"""renders the README screenshots from a synthetic stereo piece:  python tests/screenshots.py
The window is fully transparent while it is captured with PrintWindow, so nothing appears on the desktop."""
import ctypes
import os
import tkinter as tk
from ctypes import wintypes

import numpy as np
from PIL import Image

import support as T
from support import m, pump

OUT = os.path.join(T.ROOT, 'docs')
user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD),
                ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
                ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


def grab(root):
    """the client area of the window as a PIL image"""
    root.update()
    hwnd = user32.GetParent(root.winfo_id())
    w, h = root.winfo_width(), root.winfo_height()
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 3)                         # PW_CLIENTONLY | PW_RENDERFULLCONTENT
    buf = ctypes.create_string_buffer(w * h * 4)
    info = BITMAPINFOHEADER(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.SelectObject(mdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')


def fit(root):
    """size the window to its content at scale 1"""
    root.update_idletasks()
    root.geometry('%dx%d+0+0' % (m.App.BASE_W, root.winfo_reqheight()))
    pump(root, 0.8)


SR = m.SR
from support import band, demo_audio  # noqa: E402


def demo_clips():
    """two takes of the piece for the comparison picture: the second one starts 1.9 s later, is 6 dB quieter and has a damaged stretch"""
    a = demo_audio(1)
    b = np.concatenate([np.zeros((int(1.9 * SR), 2)), a * 0.5])
    r = np.random.default_rng(5)
    s0, s1 = int(11.0 * SR), int(13.2 * SR)
    b[s0:s1] = np.stack([band(r.standard_normal(s1 - s0), 150, 5000), band(r.standard_normal(s1 - s0), 150, 5000)], axis=1) * 0.12
    clip_a = m.Clip(a * 10 ** (-19 / 20), -19.0, name='stock.wav', markers=[{'t': 6.0, 'name': 'M1'}, {'t': 12.0, 'name': 'M2'}])
    clip_b = m.Clip(b * 10 ** (-25 / 20), -25.0, name='v7.wav')
    return clip_a, clip_b


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass
OUT = os.environ.get('SHOTS_OUT') or OUT
T.sandbox()
os.makedirs(OUT, exist_ok=True)
faulty, _ = T.faulty_demo()  # the findings picture needs no window
m.findings_image(faulty, None, m.find_problems(faulty), 'a demo piece with a fault in one channel at a time', left='#ff8a1f', right='#2fb5ff').save(os.path.join(OUT, 'analysis.png'))
print('analysis.png')
cap = T.SynthCapture()
cap.start()
root = tk.Tk()
root.attributes('-alpha', 0.0)
app = m.App(root, cap)
names = [t.name for t in m.THEMES]


def use(theme):
    app.theme_i = names.index(theme)
    app.use_theme()
    app.build_ui()
    fit(root)


app.k = 1.0
app.build_ui()
fit(root)
app.k = 1.0
clip_a, clip_b = demo_clips()
HERO = float(os.environ.get('SHOTS_T', '15.4'))

use('Orange + blue')
app.open_loaded(clip_a)
app.set_sel(HERO - 1.5, HERO + 2.5)
app.seek_t(HERO)
fit(root)
pump(root, 1.2)
grab(root).save(os.path.join(OUT, 'review.png'))
print('review.png')

use('Classic')
app.set_spec_mode('spectrogram')
app.seek_t(21.5)
pump(root, 1.2)
grab(root).save(os.path.join(OUT, 'spectrogram.png'))
print('spectrogram.png')

use('Orange + blue')
app.set_spec_mode('spectrum')
app.compare_start(clip_a, clip_b, auto=True)
fit(root)
app.sel = (9.0, 15.0)
app.tl_key = None
for _ in range(100):
    pump(root, 0.1)
    if app.cmp['stats'] is not None:
        break
app.seek_t(HERO)
pump(root, 1.0)
grab(root).save(os.path.join(OUT, 'compare.png'))
print('compare.png')

app.cmp_close()
app.set_sel(HERO - 1.5, HERO + 2.5)
shots = []
for theme in ('Green phosphor', 'Amber phosphor', 'Blue phosphor', 'Red + cyan'):
    use(theme)
    app.seek_t(HERO)
    pump(root, 1.5)
    shots.append(grab(root))
w, h = shots[0].size
sheet = Image.new('RGB', (w, h))
for i, im in enumerate(shots):
    sheet.paste(im.resize((w // 2, h // 2), Image.Resampling.LANCZOS), ((i % 2) * (w // 2), (i // 2) * (h // 2)))
sheet.save(os.path.join(OUT, 'themes.png'))
print('themes.png')
cap.stop = True
root.destroy()
