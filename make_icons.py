# -*- coding: utf-8 -*-
"""从 图标.png 生成 icon.ico（Windows）与 icon.icns（macOS）。

- 源图 1145x1151 略扁，先补透明边成正方形，避免缩放变形
- ICO 打多档尺寸，任务栏 / 资源管理器 / 大图标视图都清晰
- ICNS 用 Pillow 生成，macOS 打包时由 spec 引用
"""
from PIL import Image

SRC = "图标.png"
ICO_OUT = "icon.ico"
ICNS_OUT = "for-mac-build/icon.icns"

# ── 1. 补成正方形（居中，透明填充）──
im = Image.open(SRC).convert("RGBA")
w, h = im.size
side = max(w, h)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(im, ((side - w) // 2, (side - h) // 2), im)
print("源图 %dx%d → 正方形 %dx%d" % (w, h, side, side))

# ── 2. Windows ICO（多尺寸）──
ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
square.save(ICO_OUT, format="ICO", sizes=ico_sizes)
print("已生成", ICO_OUT, "尺寸:", ico_sizes)

# ── 3. macOS ICNS ──
# Pillow 会按自身的尺寸表写入多个 PNG 条目
square.save(ICNS_OUT, format="ICNS")
print("已生成", ICNS_OUT)
