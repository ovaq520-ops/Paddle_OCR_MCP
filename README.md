# PaddleOCR MCP Server

让不支持图片的纯文本模型（DeepSeek V4 等）也能"看图"的 MCP Server。

## 原理

PaddleOCR MCP Server 为 AI 提供 OCR 文字识别能力。AI 调用 `recognize` 工具，MCP 自动从当前会话 transcript 中提取图片，返回图中所有文字内容。

## 安装

```bash
# 1. 创建 conda 环境
conda create -n paddle_ocr python=3.10
conda activate paddle_ocr

# 2. 安装依赖（国内用户推荐用镜像加速）
pip install paddlepaddle-gpu paddleocr fastmcp -i https://mirror.baidu.com/pypi/simple

# 3. 配置 Claude Code
# 在用户级 mcp.json（~/.claude/mcp.json）中添加：
{
  "mcpServers": {
    "PaddleOCR": {
      "command": "YOUR_CONDA_PATH/python.exe",
      "args": ["YOUR_PATH/mcp_server.py"]
    }
  }
}
```

首次使用时 PaddleOCR 会自动从 ModelScope 下载模型权重（~140MB），缓存在项目 `models/` 目录下，之后不再需要下载。

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

- **参数**: `image_path` — 图片文件的完整路径（可选，不传则自动从 transcript 提取）
- **返回**: 每行文字的内容和置信度

### ocr_status

检查 OCR 引擎状态。

## 截图 vs 照片：切换识别模式

**默认模式**（优化截图、UI 界面、代码）：

```python
# ocr_worker.py 当前配置
_ocr = PaddleOCR(
    lang="ch",
    use_textline_orientation=False,        # 关闭文字方向检测
    use_doc_orientation_classify=False,    # 关闭文档方向检测
    use_doc_unwarping=False,               # 关闭文档拉平矫正
)
```

此模式下仅加载检测+识别两个模型，内存 ~900MB，推理约 0.3 秒。适合绝大多数场景。

**高精度模式**（照片、扫描件、旋转/弯曲文字）：

```python
_ocr = PaddleOCR(
    lang="ch",
    use_textline_orientation=True,         # 开启文字方向检测
    use_doc_orientation_classify=True,     # 开启文档方向矫正
    use_doc_unwarping=True,                # 开启文档拉平（弯曲书页）
)
```

| 参数 | 作用 | 适用场景 |
|------|------|----------|
| `use_textline_orientation` | 检测文字行是否倒置（180°） | 拍照时手机拿反、旋转截图 |
| `use_doc_orientation_classify` | 检测整页方向（0°/90°/180°/270°） | 横拍竖排文档、旋转过的 PDF |
| `use_doc_unwarping` | 将弯曲的纸面拉平 | 拍摄书页、弯曲纸张 |

**切换方式**：编辑 `ocr_worker.py` 第 48-52 行，将对应的参数改为 `True`，重启 Claude Code 即可。代价是加载 4 个模型，内存升至 ~1.7GB，推理稍慢但准确率大幅提升。

## 架构

```
Claude Code 启动 → 读 mcp.json → 启动 mcp_server.py（轻量主进程，~85MB）
  → AI 调 recognize() → 主进程 spawn python ocr_worker.py（子进程，~900MB）
    → OCR 完成 → 子进程常驻 5 分钟 → 无新请求自动退出，释放 GPU
```

| 进程 | 内存 | 生命周期 |
|------|------|----------|
| mcp_server.py | ~85 MB | Claude Code 会话期间 |
| ocr_worker.py | ~900 MB | OCR 后 5 分钟内复用，超时退出 |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PADDLEOCR_CACHE` | `<脚本目录>/models` | 模型缓存目录 |
| `PADDLEOCR_SITE_PACKAGES` | (空，不设 DLL 目录) | conda env 的 `Lib/site-packages` 路径 |
| `CLAUDE_PROJECTS_ROOT` | `~/.claude/projects` | transcript 文件搜索根目录 |

## License

MIT
