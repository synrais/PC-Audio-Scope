"""draws the application icon (a dark rounded square with two glowing traces) and writes icon.ico and icon.icns next to this script:  python packaging/make_icon.py"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
N = 1024


def trace(color, phase, amp, freq):
    pts = []
    for i in range(0, N - 2 * 150 + 1, 4):
        x = 150 + i
        t = i / float(N - 300)
        y = N / 2 + amp * math.sin(2 * math.pi * freq * t + phase) * (0.55 + 0.45 * math.sin(math.pi * t))
        pts.append((x, y))
    glow = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(pts, fill=color + (255,), width=70, joint='curve')
    glow = glow.filter(ImageFilter.GaussianBlur(34))
    core = Image.new('RGBA', (N, N), (0, 0, 0, 0))
    d = ImageDraw.Draw(core)
    d.line(pts, fill=color + (255,), width=26, joint='curve')
    light = tuple(min(255, c + 120) for c in color)
    d.line(pts, fill=light + (255,), width=9, joint='curve')
    return glow, core


tile = Image.new('RGBA', (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(tile)
d.rounded_rectangle((28, 28, N - 28, N - 28), radius=210, fill=(7, 11, 17, 255), outline=(52, 64, 78, 255), width=10)
for i in range(1, 8):                                   # graticule
    p = 28 + i * (N - 56) / 8
    d.line([(p, 90), (p, N - 90)], fill=(26, 34, 44, 255), width=4)
    d.line([(90, p), (N - 90, p)], fill=(26, 34, 44, 255), width=4)
d.line([(90, N / 2), (N - 90, N / 2)], fill=(40, 52, 66, 255), width=6)
layers = [trace((255, 138, 31), 0.0, 230, 1.5), trace((47, 181, 255), 1.9, 190, 2.5)]
for glow, _ in layers:
    tile = Image.alpha_composite(tile, glow)
for _, core in layers:
    tile = Image.alpha_composite(tile, core)
mask = Image.new('L', (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle((28, 28, N - 28, N - 28), radius=210, fill=255)
tile.putalpha(Image.composite(tile.getchannel('A'), Image.new('L', (N, N), 0), mask))
tile.save(os.path.join(HERE, 'icon.ico'), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
tile.save(os.path.join(HERE, 'icon.icns'))
