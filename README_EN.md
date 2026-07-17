# PaddleOCR MCP Server

[![中文](https://img.shields.io/badge/lang-中文-red)](README.md)
[![English](https://img.shields.io/badge/lang-English-blue)](README_EN.md)

An MCP Server that enables text-only models (DeepSeek V4, etc.) to "see" images via OCR.

## How It Works

PaddleOCR MCP Server provides OCR capabilities to AI assistants. When the AI calls the `recognize` tool, the MCP server automatically extracts images from the current session transcript and returns all recognized text.

## Installation

### 1. Create Environment & Install Dependencies

```bash
conda create -n paddle_ocr python=3.10
conda activate paddle_ocr

pip install paddlepaddle-gpu paddleocr fastmcp
```

On first use, PaddleOCR automatically downloads model weights (~140MB) from ModelScope and caches them in the `models/` directory. No manual download required.

### 2. Register the MCP Server

PaddleOCR works with the following AI coding tools:

| Platform | Config File (User) | Config File (Project) | Format | Status |
|----------|-------------------|----------------------|:--:|:--:|
| **Claude Code** | `~/.claude.json` `mcpServers` field | `<project>/.mcp.json` | JSON | ✅ Verified |
| **Codex** | `~/.codex/config.toml` | `<project>/.codex/config.toml` | TOML | ⚠️ Web research, untested |
| **Cursor** | `~/.cursor/mcp.json` | `<project>/.cursor/mcp.json` | JSON | ⚠️ Web research, untested |
| **Trae** | `~/.trae/mcp.json` | `<project>/.trae/mcp.json` | JSON | ⚠️ Web research, untested |

> **User-level** registration is recommended — configure once, available in all projects.

#### Claude Code (Verified)

Edit `~/.claude.json`, add under the `mcpServers` field:

```json
{
  "mcpServers": {
    "PaddleOCR": {
      "command": "E:/soft/anaconda3/envs/paddle_ocr/python.exe",
      "args": ["E:/soft/OCR/Paddle_ocr/mcp_server.py"]
    }
  }
}
```

> **Note**: If `mcpServers` already exists in `~/.claude.json`, merge `PaddleOCR` into it. You can also use the dedicated `~/.claude/mcp.json` file — just don't configure both simultaneously, or the MCP will be loaded twice.

#### Codex (Web Research, untested)

```toml
[mcp_servers.PaddleOCR]
command = "E:/soft/anaconda3/envs/paddle_ocr/python.exe"
args = ["E:/soft/OCR/Paddle_ocr/mcp_server.py"]
startup_timeout_sec = 30
tool_timeout_sec = 120
```

Or add via CLI:

```bash
codex mcp add PaddleOCR -- "E:/soft/anaconda3/envs/paddle_ocr/python.exe" "E:/soft/OCR/Paddle_ocr/mcp_server.py"
```

Restart Codex terminal after configuration. Verify with `codex mcp list`.

#### Cursor (Web Research, untested)

```json
{
  "mcpServers": {
    "PaddleOCR": {
      "command": "E:/soft/anaconda3/envs/paddle_ocr/python.exe",
      "args": ["E:/soft/OCR/Paddle_ocr/mcp_server.py"]
    }
  }
}
```

After saving, check Cursor Settings → MCP panel for a green indicator. `Cmd+Shift+P` → `MCP: Reload Servers` to refresh.

> On Windows, if issues arise, wrap with `"command": "cmd"` and `"args": ["/c", "E:/...python.exe", "E:/.../mcp_server.py"]`.

#### Trae (Web Research, untested)

```json
{
  "mcpServers": {
    "PaddleOCR": {
      "command": "E:/soft/anaconda3/envs/paddle_ocr/python.exe",
      "args": ["E:/soft/OCR/Paddle_ocr/mcp_server.py"]
    }
  }
}
```

> Trae requires **absolute paths** for `command`. Do not use bare `python`. Ensure the Python interpreter selected in Trae matches your conda environment.

Restart Trae IDE after configuration. A green indicator in the MCP panel confirms success.

#### Notes

- **Pick one registration method** (user-level recommended). Configuring both user and project level for the same MCP spawns duplicate processes.
- Replace all paths with your actual local paths.
- macOS / Linux users: replace `python.exe` with `python` or the conda environment's `bin/python`.

#### Verify

After restarting your IDE, ask the AI "what tools are available?" — you should see `mcp__paddleocr__recognize` and `mcp__paddleocr__ocr_status`.

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
Claude Code starts → reads ~/.claude.json → launches mcp_server.py (lightweight manager, ~85MB)
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
