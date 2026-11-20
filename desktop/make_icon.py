# -*- coding: utf-8 -*-
"""生成桌面版图标（icon.ico）：绿底白字 Q。"""
import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")


def draw(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.22)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=(20, 120, 90, 255))
    d.rounded_rectangle([int(size * .06), int(size * .06), int(size * .94), int(size * .94)],
                        radius=int(r * .8), outline=(255, 255, 255, 90), width=max(1, size // 64))
    txt = "Q"
    fsize = int(size * 0.62)
    font = None
    for name in ("msyhbd.ttc", "msyh.ttc", "arialbd.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(name, fsize)
            break
        except Exception:  # noqa: BLE001
            continue
    if font is None:
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), txt, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), txt, font=font, fill=(255, 255, 255, 255))
    return img


if __name__ == "__main__":
    base = draw(256)
    base.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("已生成", OUT, os.path.getsize(OUT), "字节")
