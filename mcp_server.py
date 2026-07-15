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

mcp = FastMCP("paddleocr")


@mcp.tool
def recognize(image_path: str) -> dict:
    """识别图片中的所有文字。参数 image_path 是图片文件的完整路径。返回每行文字的内容和置信度。"""
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


@mcp.tool
def recognize_from_transcript(transcript_path: str = "") -> dict:
    """
    从会话 transcript 中提取用户贴的图片并 OCR。
    transcript_path 可选——不传则自动在 ~/.claude/projects/ 下找最新的 transcript。
    适用于：多图粘贴（hook 只捕获最后一张）、拖文件贴图（剪贴板无图）等场景。
    """
    # ── 自动发现 transcript ──────────────────────────────────
    if transcript_path and os.path.exists(transcript_path):
        tpath = transcript_path
    else:
        try:
            claude_projects = os.path.join(Path.home(), ".claude", "projects")
            candidates = glob.glob(os.path.join(claude_projects, "*", "*.jsonl"))
            if not candidates:
                return {"error": "未找到 transcript 文件。请手动传入 transcript_path"}
            tpath = max(candidates, key=os.path.getmtime)
        except Exception as e:
            return {"error": f"自动发现 transcript 失败: {e}。请手动传入 transcript_path"}

    if not os.path.exists(tpath):
        return {"error": f"transcript 文件不存在: {tpath}"}

    # ── 读 transcript，找最新含图片的 user 消息 ──────────────
    try:
        with open(tpath, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception as e:
        return {"error": f"读取 transcript 失败: {e}"}

    target_msg = None
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
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
        return {"error": "transcript 中未找到含图片的 user 消息"}

    # ── 提取所有 base64 图片 ──────────────────────────────────
    images = []
    for c in target_msg["message"]["content"]:
        if not isinstance(c, dict):
            continue
        if c.get("type") != "image":
            continue
        src = c.get("source") or {}
        if src.get("type") != "base64":
            continue
        data = src.get("data", "")
        if not data:
            continue
        images.append({
            "media_type": src.get("media_type", "image/png"),
            "data": data,
        })

    if not images:
        return {"error": "消息中的图片不含 base64 数据"}

    # ── 解码 + 保存 + OCR ─────────────────────────────────────
    results = []
    tmp_dir = tempfile.gettempdir()
    for i, img in enumerate(images):
        try:
            raw = base64.b64decode(img["data"])
        except Exception:
            results.append({"index": i, "error": "base64 解码失败"})
            continue

        ext = ".jpg" if "jpeg" in img["media_type"] else ".png"
        filepath = os.path.join(tmp_dir, f"transcript_img_{uuid.uuid4().hex[:8]}{ext}")
        try:
            with open(filepath, "wb") as f:
                f.write(raw)
        except Exception as e:
            results.append({"index": i, "error": f"保存文件失败: {e}"})
            continue

        ocr = _get_ocr()
        try:
            ocr_result = ocr.predict(filepath)
            texts = []
            for page in ocr_result:
                rec_texts = page.get("rec_texts", [])
                rec_scores = page.get("rec_scores", [])
                for j, item in enumerate(rec_texts):
                    if isinstance(item, dict):
                        texts.append({
                            "text": item.get("text", ""),
                            "confidence": round(item.get("score", 0), 4),
                        })
                    elif isinstance(item, str):
                        score = rec_scores[j] if j < len(rec_scores) else 1.0
                        texts.append({"text": item, "confidence": round(score, 4)})
            results.append({
                "index": i,
                "image": os.path.basename(filepath),
                "text_count": len(texts),
                "texts": texts,
                "full_text": "\n".join(t["text"] for t in texts),
            })
        except Exception as e:
            results.append({"index": i, "error": f"OCR 失败: {e}"})
        finally:
            _cleanup_gpu()
            try:
                os.unlink(filepath)
            except Exception:
                pass

    return {
        "transcript": os.path.basename(tpath),
        "images_found": len(images),
        "images_processed": len([r for r in results if "full_text" in r]),
        "results": results,
    }


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
