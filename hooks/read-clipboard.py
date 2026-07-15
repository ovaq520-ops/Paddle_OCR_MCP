"""读取 Windows 剪贴板中的图片，保存到 Temp，输出 "路径|hash" 到 stdout。"""
import sys
import os
import uuid
import hashlib
import io

try:
    from PIL import ImageGrab
except ImportError:
    sys.exit(0)

img = ImageGrab.grabclipboard()
if img is None:
    sys.exit(0)

# 计算图片 hash（用于去重）
buf = io.BytesIO()
img.save(buf, "PNG")
data = buf.getvalue()
md5 = hashlib.md5(data).hexdigest()

out = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), f"{uuid.uuid4()}.png")
with open(out, "wb") as f:
    f.write(data)
print(f"{out}|{md5}")
