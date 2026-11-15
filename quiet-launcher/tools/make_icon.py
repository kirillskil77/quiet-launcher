"""Рисует assets/icon.ico (нужен Pillow; готовый файл лежит в репозитории, запускать не обязательно)."""
import os
from PIL import Image, ImageDraw

S = 1024
BG, PANEL, ACCENT = (23, 25, 28), (31, 34, 38), (90, 163, 119)


def draw():
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((32, 32, S - 32, S - 32), radius=220, fill=PANEL)
    d.rounded_rectangle((32, 32, S - 32, S - 32), radius=220, outline=(58, 64, 70), width=14)
    cx, cy, r, w = 500, 490, 270, 96
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=ACCENT, width=w)       # кольцо буквы Q
    x1, y1, x2, y2 = 650, 640, 790, 780
    d.line((x1, y1, x2, y2), fill=ACCENT, width=w)                              # хвостик
    for x, y in ((x1, y1), (x2, y2)):
        d.ellipse((x - w // 2, y - w // 2, x + w // 2, y + w // 2), fill=ACCENT)
    return im


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out, exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(out, "icon.png"))
    big.save(os.path.join(out, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
