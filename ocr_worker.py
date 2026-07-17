"""PaddleOCR Worker — 子进程常驻，stdin/stdout JSON-RPC。
启动方式: PaddleOCR.exe ocr_worker.py
"""
import os
import sys
import gc
import json
import time
import logging
import threading

# ============================================================
# 1. 环境配置（必须在 import paddleocr 之前）
# ============================================================

_CACHE = os.environ.get(
    "PADDLEOCR_CACHE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"),
)
os.environ["PADDLE_PDX_CACHE_HOME"] = _CACHE
os.environ["PADDLEX_HOME"] = _CACHE
os.environ["MODELSCOPE_CACHE"] = _CACHE
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.makedirs(_CACHE, exist_ok=True)

_SITE_PACKAGES = os.environ.get("PADDLEOCR_SITE_PACKAGES", "")
if _SITE_PACKAGES:
    _dll_dirs = [
        r"nvidia\cudnn\bin", r"nvidia\cuda_runtime\bin", r"nvidia\cublas\bin",
        r"nvidia\cufft\bin", r"nvidia\curand\bin", r"nvidia\cusparse\bin",
        r"nvidia\cusolver\bin", r"torch\lib",
    ]
    for d in _dll_dirs:
        full = os.path.join(_SITE_PACKAGES, d)
        if os.path.isdir(full):
            os.add_dll_directory(full)

logging.basicConfig(
    level=os.environ.get("PADDLEOCR_LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("PaddleOCR.Worker")

# ============================================================
# 2. 工具函数与模型加载
# ============================================================


def _str_to_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


_CUDA_DEVICES = os.environ.get("PADDLEOCR_CUDA_VISIBLE_DEVICES", "")
if _CUDA_DEVICES:
    os.environ["CUDA_VISIBLE_DEVICES"] = _CUDA_DEVICES

from paddleocr import PaddleOCR  # noqa: E402

_ocr = None


def _load_model():
    global _ocr
    lang = os.environ.get("PADDLEOCR_LANG", "ch")
    use_textline_orientation = _str_to_bool(os.environ.get("PADDLEOCR_USE_TEXTLINE_ORIENTATION", "false"))
    use_doc_orientation_classify = _str_to_bool(os.environ.get("PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY", "false"))
    use_doc_unwarping = _str_to_bool(os.environ.get("PADDLEOCR_USE_DOC_UNWARPING", "false"))
    logger.info("Loading model: lang=%s", lang)
    _ocr = PaddleOCR(
        lang=lang,
        use_textline_orientation=use_textline_orientation,
        use_doc_orientation_classify=use_doc_orientation_classify,
        use_doc_unwarping=use_doc_unwarping,
    )
    logger.info("Model loaded.")


def _cleanup_gpu():
    try:
        import paddle
        paddle.device.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()


def _parse_result(ocr_result, with_boxes: bool = False) -> list[dict]:
    texts: list[dict] = []
    for page in ocr_result:
        rec_texts = page.get("rec_texts", [])
        rec_scores = page.get("rec_scores", [])
        dt_polys = page.get("dt_polys", []) if with_boxes else []
        for i, item in enumerate(rec_texts):
            if isinstance(item, dict):
                entry = {
                    "text": item.get("text", ""),
                    "confidence": round(item.get("score", 0), 4),
                }
            elif isinstance(item, str):
                score = rec_scores[i] if i < len(rec_scores) else 1.0
                entry = {"text": item, "confidence": round(score, 4)}
            else:
                entry = {"text": str(item), "confidence": 1.0}
            if with_boxes and i < len(dt_polys):
                entry["box"] = dt_polys[i]
            texts.append(entry)
    return texts


def _to_markdown(texts: list[dict]) -> str:
    return "\n\n".join(t.get("text", "") for t in texts)

# ============================================================
# 3. 心跳看门狗
# ============================================================

IDLE_TIMEOUT = int(os.environ.get("PADDLEOCR_IDLE_TIMEOUT", "300"))
_last_request = time.time()
_idle_lock = threading.Lock()


def _bump():
    global _last_request
    with _idle_lock:
        _last_request = time.time()


def _watchdog():
    while True:
        time.sleep(5)
        with _idle_lock:
            idle = time.time() - _last_request
        if idle > IDLE_TIMEOUT:
            logger.info("Idle %.0fs, exiting.", idle)
            _cleanup_gpu()
            os._exit(0)


threading.Thread(target=_watchdog, daemon=True).start()

# ============================================================
# 4. 请求处理
# ============================================================


def _build_text_result(image_path: str, ocr_result, output_format: str = "text") -> dict:
    with_boxes = output_format == "json"
    texts = _parse_result(ocr_result, with_boxes=with_boxes)
    result = {
        "image": os.path.basename(image_path),
        "text_count": len(texts),
        "texts": texts,
        "full_text": "\n".join(t["text"] for t in texts),
    }
    if output_format == "markdown":
        result["markdown"] = _to_markdown(texts)
    return result


def _predict_with_fallback(paths: list[str]) -> list:
    """逐张预测并返回结果列表。"""
    return [_ocr.predict(p) for p in paths]


def _handle_recognize(req: dict) -> dict:
    req_id = req.get("id", "")
    single_path = req.get("image_path", "")
    multi_paths = req.get("image_paths", [])
    output_format = req.get("output_format", "text")
    if output_format not in ("text", "json", "markdown"):
        output_format = "text"
    if single_path and not multi_paths:
        multi_paths = [single_path]
    if not multi_paths:
        return {"id": req_id, "error": "No image path provided"}
    valid_paths: list[str] = []
    missing_indices: list[int] = []
    for i, path in enumerate(multi_paths):
        if os.path.exists(path):
            valid_paths.append(path)
        else:
            missing_indices.append(i)
    results: list = [None] * len(multi_paths)
    for i in missing_indices:
        results[i] = {"error": f"File not found: {multi_paths[i]}"}
    if valid_paths:
        try:
            ocr_results = _predict_with_fallback(valid_paths)
            valid_idx = 0
            for i in range(len(multi_paths)):
                if results[i] is None:
                    results[i] = _build_text_result(valid_paths[valid_idx], ocr_results[valid_idx], output_format)
                    valid_idx += 1
        except Exception as exc:
            logger.exception("OCR batch failed")
            for i in range(len(multi_paths)):
                if results[i] is None:
                    results[i] = {"error": f"OCR failed: {exc}"}
    if single_path and len(results) == 1:
        if "error" in results[0]:
            return {"id": req_id, "error": results[0]["error"]}
        return {"id": req_id, "result": results[0]}
    return {"id": req_id, "result": {"batch": True, "results": results}}


def _handle_status(req: dict) -> dict:
    return {"id": req.get("id", ""), "result": {
        "loaded": True, "language": os.environ.get("PADDLEOCR_LANG", "ch"), "status": "ready",
    }}


def _handle_set_language(req: dict) -> dict:
    req_id = req.get("id", "")
    lang = req.get("lang", "")
    if not lang:
        return {"id": req_id, "error": "lang is required"}
    try:
        os.environ["PADDLEOCR_LANG"] = lang
        _load_model()
        return {"id": req_id, "result": {"language": lang, "status": "ready"}}
    except Exception as exc:
        logger.exception("Failed to switch language to %s", lang)
        return {"id": req_id, "error": f"Failed to switch language: {exc}"}


def _handle_shutdown(req: dict) -> dict:
    sys.stdout.write(json.dumps(
        {"id": req.get("id", ""), "result": "ok"}, ensure_ascii=False
    ) + "\n")
    sys.stdout.flush()
    _cleanup_gpu()
    sys.exit(0)

# ============================================================
# 5. 主循环
# ============================================================


def main():
    _load_model()
    sys.stdout.write(json.dumps({"status": "ready"}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    logger.info("Worker ready (idle_timeout=%ds).", IDLE_TIMEOUT)
    for line in sys.stdin:
        _bump()
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(
                {"id": "", "error": f"Invalid JSON: {exc}"}, ensure_ascii=False
            ) + "\n")
            sys.stdout.flush()
            continue
        method = req.get("method", "")
        if method == "recognize":
            resp = _handle_recognize(req)
        elif method == "ocr_status":
            resp = _handle_status(req)
        elif method == "set_language":
            resp = _handle_set_language(req)
        elif method == "shutdown":
            resp = _handle_shutdown(req)
        else:
            resp = {"id": req.get("id", ""), "error": f"Unknown method: {method}"}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
