# PaddleOCR MCP Server

[![中文](https://img.shields.io/badge/lang-中文-red)](README.md)
[![English](https://img.shields.io/badge/lang-English-blue)](README_EN.md)

An MCP Server that enables text-only models (DeepSeek V4, etc.) to "see" images via OCR.

## How It Works

PaddleOCR MCP Server provides OCR capabilities to AI assistants. When the AI calls the `recognize` tool, the MCP server automatically extracts images from the current session transcript and returns all recognized text.

## Installation

### 1. Create Environment & Install Dependencies

You can use either **conda** or **venv**. On Windows, the GPU wheel must be installed from Paddle's CUDA-specific repository, not the default PyPI index.

#### Option 1: conda (recommended for GPU dependency management)

```bash
conda create -n paddle_ocr python=3.10
conda activate paddle_ocr

# Windows GPU (choose one matching your CUDA version)
python -m pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/   # CUDA 11.8
python -m pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/   # CUDA 12.6
python -m pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu129/   # CUDA 12.9

# Windows CPU / macOS / Linux
pip install paddlepaddle paddleocr fastmcp
```

#### Option 2: venv / virtualenv

```bash
# Create and activate virtual environment
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies (for Windows GPU use the official CUDA source above)
pip install paddlepaddle-gpu paddleocr fastmcp

# Windows CPU / macOS / Linux
# pip install paddlepaddle paddleocr fastmcp
```

> **CPU users**: replace `paddlepaddle-gpu` with `paddlepaddle`.
>
> **Windows says no matching distribution for `paddlepaddle-gpu`?** Make sure Python is 64-bit 3.9-3.13 and install from the CUDA-specific official source shown above.

On first use, PaddleOCR automatically downloads model weights (~140MB) from ModelScope and caches them in the `models/` directory. No manual download required.

### 2. Register the MCP Server

PaddleOCR works with the following AI coding tools:

| Platform | Config File (User) | Config File (Project) | Format | Status |
|----------|-------------------|----------------------|:--:|:--:|
| **Claude Code** | `~/.claude.json` `mcpServers` field | `<project>/.mcp.json` | JSON | Verified |
| **Codex** | `~/.codex/config.toml` | `<project>/.codex/config.toml` | TOML | Untested |
| **Cursor** | `~/.cursor/mcp.json` | `<project>/.cursor/mcp.json` | JSON | Untested |
| **Trae** | `~/.trae/mcp.json` | `<project>/.trae/mcp.json` | JSON | Untested |

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

If using venv, set `command` to `.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (macOS / Linux).

#### Codex (Untested)

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

#### Cursor (Untested)

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

#### Trae (Untested)

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

> Trae requires **absolute paths** for `command`. Do not use bare `python`. Ensure the Python interpreter selected in Trae matches your conda/venv environment.

Restart Trae IDE after configuration. A green indicator in the MCP panel confirms success.

#### Notes

- **Pick one registration method** (user-level recommended). Configuring both user and project level for the same MCP spawns duplicate processes.
- Replace all paths with your actual local paths.
- macOS / Linux users: replace `python.exe` with `python` or the conda/venv environment's `bin/python`.

#### Verify

After restarting your IDE, ask the AI "what tools are available?" — you should see `mcp__paddleocr__recognize`, `mcp__paddleocr__recognize_batch`, `mcp__paddleocr__list_languages`, `mcp__paddleocr__set_language`, and `mcp__paddleocr__ocr_status`.

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

### Method 4: Batch Recognition

To recognize multiple local images at once, ask the AI:

```
Please recognize these images: C:\a.png, C:\b.png, C:\c.png
```

The AI will call `recognize_batch(image_paths=["C:/a.png", "C:/b.png", "C:/c.png"])`.

The worker processes images one by one. The model is loaded only once at startup, so subsequent requests do not need to re-warm the GPU.

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

- **Parameters**:
  - `image_path` — Full path to the image file (optional; if omitted, extracts images from the current session transcript)
  - `output_format` — Output format: `text` (default) / `json` / `markdown`
- **Returns**:
  ```json
  {
    "success": true,
    "source": "transcript",
    "images_found": 2,
    "results": [
      {
        "index": 0,
        "image": "screenshot.png",
        "text_count": 3,
        "texts": [{"text": "Line 1", "confidence": 0.99}],
        "full_text": "Line 1\nLine 2"
      }
    ]
  }
  ```

#### output_format

- `text`: returns `texts` and `full_text` (default).
- `json`: each item in `texts` additionally includes `box` (four-point coordinates) and `confidence`.
- `markdown`: additionally returns a `markdown` field for easy document insertion.

Example:

```
Recognize this image and return JSON: C:\screenshot.png
```

The AI will call `recognize(image_path="C:/screenshot.png", output_format="json")`.

### recognize_batch

Recognize text from multiple local images at once.

- **Parameters**:
  - `image_paths` — List of image paths (required)
  - `output_format` — Output format: `text` (default) / `json` / `markdown`
- **Returns**: Same unified structure as `recognize`, with `source` set to `"batch"`

### list_languages

List supported OCR language codes.

- **Returns**: List of languages with `code` and `name`

### set_language

Switch the OCR language model. Subsequent recognition requests use the new language.

- **Parameter**: `lang` — Language code, e.g. `en`, `japan`, `korean`
- **Returns**: `{"success": true, "language": "en", "status": "ready"}`

> Switching languages reloads the model, which takes a few seconds. Call it at the start of a session or only when needed.

### ocr_status

Check OCR engine status.

- **Returns**: `{"success": true, "loaded": true, "status": "ready"}`

## Screenshots vs. Photos: Switching Recognition Modes

The default mode is optimized for screenshots, UI, and code. You can switch modes via environment variables without editing code.

**Default mode** (lightweight, loads only detection + recognition models):

```bash
# No extra settings needed; these are the defaults
PADDLEOCR_USE_TEXTLINE_ORIENTATION=false
PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY=false
PADDLEOCR_USE_DOC_UNWARPING=false
```

This mode uses ~900MB RAM and ~0.3s inference. Suitable for most use cases.

**High-accuracy mode** (photos, scanned documents, rotated/curved text):

```bash
PADDLEOCR_USE_TEXTLINE_ORIENTATION=true
PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY=true
PADDLEOCR_USE_DOC_UNWARPING=true
```

| Parameter | Purpose | Use Case |
|-----------|---------|----------|
| `use_textline_orientation` | Detect 180° text rotation | Phone held upside-down, rotated screenshots |
| `use_doc_orientation_classify` | Detect page orientation (4 directions) | Landscape photos of portrait docs, rotated PDFs |
| `use_doc_unwarping` | Flatten curved paper surfaces | Book pages, bent paper photos |

Trade-off: 4 models loaded, ~1.7GB RAM, slightly slower inference, significantly higher accuracy.

**Multi-language**: switch via `PADDLEOCR_LANG`, e.g. `en`, `japan`, `korean`, `chinese_cht`. Default is `ch`.

**CPU mode**: set `PADDLEOCR_CUDA_VISIBLE_DEVICES=""` to force CPU inference (PaddleOCR auto-uses GPU when available; empty value disables CUDA).

## Architecture

```
Claude Code starts → reads ~/.claude.json → launches mcp_server.py (lightweight manager, ~85MB)
  → AI calls recognize() → manager spawns python ocr_worker.py (worker with model, ~900MB)
    → OCR completes → worker stays alive (default 300s, configurable via PADDLEOCR_IDLE_TIMEOUT)
    → idle timeout → exits, releasing GPU
```

| Process | RAM | Lifetime |
|---------|-----|----------|
| mcp_server.py | ~85 MB | Duration of Claude Code session |
| ocr_worker.py | ~900 MB | Reused during idle timeout after last OCR, then exits |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PADDLEOCR_CACHE` | `<script_dir>/models` | Model cache directory |
| `PADDLEOCR_SITE_PACKAGES` | (empty) | Path to conda/venv `Lib/site-packages`, used to add CUDA DLL directories |
| `PADDLEOCR_PYTHON` | (auto-detected) | Absolute path to Python interpreter used to spawn the worker subprocess |
| `PADDLEOCR_IDLE_TIMEOUT` | `300` | Worker idle auto-exit time in seconds |
| `PADDLEOCR_LOG_LEVEL` | `INFO` | Log level: `DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `PADDLEOCR_LANG` | `ch` | OCR language: `ch`/`en`/`japan`/`korean`/`chinese_cht`, etc. |
| `PADDLEOCR_CUDA_VISIBLE_DEVICES` | (empty) | GPU to use, e.g. `0` or `0,1`; set to empty string to force CPU |
| `PADDLEOCR_USE_TEXTLINE_ORIENTATION` | `false` | Textline orientation detection |
| `PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY` | `false` | Document orientation classification |
| `PADDLEOCR_USE_DOC_UNWARPING` | `false` | Document unwarping correction |
| `CLAUDE_PROJECTS_ROOT` | `~/.claude/projects` | Transcript file search root directory |
| `CLAUDE_CODE_SESSION_ID` | Injected by Claude Code | Current session ID, used for precise transcript lookup without cross-window interference |

### Passing environment variables in MCP config

#### Claude Code

```json
{
  "mcpServers": {
    "PaddleOCR": {
      "command": "E:/soft/anaconda3/envs/paddle_ocr/python.exe",
      "args": ["E:/soft/OCR/Paddle_ocr/mcp_server.py"],
      "env": {
        "PADDLEOCR_LANG": "ch",
        "PADDLEOCR_USE_DOC_UNWARPING": "true"
      }
    }
  }
}
```

## License

This project is licensed under the [MIT License](LICENSE).
