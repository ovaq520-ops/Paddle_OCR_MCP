"""
PaddleOCR MCP Server
让 AI 能调用 PaddleOCR 识别图片中的文字。
模型在对话期间常驻内存，每次 OCR 后清理临时显存碎片。
启动方式: python mcp_server.py
"""
import os
import sys
import gc
import json
import glob
import base64
import uuid
import tempfile
from pathlib import Path

# ============================================================
# 1. 环境配置（必须在 import paddleocr 之前）
# ============================================================

_CACHE = r"E:\soft\OCR\Paddle_ocr\models"
os.environ["PADDLE_PDX_CACHE_HOME"] = _CACHE
os.environ["PADDLEX_HOME"] = _CACHE
os.environ["MODELSCOPE_CACHE"] = _CACHE
os.makedirs(_CACHE, exist_ok=True)

_ENV = r"E:\soft\anaconda3\envs\paddle_ocr\Lib\site-packages"
_dll_dirs = [
    r"nvidia\cudnn\bin", r"nvidia\cuda_runtime\bin", r"nvidia\cublas\bin",
    r"nvidia\cufft\bin", r"nvidia\curand\bin", r"nvidia\cusparse\bin",
    r"nvidia\cusolver\bin", r"torch\lib",
]
for d in _dll_dirs:
    full = os.path.join(_ENV, d)
    if os.path.isdir(full):
        os.add_dll_directory(full)

# ============================================================
# 2. 初始化 PaddleOCR（常驻内存）
# ============================================================

from paddleocr import PaddleOCR  # noqa: E402

_ocr = None

def _get_ocr():
    """懒加载模型，整个对话生命周期只加载一次"""
    global _ocr
    if _ocr is None:
        _ocr = PaddleOCR(lang="ch", use_textline_orientation=False)
    return _ocr

def _cleanup_gpu():
    """释放本次 OCR 产生的临时显存碎片，不卸载模型"""
    try:
        import paddle
        paddle.device.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()

# ============================================================
# 3. MCP Server
# ============================================================

from fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "paddleocr",
    instructions="""
当你看到 [Unsupported Image] 时，调用 recognize() 不传参数。
MCP 会自动从当前会话 transcript 中提取所有图片并 OCR，无论贴了几张、是粘贴还是拖文件。
如果你知道确切的图片路径，也可以传 image_path 参数直接读取。
""",
)


# ── 共享：transcript 提取 + OCR ─────────────────────────────

def _ocr_from_transcript(transcript_path: str = ""):
    """从 transcript 提取所有图片并 OCR。内部函数，被 recognize 和 recognize_from_transcript 复用。"""
    import json as _json, base64 as _base64, uuid as _uuid, glob as _glob, tempfile as _tempfile
    from pathlib import Path as _Path

    if transcript_path and os.path.exists(transcript_path):
        tpath = transcript_path
    else:
        root = os.path.join(_Path.home(), ".claude", "projects")
        candidates = _glob.glob(os.path.join(root, "*", "*.jsonl"))
        if not candidates:
            return {"error": "未找到 transcript 文件"}
        tpath = max(candidates, key=os.path.getmtime)

    if not os.path.exists(tpath):
        return {"error": f"文件不存在: {tpath}"}

    try:
        with open(tpath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception as e:
        return {"error": f"读取失败: {e}"}

    target_msg = None
    for line in reversed(lines):
        try:
            obj = _json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "user": continue
        msg = obj.get("message") or {}
        if msg.get("role") != "user": continue
        content = msg.get("content")
        if not isinstance(content, list): continue
        if any(c.get("type") == "image" for c in content if isinstance(c, dict)):
            target_msg = obj; break

    if not target_msg:
        return {"error": "未找到含图片的 user 消息"}

    images = []
    for c in target_msg["message"]["content"]:
        if not isinstance(c, dict) or c.get("type") != "image": continue
        src = c.get("source") or {}
        if src.get("type") != "base64": continue
        data = src.get("data", "")
        if data:
            images.append({"media_type": src.get("media_type", "image/png"), "data": data})

    if not images:
        return {"error": "不含 base64 数据"}

    results = []
    tmp_dir = _tempfile.gettempdir()
    for i, img in enumerate(images):
        try: raw = _base64.b64decode(img["data"])
        except Exception: results.append({"index": i, "error": "base64 解码失败"}); continue
        ext = ".jpg" if "jpeg" in img["media_type"] else ".png"
        fp = os.path.join(tmp_dir, f"ts_{_uuid.uuid4().hex[:8]}{ext}")
        try:
            with open(fp, "wb") as f: f.write(raw)
        except Exception as e:
            results.append({"index": i, "error": str(e)}); continue
        ocr = _get_ocr()
        try:
            ocr_result = ocr.predict(fp)
            texts = []
            for page in ocr_result:
                rt = page.get("rec_texts", []); rs = page.get("rec_scores", [])
                for j, item in enumerate(rt):
                    if isinstance(item, dict):
                        texts.append({"text": item.get("text", ""), "confidence": round(item.get("score", 0), 4)})
                    elif isinstance(item, str):
                        s = rs[j] if j < len(rs) else 1.0
                        texts.append({"text": item, "confidence": round(s, 4)})
            results.append({"index": i, "text_count": len(texts), "full_text": "\n".join(t["text"] for t in texts)})
        except Exception as e:
            results.append({"index": i, "error": str(e)})
        finally:
            _cleanup_gpu()
            try: os.unlink(fp)
            except Exception: pass

    return {"transcript": os.path.basename(tpath), "images_found": len(images), "results": results}


# ── 工具 ─────────────────────────────────────────────────────

@mcp.tool
def recognize(image_path: str = "") -> dict:
    """
    识别图片中的文字。
    不传 image_path → 自动从当前会话 transcript 中提取所有图片并 OCR。
    传 image_path → 直接 OCR 指定文件。
    """
    # 无路径 → transcript 兜底
    if not image_path:
        return _ocr_from_transcript()

    # 有路径 → 直接 OCR
    if not os.path.exists(image_path):
        return {"error": f"文件不存在: {image_path}"}

    ocr = _get_ocr()
    try:
        result = ocr.predict(image_path)
        texts = []
        for page in result:
            rec_texts = page.get("rec_texts", [])
            rec_scores = page.get("rec_scores", [])
            for i, item in enumerate(rec_texts):
                if isinstance(item, dict):
                    texts.append({
                        "text": item.get("text", ""),
                        "confidence": round(item.get("score", 0), 4),
                    })
                elif isinstance(item, str):
                    score = rec_scores[i] if i < len(rec_scores) else 1.0
                    texts.append({"text": item, "confidence": round(score, 4)})
        return {
            "image": os.path.basename(image_path),
            "text_count": len(texts),
            "texts": texts,
            "full_text": "\n".join(t["text"] for t in texts),
        }
    finally:
        _cleanup_gpu()


# recognize_from_transcript tool body — injected into mcp_server.py
@mcp.tool
def recognize_from_transcript(transcript_path: str = "") -> dict:
    """
    从会话 transcript 中提取图片并 OCR（等同于 recognize() 不传参）。
    保留此工具作为独立入口，便于 AI 明确意图时直接调用。
    """
    return _ocr_from_transcript(transcript_path)


@mcp.tool
def ocr_status() -> dict:
    """检查 OCR 引擎状态。"""
    try:
        _get_ocr()
        return {"loaded": True, "language": "ch", "model_dir": _CACHE, "status": "ready"}
    except Exception as e:
        return {"loaded": False, "error": str(e), "status": "error"}


if __name__ == "__main__":
    sys.stderr.write("[paddleocr] Loading model...\n")
    sys.stderr.flush()
    # 启动时预加载模型（可注释掉改为懒加载）
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr
    try:
        _get_ocr()
    finally:
        sys.stdout = _real_stdout
    sys.stderr.write("[paddleocr] Model ready.\n")
    sys.stderr.flush()
    mcp.run()
