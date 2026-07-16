"""
PaddleOCR Worker — 子进程常驻 60 秒，stdin/stdout JSON-RPC。
启动方式: PaddleOCR.exe ocr_worker.py
"""
import os
import sys
import gc
import json
import time
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

# ============================================================
# 2. 模型（常驻，只加载一次）
# ============================================================

from paddleocr import PaddleOCR  # noqa: E402

_ocr = None


def _load_model():
    global _ocr
    _ocr = PaddleOCR(
        lang="ch",
        use_textline_orientation=False,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )


def _cleanup_gpu():
    try:
        import paddle
        paddle.device.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()


def _parse_result(ocr_result) -> list[dict]:
    texts: list[dict] = []
    for page in ocr_result:
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
    return texts


# ============================================================
# 3. 心跳看门狗（60 秒无请求 → 退出）
# ============================================================

IDLE_TIMEOUT = 300
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
            sys.stderr.write(f"[PaddleOCR Worker] idle {idle:.0f}s, exiting.\n")
            sys.stderr.flush()
            _cleanup_gpu()
            os._exit(0)


threading.Thread(target=_watchdog, daemon=True).start()

# ============================================================
# 4. 主循环：stdin 读请求 → stdout 写结果
# ============================================================


def main():
    _load_model()

    # 发就绪信号，主进程等待此行后才发送第一个请求
    sys.stdout.write(json.dumps({"status": "ready"}, ensure_ascii=False) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        _bump()
        line = line.strip()
        if not line:
            continue

        # 解析请求
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps(
                {"id": "", "error": f"Invalid JSON: {e}"}, ensure_ascii=False
            ) + "\n")
            sys.stdout.flush()
            continue

        req_id = req.get("id", "")
        method = req.get("method", "")

        try:
            if method == "recognize":
                image_path = req.get("image_path", "")
                if not image_path or not os.path.exists(image_path):
                    resp = {"id": req_id, "error": f"File not found: {image_path}"}
                else:
                    ocr_result = _ocr.predict(image_path)
                    texts = _parse_result(ocr_result)
                    resp = {"id": req_id, "result": {
                        "image": os.path.basename(image_path),
                        "text_count": len(texts),
                        "texts": texts,
                        "full_text": "\n".join(t["text"] for t in texts),
                    }}

            elif method == "ocr_status":
                resp = {"id": req_id, "result": {
                    "loaded": True, "language": "ch", "status": "ready",
                }}

            elif method == "shutdown":
                sys.stdout.write(json.dumps(
                    {"id": req_id, "result": "ok"}, ensure_ascii=False
                ) + "\n")
                sys.stdout.flush()
                _cleanup_gpu()
                sys.exit(0)

            else:
                resp = {"id": req_id, "error": f"Unknown method: {method}"}

        except Exception as e:
            resp = {"id": req_id, "error": str(e)}

        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        _cleanup_gpu()


if __name__ == "__main__":
    main()
