"""
PaddleOCR MCP Server — 轻量进程管理器。
自身不加载模型（内存 ~0 MB），按需启动 PaddleOCR.exe 子进程。
子进程常驻 300 秒（5 分钟），无请求自动退出。

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
from pathlib import Path

# ============================================================
# 1. 子进程管理
# ============================================================

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKER_SCRIPT = os.path.join(_THIS_DIR, "ocr_worker.py")
_PYTHON_EXE = os.path.join(os.path.dirname(sys.executable), "PaddleOCR.exe")
if not os.path.exists(_PYTHON_EXE):
    _PYTHON_EXE = sys.executable  # fallback: 没找到 hardlink 就用原始 python.exe

_worker_proc = None
_worker_lock = threading.Lock()


def _ensure_worker():
    """确保子进程存活。已死则重新启动。"""
    global _worker_proc

    with _worker_lock:
        # 检查是否还活着
        if _worker_proc is not None and _worker_proc.poll() is None:
            return

        # 清理僵尸进程
        if _worker_proc is not None:
            try:
                _worker_proc.kill()
                _worker_proc.wait(timeout=3)
            except Exception:
                pass
            _worker_proc = None

        # 启动新子进程
        sys.stderr.write("[PaddleOCR] Starting worker...\n")
        sys.stderr.flush()
        _worker_proc = subprocess.Popen(
            [_PYTHON_EXE, _WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        # 等待就绪信号（超时 30 秒）
        try:
            line = _worker_proc.stdout.readline()
            data = json.loads(line)
            if data.get("status") != "ready":
                raise RuntimeError(f"Worker not ready: {data}")
        except Exception:
            try:
                _worker_proc.kill()
            except Exception:
                pass
            _worker_proc = None
            raise RuntimeError("PaddleOCR Worker 启动失败")

        sys.stderr.write("[PaddleOCR] Worker ready.\n")
        sys.stderr.flush()


def _send_to_worker(method: str, **params) -> dict:
    """向子进程发送请求，返回 result dict（不含 error key 则成功）。"""
    global _worker_proc

    req_id = uuid.uuid4().hex[:8]
    req = {"id": req_id, "method": method}
    req.update(params)
    payload = json.dumps(req, ensure_ascii=False) + "\n"

    _ensure_worker()

    # 发送请求 + 读取响应，worker 崩溃时重试一次
    for attempt in (1, 2):
        try:
            _worker_proc.stdin.write(payload)
            _worker_proc.stdin.flush()
            line = _worker_proc.stdout.readline()
            if not line:
                raise RuntimeError("Worker closed stdout")
            resp = json.loads(line)
            break
        except (BrokenPipeError, RuntimeError):
            if attempt == 2:
                raise
            # Worker 崩溃，强制重启
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
    """atexit 回调：优雅关闭子进程"""
    global _worker_proc
    if _worker_proc is None or _worker_proc.poll() is not None:
        return
    try:
        _worker_proc.stdin.write(json.dumps(
            {"id": "0", "method": "shutdown"}, ensure_ascii=False
        ) + "\n")
        _worker_proc.stdin.flush()
        _worker_proc.wait(timeout=3)
    except Exception:
        try:
            _worker_proc.kill()
        except Exception:
            pass


atexit.register(_kill_worker)


# ============================================================
# 2. Transcript 图片提取（纯 IO，不涉及模型）
# ============================================================


def _ocr_from_transcript(transcript_path: str = "") -> dict:
    """
    从 transcript JSONL 中提取最近一条 user 消息里的 base64 图片，
    保存为临时文件后交给子进程 OCR。

    定位优先级（从高到低）：
    1. transcript_path 是完整路径且存在 → 直接使用（显式覆盖）
    2. CLAUDE_CODE_SESSION_ID 可用 → 精确文件名匹配 {session_id}.jsonl（确定性）
    3. transcript_path 是纯文件名 → 精确匹配 + mtime 兜底（AI 传的，不可靠）
    4. 什么都没有 → mtime 最新（最后兜底，多窗口时可能串）
    """
    if transcript_path and os.path.exists(transcript_path):
        # 优先级 1：显式完整路径
        tpath = transcript_path
    else:
        root = os.environ.get(
            "CLAUDE_PROJECTS_ROOT",
            os.path.join(Path.home(), ".claude", "projects"),
        )
        candidates = glob.glob(os.path.join(root, "*", "*.jsonl"))
        if not candidates:
            return {"error": "未找到 transcript 文件"}

        # 优先级 2：系统注入的 session_id，100% 可靠
        session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
        if session_id:
            target = f"{session_id}.jsonl"
            matched = [c for c in candidates if os.path.basename(c) == target]
            if matched:
                tpath = matched[0]
            else:
                return {"error": f"当前会话 transcript 未找到 (session_id={session_id})"}
        elif transcript_path:
            # 优先级 3：AI 传的裸文件名 → 精确匹配 + mtime 兜底
            matched = [c for c in candidates if os.path.basename(c) == transcript_path]
            tpath = matched[0] if matched else max(candidates, key=os.path.getmtime)
        else:
            # 优先级 4：最终兜底 — mtime 最新（多窗口时可能串）
            tpath = max(candidates, key=os.path.getmtime)

    if not os.path.exists(tpath):
        return {"error": f"文件不存在: {tpath}"}

    try:
        with open(tpath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception as e:
        return {"error": f"读取失败: {e}"}

    # 从后往前找最近一条含图片的 user 消息
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
        return {"error": "未找到含图片的 user 消息"}

    # 提取所有 base64 图片
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

    if not images:
        return {"error": "不含 base64 数据"}

    # 逐张保存临时文件 → 交给子进程 OCR
    results = []
    tmp_dir = tempfile.gettempdir()
    for i, img in enumerate(images):
        try:
            raw = base64.b64decode(img["data"])
        except Exception:
            results.append({"index": i, "error": "base64 解码失败"})
            continue

        ext = ".jpg" if "jpeg" in img["media_type"] else ".png"
        fp = os.path.join(tmp_dir, f"ts_{uuid.uuid4().hex[:8]}{ext}")
        try:
            with open(fp, "wb") as f:
                f.write(raw)
        except Exception as e:
            results.append({"index": i, "error": str(e)})
            continue

        r = _send_to_worker("recognize", image_path=fp)
        if "error" in r:
            results.append({"index": i, "error": r["error"]})
        else:
            results.append({
                "index": i,
                "text_count": r.get("text_count", 0),
                "full_text": r.get("full_text", ""),
            })

        try:
            os.unlink(fp)
        except Exception:
            pass

    return {
        "transcript": os.path.basename(tpath),
        "images_found": len(images),
        "results": results,
    }


# ============================================================
# 3. MCP Server
# ============================================================

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "PaddleOCR",
    instructions="""
当你看到 [Unsupported Image] 时，调用 recognize() 不传参数。
MCP 会自动从当前会话 transcript 中提取所有图片并 OCR。
如果你知道确切的图片文件路径，也可以传 image_path 参数直接读取。
""",
)


@mcp.tool
def recognize(image_path: str = "", transcript_path: str = "") -> dict:
    """
    识别图片中的文字。
    不传 image_path → 自动从当前会话 transcript 中提取所有图片并 OCR。
    传 image_path → 直接 OCR 指定文件。
    transcript_path 通常无需传入，系统会自动定位当前会话。
    """
    # 无路径 → transcript 兜底
    if not image_path:
        return _ocr_from_transcript(transcript_path)

    # 有路径 → 直接发给子进程 OCR
    if not os.path.exists(image_path):
        return {"error": f"文件不存在: {image_path}"}

    r = _send_to_worker("recognize", image_path=image_path)
    if "error" in r:
        return r
    return r


@mcp.tool
def ocr_status() -> dict:
    """检查 OCR 引擎状态。"""
    try:
        return _send_to_worker("ocr_status")
    except Exception as e:
        return {"loaded": False, "error": str(e), "status": "error"}


if __name__ == "__main__":
    sys.stderr.write("[PaddleOCR] MCP Server started (process manager mode).\n")
    sys.stderr.flush()
    mcp.run()
