"""Рисует картинки для окна установщика из assets/icon.png (запуск: python scripts/make_installer_art.py).

Нужен Pillow. Результат: assets/wizard-*.bmp (большая левая картинка) и assets/wizard-small-*.bmp (маленькая справа сверху)
в трёх масштабах, чтобы Inno Setup выбирал подходящий под DPI экрана.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TOP, BOTTOM = (8, 28, 92), (12, 54, 150)  # цвета из фона иконки


def font(size: int, bold: bool = True):
    for name in ("segoeuib.ttf", "DejaVuSans-Bold.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        row = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = row
    return img


def big(scale: float) -> Image.Image:
    w, h = round(164 * scale), round(314 * scale)
    img = gradient(w, h)
    icon = Image.open(ASSETS / "icon.png").convert("RGBA")
    size = round(110 * scale)
    icon = icon.resize((size, size), Image.LANCZOS)
    img.paste(icon, ((w - size) // 2, round(70 * scale)), icon)
    d = ImageDraw.Draw(img)
    f = font(round(26 * scale))
    tw = d.textlength("FilePilot", font=f)
    d.text(((w - tw) / 2, round(196 * scale)), "FilePilot", font=f, fill="white")
    f2 = font(round(11 * scale), bold=False)
    for i, line in enumerate(("search · duplicates", "disk map · rules")):
        tw = d.textlength(line, font=f2)
        d.text(((w - tw) / 2, round((232 + i * 16) * scale)), line, font=f2, fill=(170, 200, 245))
    d.rectangle([0, h - round(4 * scale), w, h], fill=(32, 178, 232))
    return img


def small(scale: float) -> Image.Image:
    s = round(55 * scale)
    img = Image.new("RGB", (s, s), (255, 255, 255))
    icon = Image.open(ASSETS / "icon.png").convert("RGBA").resize((round(47 * scale),) * 2, Image.LANCZOS)
    img.paste(icon, ((s - icon.width) // 2, (s - icon.height) // 2), icon)
    return img


if __name__ == "__main__":
    for tag, k in (("100", 1.0), ("150", 1.5), ("200", 2.0)):
        big(k).save(ASSETS / f"wizard-{tag}.bmp")
        small(k).save(ASSETS / f"wizard-small-{tag}.bmp")
    print("готово:", ", ".join(sorted(p.name for p in ASSETS.glob("wizard*.bmp"))))
