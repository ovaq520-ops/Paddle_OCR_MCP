# PaddleOCR MCP Server

An MCP Server that enables text-only models (DeepSeek V4, etc.) to "see" images via OCR.

## How It Works

PaddleOCR MCP Server provides OCR capabilities to AI assistants. When the AI calls the `recognize` tool, the MCP server automatically extracts images from the current session transcript and returns all recognized text.

## Installation

```bash
# 1. Create conda environment
conda create -n paddle_ocr python=3.10
conda activate paddle_ocr

# 2. Install dependencies
pip install paddlepaddle-gpu paddleocr fastmcp

# 3. Configure Claude Code
# Add to your user-level mcp.json (~/.claude/mcp.json or %USERPROFILE%/.claude/mcp.json on Windows):
{
  "mcpServers": {
    "PaddleOCR": {
      "command": "YOUR_CONDA_PATH/python.exe",
      "args": ["YOUR_PATH/mcp_server.py"]
    }
  }
}
```

On first use, PaddleOCR automatically downloads model weights (~140MB) from ModelScope and caches them in the `models/` directory. No manual download required.

## Usage

### Method 1: Drag & Drop

Drag an image file directly into the Claude Code input box. An `[Unsupported Image]` marker will appear. After sending, the AI automatically calls OCR to recognize the text.

### Method 2: Copy & Paste

Copy an image from anywhere (screenshot tool `Ctrl+C`, right-click copy, etc.) and paste it into Claude Code with `Ctrl+V`. The same `[Unsupported Image]` marker will trigger automatic recognition.

### Method 3: Explicit File Path

Tell the AI the full path to an image file in your message. The AI will call `recognize(image_path="C:/path/to/image.png")` directly.

```
Read this image for me: C:\Users\Administrator\Desktop\screenshot.png
```

## Improving Tool Call Accuracy

External models connected to Claude Code (such as DeepSeek) may occasionally ignore the MCP tool's built-in `instructions`, resulting in the AI not calling OCR when it sees `[Unsupported Image]`.

**Solution**: Add the tool usage instructions explicitly to your `CLAUDE.md`. Since `CLAUDE.md` is injected at the system prompt level, it has higher priority than MCP tool instructions and external models are more likely to comply.

Add the following to your `CLAUDE.md`:

```markdown
## Image Processing (when model cannot see images)
When [Unsupported Image] appears in user messages, call `mcp__paddleocr__recognize` without arguments.
The MCP will automatically extract images from the current session transcript and OCR them.
Report the results as "From the image, I read the following content:" to the user.
```

> **Why this works**: MCP tool `instructions` are passed as part of tool definitions, which some models pay less attention to during tool calling decisions. `CLAUDE.md` is a system-level directive with higher compliance priority.

## Screenshots vs. Photos: Switching Recognition Modes

**Default mode** (optimized for screenshots, UI, code):

```python
# Current ocr_worker.py configuration
_ocr = PaddleOCR(
    lang="ch",
    use_textline_orientation=False,        # Skip textline orientation detection
    use_doc_orientation_classify=False,    # Skip document orientation classification
    use_doc_unwarping=False,               # Skip document unwarping
)
```

This mode loads only the detection + recognition models (~900MB RAM, ~0.3s inference). Suitable for most use cases.

**High-accuracy mode** (photos, scanned documents, rotated/curved text):

```python
_ocr = PaddleOCR(
    lang="ch",
    use_textline_orientation=True,         # Detect upside-down text lines
    use_doc_orientation_classify=True,     # Correct document rotation (0°/90°/180°/270°)
    use_doc_unwarping=True,                # Flatten curved pages
)
```

| Parameter | Purpose | Use Case |
|-----------|---------|----------|
| `use_textline_orientation` | Detect 180° text rotation | Phone held upside-down, rotated screenshots |
| `use_doc_orientation_classify` | Detect page orientation (4 directions) | Landscape photos of portrait docs, rotated PDFs |
| `use_doc_unwarping` | Flatten curved paper surfaces | Book pages, bent paper photos |

**How to switch**: Edit `ocr_worker.py` lines 48-52, change the relevant parameters to `True`, and restart Claude Code. Trade-off: 4 models loaded, ~1.7GB RAM, slightly slower inference, significantly higher accuracy.

## Hardware Requirements

|          | Minimum             | Recommended            |
|----------|---------------------|------------------------|
| GPU      | NVIDIA GTX 1050 4GB | NVIDIA RTX 3060+ 8GB   |
| VRAM     | 4 GB                | 8 GB+                  |
| RAM      | 4 GB                | 8 GB+                  |
| CUDA     | 11.2+               | 12.x                   |
| cuDNN    | 8.x                 | 9.x                    |
| Disk     | ~200MB (models)     | SSD                    |

Falls back to CPU mode if no GPU is available — 5-10x slower but still functional.

## Tools

### recognize

Recognize text from images.

- **Parameter**: `image_path` — Full path to the image file (optional; if omitted, extracts images from the current session transcript)
- **Returns**: Recognized text lines with confidence scores

### ocr_status

Check OCR engine status.

## Architecture

```
Claude Code starts → reads mcp.json → launches mcp_server.py (lightweight manager, ~85MB)
  → AI calls recognize() → manager spawns python ocr_worker.py (worker with model, ~900MB)
    → OCR completes → worker stays alive for 5 minutes → idle timeout → exits, releasing GPU
```

| Process | RAM | Lifetime |
|---------|-----|----------|
| mcp_server.py | ~85 MB | Duration of Claude Code session |
| ocr_worker.py | ~900 MB | Reused for 5 minutes after last OCR, then exits |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PADDLEOCR_CACHE` | `<script_dir>/models` | Model cache directory |
| `PADDLEOCR_SITE_PACKAGES` | (empty, no DLL dirs set) | Path to conda env's `Lib/site-packages` |
| `CLAUDE_PROJECTS_ROOT` | `~/.claude/projects` | Transcript file search root |

## License

MIT
