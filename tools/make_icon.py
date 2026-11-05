# -*- coding: utf-8 -*-
"""生成托盘图标 sidequest.ico。打包前跑一次即可。

用法：python tools/make_icon.py
输出：assets/sidequest.ico（16/24/32/48/64/128/256 七个尺寸）
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "sidequest.ico")

ACCENT = "#ffd166"
BG = "#14171f"
LINE = "#a8b7cc"


def draw(size=256):
    scale = size / 64.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1, radius, fill):
        d.rounded_rectangle((x0 * scale, y0 * scale, x1 * scale, y1 * scale),
                            radius=max(1, radius * scale), fill=fill)

    # 圆角底板：外圈留一点透明，缩小到 16px 时也不糊成一团
    box(4, 4, 60, 60, 13, BG)
    # 三条任务线，第一条用金色表示"当前这条"
    box(15, 20, 45, 24, 2, ACCENT)
    box(15, 30, 37, 34, 2, LINE)
    box(15, 40, 41, 44, 2, LINE)
    # 右下角一个完成点
    d.ellipse((44 * scale, 40 * scale, 54 * scale, 50 * scale), fill=ACCENT)
    return img


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = draw(256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print(OUT, os.path.getsize(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
