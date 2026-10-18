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


def band(x, lo, hi):
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    spec[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(spec, len(x))


def demo_audio(seed=1, sec=24.0):
    """a short stereo piece that gives every panel something to show: pads detuned between the channels (a rotating figure on the vectorscope) that pump with the kick,
    plucks and hats panned about, kick and bass in the centre, a drop at 12 s, and a riser of independent noise in each channel (a round cloud on the vectorscope)"""
    r = np.random.default_rng(seed)
    n = int(sec * SR)
    t = np.arange(n) / SR

    def gate(a, b):
        return np.clip(np.minimum((t - a) / 0.08, (b - t) / 0.08), 0.0, 1.0)

    full = np.maximum(gate(6.0, 12.0), gate(13.2, sec))
    drums = full
    plucks = np.maximum(gate(3.0, 12.0), gate(13.2, sec))
    hats = np.maximum(gate(9.0, 12.0), gate(13.2, sec))
    beat = 0.6
    left, right = np.zeros(n), np.zeros(n)
    chords = [(220.00, 261.63, 329.63), (174.61, 220.00, 261.63), (196.00, 246.94, 293.66), (164.81, 207.65, 246.94)]
    seg = int(6 * SR)
    for i, notes in enumerate(chords):
        a, b = i * seg, min(n, (i + 1) * seg)
        k = np.arange(b - a)
        env = np.minimum(1.0, np.minimum(k / (0.6 * SR), (b - a - k) / (0.9 * SR)))
        tt = t[a:b]
        for j, f in enumerate(notes):
            left[a:b] += 0.11 * env * (np.sin(2 * np.pi * f * 0.997 * tt) + 0.4 * np.sin(2 * np.pi * 2 * f * 0.997 * tt + j))
            right[a:b] += 0.11 * env * (np.sin(2 * np.pi * f * 1.003 * tt + 1.3) + 0.4 * np.sin(2 * np.pi * 2 * f * 1.003 * tt + 2 * j))
    duck = 1.0 - 0.6 * np.exp(-(t % beat) / 0.14) * drums  # the pads pump with the kick
    fade = np.clip(t / 2.5, 0.0, 1.0)
    left, right = left * duck * fade, right * duck * fade
    for k in range(int(sec / beat)):  # kick, centre
        a = int(k * beat * SR)
        m_ = min(int(0.35 * SR), n - a)
        if m_ <= 0:
            break
        tk = np.arange(m_) / SR
        kick = 0.6 * drums[a] * np.sin(2 * np.pi * (50 + 90 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 9)
        left[a:a + m_] += kick
        right[a:a + m_] += kick
    for i, f in enumerate((55.0, 43.65, 49.0, 41.2)):  # bass, centre
        a, b = i * seg, min(n, (i + 1) * seg)
        bass = 0.17 * np.sin(2 * np.pi * f * t[a:b]) * (0.6 + 0.4 * np.sin(2 * np.pi * 1.6667 * t[a:b])) * drums[a:b]
        left[a:b] += bass
        right[a:b] += bass
    for k in range(int(sec / (beat / 2))):  # plucks and hats, panned about
        a = int(k * beat / 2 * SR)
        m_ = min(int(0.45 * SR), n - a)
        if m_ <= 0:
            break
        f = chords[min(len(chords) - 1, a // seg)][k % 3] * 2 * (2 if k % 4 == 3 else 1)
        tp = np.arange(m_) / SR
        pluck = 0.4 * plucks[a] * (np.sin(2 * np.pi * f * tp) + 0.3 * np.sin(2 * np.pi * 3 * f * tp)) * np.exp(-tp * 7)
        pan = 0.5 + 0.45 * np.sin(k * 1.1)
        left[a:a + m_] += pluck * (1 - pan)
        right[a:a + m_] += pluck * pan
        if k % 2:
            mh = min(int(0.05 * SR), n - a)
            hat = np.diff(r.standard_normal(mh + 1)) * np.exp(-np.arange(mh) / (0.012 * SR)) * 0.22 * hats[a]
            gl = 1.0 if (k // 2) % 2 == 0 else 0.35
            left[a:a + mh] += hat * gl
            right[a:a + mh] += hat * (1.35 - gl)
    a = int(18 * SR)  # the riser: independent noise in each channel, softly band-limited
    f = np.fft.rfftfreq(n - a, 1.0 / SR)
    soft = np.where((f > 300) & (f < 12000), 1.0 / (1.0 + (f / 3500.0) ** 2), 0.0)
    ramp = (np.arange(n - a) / float(n - a)) ** 2.5 * 0.5
    left[a:] += np.fft.irfft(np.fft.rfft(r.standard_normal(n - a)) * soft, n - a) * ramp * 9
    right[a:] += np.fft.irfft(np.fft.rfft(r.standard_normal(n - a)) * soft, n - a) * ramp * 9
    out = np.stack([left, right], axis=1)
    return out / np.abs(out).max() * 0.7


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
