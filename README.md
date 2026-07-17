# PaddleOCR MCP Server

[![中文](https://img.shields.io/badge/语言-中文-red)](README.md)
[![English](https://img.shields.io/badge/lang-English-blue)](README_EN.md)

让不支持图片的纯文本模型（DeepSeek V4 等）也能"看图"的 MCP Server。

## 原理

PaddleOCR MCP Server 为 AI 提供 OCR 文字识别能力。AI 调用 `recognize` 工具，MCP 自动从当前会话 transcript 中提取图片，返回图中所有文字内容。

## 安装

### 1. 创建环境并安装依赖

支持 **conda** 或 **venv** 任选其一。Windows GPU 版需从 Paddle 官方 CUDA 专用源安装，不能直接从默认 PyPI 装。

#### 方式一：conda（推荐，便于 GPU 依赖管理）

```bash
conda create -n paddle_ocr python=3.10
conda activate paddle_ocr

# Windows GPU（根据你的 CUDA 版本选一条）
python -m pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/   # CUDA 11.8
python -m pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/   # CUDA 12.6
python -m pip install paddlepaddle-gpu==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu129/   # CUDA 12.9

# Windows CPU / macOS / Linux
pip install paddlepaddle paddleocr fastmcp

# 国内用户可加百度镜像加速 paddleocr/fastmcp
pip install paddleocr fastmcp -i https://mirror.baidu.com/pypi/simple
```

#### 方式二：venv / virtualenv

```bash
# 创建并激活虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 安装依赖（Windows GPU 按 CUDA 版本选择上面 conda 中的官方源命令）
pip install paddlepaddle-gpu paddleocr fastmcp

# Windows CPU / macOS / Linux
# pip install paddlepaddle paddleocr fastmcp
```

> **CPU 用户**：将 `paddlepaddle-gpu` 替换为 `paddlepaddle`。
>
> **Windows 找不到 `paddlepaddle-gpu` 版本？** 确认 Python 是 3.9-3.13 的 64 位版本，并使用上面带有 CUDA 版本号的官方源安装。
首次使用时 PaddleOCR 会自动从 ModelScope 下载模型权重（~140MB），缓存在项目 `models/` 目录下，之后不再需要下载。

### 2. 注册 MCP Server

PaddleOCR 支持以下四个 AI 编程工具：

| 平台 | 配置文件（用户级） | 配置文件（项目级） | 配置格式 | 状态 |
|------|-------------------|-------------------|:--:|:--:|
| **Claude Code** | `~/.claude.json` 内 `mcpServers` 字段 | `<项目>/.mcp.json` | JSON | 已实测 |
| **Codex** | `~/.codex/config.toml` | `<项目>/.codex/config.toml` | TOML | 未实测 |
| **Cursor** | `~/.cursor/mcp.json` | `<项目>/.cursor/mcp.json` | JSON | 未实测 |
| **Trae** | `~/.trae/mcp.json` | `<项目>/.trae/mcp.json` | JSON | 未实测 |

> 推荐**用户级注册**——一次配置，所有项目都能用。

#### Claude Code（已实测）

编辑 `~/.claude.json`，在 `mcpServers` 字段中添加：

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

> **注意**：如果 `~/.claude.json` 中已有 `mcpServers` 字段，将 `PaddleOCR` 合并进去，不要创建新的顶级 `mcpServers`。

如果使用 venv，将 `command` 改为 `.venv\Scripts\python.exe`（Windows）或 `.venv/bin/python`（macOS / Linux）。

#### Codex（未实测）

```toml
[mcp_servers.PaddleOCR]
command = "E:/soft/anaconda3/envs/paddle_ocr/python.exe"
args = ["E:/soft/OCR/Paddle_ocr/mcp_server.py"]
startup_timeout_sec = 30
tool_timeout_sec = 120
```

或使用 CLI 一键添加：

```bash
codex mcp add PaddleOCR -- "E:/soft/anaconda3/envs/paddle_ocr/python.exe" "E:/soft/OCR/Paddle_ocr/mcp_server.py"
```

配置后重启 Codex 终端，`codex mcp list` 验证生效。

#### Cursor（未实测）

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

配置后 Cursor Settings → MCP 面板应显示绿色指示灯。`Cmd+Shift+P` → `MCP: Reload Servers` 刷新。

> Windows 上如遇问题，可将 `command` 改为 `"cmd"`，`args` 改为 `["/c", "E:/...python.exe", "E:/.../mcp_server.py"]`。

#### Trae（未实测）

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

> Trae 的 `command` **必须使用绝对路径**，不能只写 `python`。确保 Trae 中选择的 Python 解释器与 conda/venv 环境一致。

配置后重启 Trae IDE，MCP 面板显示绿色指示灯即成功。

#### 注意事项

- **选择一种注册方式即可**（推荐用户级）。如果用户级和项目级同时配置了同一个 MCP，会被加载两次——导致重复进程。
- 所有平台的 `command` 和 `args` 路径需替换为你本机实际路径。
- macOS / Linux 用户将 `python.exe` 路径改为 `python` 或 conda/venv 环境的 `bin/python`。

#### 验证

重启 IDE 后，在对话中询问 AI 有哪些工具可用，应该能看到 `mcp__paddleocr__recognize`、`mcp__paddleocr__recognize_batch`、`mcp__paddleocr__list_languages`、`mcp__paddleocr__set_language` 和 `mcp__paddleocr__ocr_status`。

## 使用场景

### 方式一：拖动图片到 Claude Code

将图片文件直接拖入 Claude Code 输入框，对话框中会出现 `[Unsupported Image]` 标记。发送后 AI 会自动调用 OCR 识别图片中的文字。

### 方式二：复制图片粘贴到 Claude Code

在任意位置复制图片（截图工具 `Ctrl+C`、右键复制图片等），在 Claude Code 输入框 `Ctrl+V` 粘贴。同样会出现 `[Unsupported Image]` 标记，AI 自动识别。

### 方式三：显式指定图片文件路径

直接在对话中告诉 AI 图片的完整路径，AI 会调用 `recognize(image_path="C:/path/to/image.png")` 进行识别。适用于脚本批处理或路径已知的场景。

```
帮我看下这张图：C:\Users\Administrator\Desktop\screenshot.png
```

### 方式四：批量识别

如果需要一次识别多张本地图片，可以让 AI 调用：

```
请识别以下图片：C:\a.png, C:\b.png, C:\c.png
```

AI 会调用 `recognize_batch(image_paths=["C:/a.png", "C:/b.png", "C:/c.png"])`。

worker 逐张处理图片列表。模型只在启动时加载一次，后续请求无需重新预热 GPU。

## 提高工具调用准确率

Claude Code 接入的外部模型（如 DeepSeek）有时会忽略 MCP 工具自身的 `instructions` 说明，导致 AI 看到 `[Unsupported Image]` 后不会主动调用 OCR。

**解决办法**：在 `CLAUDE.md` 中显式写入工具使用说明。因为 `CLAUDE.md` 是系统提示词级别注入，优先级高于 MCP 工具自身的说明，外部模型更容易遵从。

在 `CLAUDE.md` 末尾添加：

```markdown
## 图片处理（模型不可见图片时使用）
当用户消息中出现 [Unsupported Image] 标记时，调 `mcp__paddleocr__recognize` 不传参数。
MCP 会自动从当前会话 transcript 中提取图片并 OCR。
然后将识别结果作为"从图片中读到了以下内容"汇报给用户。
```

> **为什么这样做有效**：MCP 工具自身的 `instructions` 以 tool definition 形式传递，部分模型在 tool calling 决策时对其关注度较低。而 `CLAUDE.md` 是系统级指令，模型对其遵从度更高。

## 硬件要求

|          | 最低                 | 推荐                    |
|----------|---------------------|------------------------|
| GPU      | NVIDIA GTX 1050 4GB | NVIDIA RTX 3060+ 8GB   |
| VRAM     | 4 GB                | 8 GB+                  |
| RAM      | 4 GB                | 8 GB+                  |
| CUDA     | 11.2+               | 12.x                   |
| cuDNN    | 8.x                 | 9.x                    |
| 磁盘     | ~200MB（模型）       | SSD                    |

无 GPU 时自动退到 CPU 模式，速度慢 5-10 倍但仍可用。

## 工具

### recognize

识别图片中的所有文字。

- **参数**:
  - `image_path` — 图片文件的完整路径（可选，不传则自动从 transcript 提取）
  - `output_format` — 输出格式：`text`（默认）/`json`/`markdown`
- **返回**:
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
        "texts": [{"text": "第一行", "confidence": 0.99}],
        "full_text": "第一行\n第二行"
      }
    ]
  }
  ```

#### output_format 说明

- `text`：返回 `texts` 和 `full_text`（默认）。
- `json`：在 `texts` 中额外包含每个文本行的 `box`（四点坐标）和 `confidence`。
- `markdown`：额外返回 `markdown` 字段，方便直接插入文档。

示例：

```
识别这张图片并以 JSON 格式返回：C:\screenshot.png
```

AI 会调用 `recognize(image_path="C:/screenshot.png", output_format="json")`。

### recognize_batch

批量识别多张本地图片。

- **参数**:
  - `image_paths` — 图片路径列表（必填）
  - `output_format` — 输出格式：`text`（默认）/`json`/`markdown`
- **返回**: 与 `recognize` 相同的统一结构，`source` 为 `"batch"`

### list_languages

列出 PaddleOCR 支持的语言代码。

- **返回**: 语言列表，包含 `code` 和 `name`

### set_language

切换 OCR 语言模型。切换后后续所有识别请求均使用新语言。

- **参数**: `lang` — 语言代码，如 `en`、`japan`、`korean`
- **返回**: `{"success": true, "language": "en", "status": "ready"}`

> 切换语言会重新加载模型，耗时数秒，建议在会话开始时或确有需要时调用。

### ocr_status

检查 OCR 引擎状态。

- **返回**: `{"success": true, "loaded": true, "status": "ready"}`

## 截图 vs 照片：切换识别模式

默认模式针对截图、UI 界面、代码优化。可通过环境变量切换，无需修改代码。

**默认模式**（轻量，只加载检测+识别模型）：

```bash
# 无需额外设置，默认值即可
PADDLEOCR_USE_TEXTLINE_ORIENTATION=false
PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY=false
PADDLEOCR_USE_DOC_UNWARPING=false
```

此模式下内存 ~900MB，推理约 0.3 秒。适合绝大多数场景。

**高精度模式**（照片、扫描件、旋转/弯曲文字）：

```bash
PADDLEOCR_USE_TEXTLINE_ORIENTATION=true
PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY=true
PADDLEOCR_USE_DOC_UNWARPING=true
```

| 参数 | 作用 | 适用场景 |
|------|------|----------|
| `use_textline_orientation` | 检测文字行是否倒置（180°） | 拍照时手机拿反、旋转截图 |
| `use_doc_orientation_classify` | 检测整页方向（0°/90°/180°/270°） | 横拍竖排文档、旋转过的 PDF |
| `use_doc_unwarping` | 将弯曲的纸面拉平 | 拍摄书页、弯曲纸张 |

代价是加载 4 个模型，内存升至 ~1.7GB，推理稍慢但准确率大幅提升。

**多语言**：通过 `PADDLEOCR_LANG` 切换，例如 `en`、`japan`、`korean`、`chinese_cht`，默认为 `ch`。

**CPU 模式**：设置 `PADDLEOCR_CUDA_VISIBLE_DEVICES=""` 强制使用 CPU（PaddleOCR 有 GPU 时自动使用，设为空值则不启用 CUDA）。

## 架构

```
Claude Code 启动 → 读 ~/.claude.json → 启动 mcp_server.py（轻量主进程，~85MB）
  → AI 调 recognize() → 主进程 spawn python ocr_worker.py（子进程，~900MB）
    → OCR 完成 → 子进程常驻（默认 300 秒，可通过 PADDLEOCR_IDLE_TIMEOUT 调整）
    → 无新请求自动退出，释放 GPU
```

| 进程 | 内存 | 生命周期 |
|------|------|----------|
| mcp_server.py | ~85 MB | Claude Code 会话期间 |
| ocr_worker.py | ~900 MB | OCR 后空闲超时内复用，超时退出 |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PADDLEOCR_CACHE` | `<脚本目录>/models` | 模型缓存目录 |
| `PADDLEOCR_SITE_PACKAGES` | （空） | conda/venv 的 `Lib/site-packages` 路径，用于添加 CUDA DLL 目录 |
| `PADDLEOCR_PYTHON` | （自动探测） | 启动 worker 子进程使用的 Python 解释器绝对路径 |
| `PADDLEOCR_IDLE_TIMEOUT` | `300` | worker 空闲自动退出时间（秒） |
| `PADDLEOCR_LOG_LEVEL` | `INFO` | 日志级别：`DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `PADDLEOCR_LANG` | `ch` | OCR 语言：`ch`/`en`/`japan`/`korean`/`chinese_cht` 等 |
| `PADDLEOCR_CUDA_VISIBLE_DEVICES` | （空） | 指定使用的 GPU，例如 `0` 或 `0,1`；设为空字符串强制 CPU |
| `PADDLEOCR_USE_TEXTLINE_ORIENTATION` | `false` | 文字行方向检测 |
| `PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY` | `false` | 文档方向分类 |
| `PADDLEOCR_USE_DOC_UNWARPING` | `false` | 文档拉平矫正 |
| `CLAUDE_PROJECTS_ROOT` | `~/.claude/projects` | transcript 文件搜索根目录 |
| `CLAUDE_CODE_SESSION_ID` | Claude Code 自动注入 | 当前会话 ID，用于精确定位 transcript，避免多窗口串图 |

### 在 MCP 配置中传入环境变量示例

#### Claude Code

```json
{
  "mcpServers": {
    "PaddleOCR": {
      "command": "E:/soft/anaconda3/envs/paddle_ocr/python.exe",
      "args": ["E:/soft/OCR/Paddle_ocr/mcp_server.py"],
      "env": {
        "PADDLEOCR_LANG": "ch",
        "PADDLEOCR_USE_TEXTLINE_ORIENTATION": "true",
        "PADDLEOCR_USE_DOC_ORIENTATION_CLASSIFY": "true",
        "PADDLEOCR_USE_DOC_UNWARPING": "true"
      }
    }
  }
}
```

## License

本项目采用 [MIT](LICENSE) 开源协议。
