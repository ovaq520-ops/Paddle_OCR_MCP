@mcp.tool
def recognize_from_transcript(transcript_path: str = "") -> dict:
    """
    从会话 transcript 中提取图片并 OCR（等同于 recognize() 不传参）。
    保留此工具作为独立入口，便于 AI 明确意图时直接调用。
    """
    return _ocr_from_transcript(transcript_path)
