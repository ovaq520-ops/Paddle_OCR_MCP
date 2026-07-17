"""PaddleOCR MCP Server — 轻量进程管理器。
自身不加载模型，按需启动 PaddleOCR 子进程。
子进程空闲自动退出，超时时间由 PADDLEOCR_IDLE_TIMEOUT 控制。

启动方式: python mcp_server.py
"""
import os
import sys
import json
import glob
import base64
import uuid
import tempfile
import subprocess
import threading
import atexit
import logging
from pathlib import Path
from typing import Optional, List

# ============================================================
# 1. 配置与日志
# ============================================================

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKER_SCRIPT = os.path.join(_THIS_DIR, "ocr_worker.py")

_PYTHON_EXE = os.environ.get("PADDLEOCR_PYTHON") or os.path.join(
    os.path.dirname(sys.executable), "PaddleOCR.exe"
)
if not os.path.exists(_PYTHON_EXE):
    _PYTHON_EXE = sys.executable

_IDLE_TIMEOUT = int(os.environ.get("PADDLEOCR_IDLE_TIMEOUT", "300"))

logging.basicConfig(
    level=os.environ.get("PADDLEOCR_LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("PaddleOCR")

# ============================================================
# 2. 子进程管理
# ============================================================

_worker_proc: Optional[subprocess.Popen] = None
_worker_lock = threading.Lock()


def _ensure_worker():
    """确保子进程存活。已死则重新启动。"""
    global _worker_proc
    with _worker_lock:
        if _worker_proc is not None and _worker_proc.poll() is None:
            return
        if _worker_proc is not None:
            try:
                _worker_proc.kill()
                _worker_proc.wait(timeout=3)
            except Exception:
                pass
            _worker_proc = None
        logger.info("Starting worker...")
        env = os.environ.copy()
        env["PADDLEOCR_IDLE_TIMEOUT"] = str(_IDLE_TIMEOUT)
        _worker_proc = subprocess.Popen(
            [_PYTHON_EXE, _WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )
        try:
            line = _worker_proc.stdout.readline()
            data = json.loads(line)
            if data.get("status") != "ready":
                raise RuntimeError(f"Worker not ready: {data}")
        except Exception as exc:
            try:
                _worker_proc.kill()
            except Exception:
                pass
            _worker_proc = None
            raise RuntimeError(f"PaddleOCR Worker 启动失败: {exc}")
        logger.info("Worker ready.")


def _send_to_worker(method: str, **params) -> dict:
    """向子进程发送请求，返回 result dict（不含 error key 则成功）。"""
    global _worker_proc
    req_id = uuid.uuid4().hex[:8]
    req = {"id": req_id, "method": method}
    # 防止 params 覆盖 id/method
    for key, value in params.items():
        if key not in req:
            req[key] = value
    payload = json.dumps(req, ensure_ascii=False) + "\n"
    _ensure_worker()
    for attempt in (1, 2):
        try:
            _worker_proc.stdin.write(payload)
            _worker_proc.stdin.flush()
            line = _worker_proc.stdout.readline()
            if not line:
                raise RuntimeError("Worker closed stdout")
            resp = json.loads(line)
            break
        except (BrokenPipeError, json.JSONDecodeError, RuntimeError) as exc:
            logger.warning("Worker communication failed (attempt %d): %s", attempt, exc)
            if attempt == 2:
                raise
            with _worker_lock:
                if _worker_proc is not None:
                    try:
                        _worker_proc.kill()
                    except Exception:
                        pass
                    _worker_proc = None
            _ensure_worker()
    if "error" in resp:
        return {"error": resp["error"]}
    return resp.get("result", {})


def _kill_worker():
    """atexit 回调：优雅关闭子进程。"""
    global _worker_proc
    if _worker_proc is None or _worker_proc.poll() is not None:
        return
    try:
        _worker_proc.stdin.write(json.dumps(
            {"id": "0", "method": "shutdown"}, ensure_ascii=False
        ) + "\n")
        _worker_proc.stdin.flush()
        _worker_proc.wait(timeout=3)
        logger.info("Worker shut down.")
    except Exception:
        try:
            _worker_proc.kill()
        except Exception:
            pass


atexit.register(_kill_worker)

# ============================================================
# 3. Transcript 图片提取
# ============================================================


def _find_transcript(transcript_path: str = "") -> str:
    """定位 transcript 文件路径。"""
    if transcript_path and os.path.exists(transcript_path):
        return transcript_path
    root = os.environ.get(
        "CLAUDE_PROJECTS_ROOT",
        os.path.join(Path.home(), ".claude", "projects"),
    )
    candidates = glob.glob(os.path.join(root, "*", "*.jsonl"))
    if not candidates:
        return ""
    return max(candidates, key=os.path.getmtime)


def _extract_images_from_transcript(tpath: str) -> list[dict]:
    """从 transcript JSONL 中提取最近一轮 user 消息里的所有 base64 图片。"""
    try:
        with open(tpath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception as exc:
        raise RuntimeError(f"读取失败: {exc}")
    target_msg = None
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "user":
            continue
        msg = obj.get("message") or {}
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        if any(c.get("type") == "image" for c in content if isinstance(c, dict)):
            target_msg = obj
            break
    if not target_msg:
        return []
    images = []
    for c in target_msg["message"]["content"]:
        if not isinstance(c, dict) or c.get("type") != "image":
            continue
        src = c.get("source") or {}
        if src.get("type") != "base64":
            continue
        data = src.get("data", "")
        if data:
            images.append({
                "media_type": src.get("media_type", "image/png"),
                "data": data,
            })
    return images


def _save_base64_image(img: dict, tmp_dir: str) -> str:
    """解码 base64 图片并保存为临时文件，返回路径。"""
    raw = base64.b64decode(img["data"])
    ext = ".jpg" if "jpeg" in img["media_type"] else ".png"
    fp = os.path.join(tmp_dir, f"ts_{uuid.uuid4().hex[:8]}{ext}")
    with open(fp, "wb") as f:
        f.write(raw)
    return fp


def _ocr_from_transcript(transcript_path: str = "", output_format: str = "text") -> dict:
    """从 transcript 提取图片并批量 OCR。"""
    tpath = _find_transcript(transcript_path)
    if not tpath:
        return {"success": False, "error": "未找到 transcript 文件", "results": []}
    try:
        images = _extract_images_from_transcript(tpath)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc), "results": []}
    if not images:
        return {"success": False, "error": "未找到含图片的 user 消息或不含 base64 数据", "results": []}
    tmp_dir = tempfile.gettempdir()
    tmp_paths: list[tuple[int, str]] = []
    results: list[dict] = []
    for i, img in enumerate(images):
        try:
            fp = _save_base64_image(img, tmp_dir)
            tmp_paths.append((i, fp))
        except Exception as exc:
            results.append({"index": i, "error": str(exc)})
    if tmp_paths:
        paths = [fp for _, fp in tmp_paths]
        r = _send_to_worker("recognize", image_paths=paths, output_format=output_format)
        if "error" in r:
            for i, _ in tmp_paths:
                results.append({"index": i, "error": r["error"]})
        else:
            batch_results = r.get("results", [])
            if len(batch_results) != len(tmp_paths):
                batch_results = [r]
            for (i, _), br in zip(tmp_paths, batch_results):
                if "error" in br:
                    results.append({"index": i, "error": br["error"]})
                else:
                    results.append({
                        "index": i,
                        "image": br.get("image", ""),
                        "text_count": br.get("text_count", 0),
                        "texts": br.get("texts", []),
                        "full_text": br.get("full_text", ""),
                        "markdown": br.get("markdown", "") if output_format == "markdown" else "",
                    })
        for _, fp in tmp_paths:
            try:
                os.unlink(fp)
            except Exception:
                pass
    return {
        "success": True,
        "source": "transcript",
        "transcript": os.path.basename(tpath),
        "images_found": len(images),
        "results": results,
    }

# ============================================================
# 4. MCP Server
# ============================================================

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "PaddleOCR",
    instructions="""
当你看到 [Unsupported Image] 时，调用 recognize() 不传参数。
MCP 会自动从当前会话 transcript 中提取所有图片并 OCR。
如果你知道确切的图片路径，也可以传 image_path 参数直接读取。
""",
)


def _normalize_result(r: dict, image: str = "", output_format: str = "text") -> dict:
    """统一 recognize 返回值结构。"""
    if "error" in r:
        return {"success": False, "error": r["error"], "results": []}
    entry = {
        "index": 0,
        "image": r.get("image", image),
        "text_count": r.get("text_count", 0),
        "texts": r.get("texts", []),
        "full_text": r.get("full_text", ""),
    }
    if output_format == "markdown":
        entry["markdown"] = r.get("markdown", "")
    return {
        "success": True,
        "source": "image_path",
        "images_found": 1,
        "results": [entry],
    }


@mcp.tool
def recognize(image_path: str = "", output_format: str = "text") -> dict:
    """识别图片中的文字。
    不传 image_path → 自动从当前会话 transcript 提取所有图片。
    传 image_path → 直接 OCR 指定文件。
    output_format: text（默认）/ json / markdown
    """
    try:
        if not image_path:
            return _ocr_from_transcript(output_format=output_format)
        if not os.path.exists(image_path):
            return {"success": False, "error": f"文件不存在: {image_path}", "results": []}
        r = _send_to_worker("recognize", image_path=image_path, output_format=output_format)
        return _normalize_result(r, image=os.path.basename(image_path), output_format=output_format)
    except Exception as exc:
        logger.error("recognize failed: %s", exc)
        return {"success": False, "error": str(exc), "results": []}


@mcp.tool
def recognize_batch(image_paths: Optional[List[str]] = None, output_format: str = "text") -> dict:
    """批量识别多张图片中的文字。
    output_format: text（默认）/ json / markdown
    """
    try:
        if not image_paths:
            return {"success": False, "error": "image_paths 不能为空", "results": []}
        valid_paths: list[tuple[int, str]] = []
        results: list[dict] = []
        for i, p in enumerate(image_paths):
            if os.path.exists(p):
                valid_paths.append((i, p))
            else:
                results.append({"index": i, "error": f"文件不存在: {p}"})
        if not valid_paths:
            return {"success": False, "error": "所有路径均无效", "results": results}
        paths = [p for _, p in valid_paths]
        r = _send_to_worker("recognize", image_paths=paths, output_format=output_format)
        if "error" in r:
            return {"success": False, "error": r["error"], "results": results}
        batch_results = r.get("results", [])
        for (i, p), br in zip(valid_paths, batch_results):
            if "error" in br:
                results.append({"index": i, "error": br["error"]})
            else:
                entry = {
                    "index": i,
                    "image": br.get("image", os.path.basename(p)),
                    "text_count": br.get("text_count", 0),
                    "texts": br.get("texts", []),
                    "full_text": br.get("full_text", ""),
                }
                if output_format == "markdown":
                    entry["markdown"] = br.get("markdown", "")
                results.append(entry)
        return {
            "success": True,
            "source": "batch",
            "images_found": len(image_paths),
            "results": results,
        }
    except Exception as exc:
        logger.error("recognize_batch failed: %s", exc)
        return {"success": False, "error": str(exc), "results": []}


@mcp.tool
def list_languages() -> dict:
    """列出支持的 OCR 语言。"""
    return {
        "success": True,
        "languages": [
            {"code": "ch", "name": "简体中文"},
            {"code": "en", "name": "English"},
            {"code": "japan", "name": "日本語"},
            {"code": "korean", "name": "한국어"},
            {"code": "chinese_cht", "name": "繁體中文"},
            {"code": "ta", "name": "தமிழ்"},
            {"code": "te", "name": "తెలుగు"},
            {"code": "ka", "name": "ಕನ್ನಡ"},
            {"code": "latin", "name": "Latin"},
            {"code": "arabic", "name": "العربية"},
            {"code": "cyrillic", "name": "Cyrillic"},
            {"code": "devanagari", "name": "Devanagari"},
        ],
    }


@mcp.tool
def set_language(lang: str) -> dict:
    """切换 OCR 语言模型。切换后后续识别均使用新语言。"""
    try:
        if not lang:
            return {"success": False, "error": "lang 不能为空"}
        r = _send_to_worker("set_language", lang=lang)
        if "error" in r:
            return {"success": False, "error": r["error"]}
        return {"success": True, "language": r.get("language", lang), "status": r.get("status", "ready")}
    except Exception as exc:
        logger.error("set_language failed: %s", exc)
        return {"success": False, "error": str(exc)}


@mcp.tool
def ocr_status() -> dict:
    """检查 OCR 引擎状态。"""
    try:
        r = _send_to_worker("ocr_status")
        return {"success": True, "loaded": r.get("loaded", False), "status": r.get("status", "unknown")}
    except Exception as exc:
        logger.error("ocr_status failed: %s", exc)
        return {"success": False, "loaded": False, "error": str(exc), "status": "error"}


if __name__ == "__main__":
    logger.info("MCP Server started (process manager mode).")
    mcp.run()
