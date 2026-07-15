/**
 * Hook: 检测用户贴图 → 读系统剪贴板 → 保存到 Temp → 输出 PENDING_IMAGE
 * 触发事件: UserPromptSubmit
 *
 * 用 MD5 去重：同一张图不重复输出 PENDING_IMAGE。
 */
const fs = require("fs");
const path = require("path");
const os = require("os");
const { execSync } = require("child_process");

const TEMP_DIR = os.tmpdir();
const PY_SCRIPT = path.join(__dirname, "read-clipboard.py");
const STATE_FILE = path.join(TEMP_DIR, "image-detect-state.json");
const DEBUG = true;

function debug(msg) {
  if (!DEBUG) return;
  try { fs.appendFileSync(path.join(TEMP_DIR, "image-detect-debug.log"), `[${new Date().toISOString()}] ${msg}\n`); } catch {}
}

// ── 1. 读 stdin ──────────────────────────────────────────────
let raw = "";
try { raw = fs.readFileSync(process.stdin.fd, "utf-8"); } catch { process.exit(0); }
if (!raw.trim()) { process.exit(0); }

// Dump stdin 到文件用于对比排查
try { fs.writeFileSync(path.join(TEMP_DIR, "image-detect-stdin.json"), raw.slice(0, 500000)); } catch {}

// ── 2. 读上次状态（hash → 路径）───────────────────────────────
let state = { lastHash: "", lastPath: "" };
try { if (fs.existsSync(STATE_FILE)) state = JSON.parse(fs.readFileSync(STATE_FILE, "utf-8")); } catch {}

// ── 3. 调 Python 读剪贴板 ─────────────────────────────────────
let output = "";
try {
  output = execSync(`python "${PY_SCRIPT}"`, {
    encoding: "utf-8",
    timeout: 5000,
    windowsHide: true,
  }).trim();
  debug(`python: "${output}"`);
} catch (e) {
  debug(`python exited: ${e.status}`);
  process.exit(0);
}

if (!output) { process.exit(0); }

const parts = output.split("|");
const imagePath = parts[0];
const imageHash = parts[1];

if (!imagePath || !imageHash || !fs.existsSync(imagePath)) {
  debug("invalid output");
  process.exit(0);
}

// ── 4. 去重：同一张图不重复输出 ───────────────────────────────
if (imageHash === state.lastHash) {
  debug(`same image as before, skipping (hash: ${imageHash})`);
  // 删除重复文件，保留旧路径（旧文件已被 AI 读过）
  try { fs.unlinkSync(imagePath); } catch {}
  process.exit(0);
}

// 新图片！更新状态
state.lastHash = imageHash;
state.lastPath = imagePath;
try { fs.writeFileSync(STATE_FILE, JSON.stringify(state)); } catch {}

debug(`new image: ${imagePath} (hash: ${imageHash})`);

// ── 5. 输出 PENDING_IMAGE ─────────────────────────────────────
process.stdout.write(
  `\n[系统] 用户在此消息中贴了图片。图片已保存，你必须立即使用 mcp__paddleocr__recognize 工具读取以下路径：\n` +
  `PENDING_IMAGE: ${imagePath}\n`
);

debug("=== hook done ===");
process.exit(0);
