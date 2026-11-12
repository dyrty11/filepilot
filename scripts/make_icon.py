"""Рисует временную иконку assets/icon.png и assets/icon.ico. Чтобы использовать свою, просто замените эти файлы."""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
for y in range(SIZE):  # вертикальный градиент круга
    t = y / SIZE
    c = (int(40 + 20 * t), int(110 + 30 * (1 - t)), int(230 - 40 * t), 255)
    d.line([(0, y), (SIZE, y)], fill=c)
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).ellipse([16, 16, SIZE - 16, SIZE - 16], fill=255)
base = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
base.paste(img, (0, 0), mask)
d = ImageDraw.Draw(base)
d.polygon([(256, 96), (368, 392), (256, 330), (144, 392)], fill=(255, 255, 255, 255))  # стрелка-«пилот»
d.polygon([(256, 96), (256, 330), (144, 392)], fill=(215, 230, 255, 255))
out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
base.save(out / "icon.png")
base.save(out / "icon.ico", sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)])
