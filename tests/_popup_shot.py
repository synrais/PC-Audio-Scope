"""a picture of the popup menu (the window and the menu fully transparent, captured with PrintWindow)"""
import sys, types, ctypes
from ctypes import wintypes
import tkinter as tk
import support as T
from support import m, pump
from PIL import Image
user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
class BIH(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG), ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
                ('biSizeImage', wintypes.DWORD), ('x', wintypes.LONG), ('y', wintypes.LONG), ('c', wintypes.DWORD), ('i', wintypes.DWORD)]
user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
def grab(win):
    win.update()
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    w, h = win.winfo_width(), win.winfo_height()
    hdc = user32.GetDC(hwnd); mdc = gdi32.CreateCompatibleDC(hdc); bmp = gdi32.CreateCompatibleBitmap(hdc, w, h); old = gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 3)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(BIH(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)), 0)
    gdi32.SelectObject(mdc, old); gdi32.DeleteObject(bmp); gdi32.DeleteDC(mdc); user32.ReleaseDC(hwnd, hdc)
    return Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
T.sandbox()
cap = T.SynthCapture(); cap.start()
root = tk.Tk(); root.attributes('-alpha', 0.0); root.geometry('+0+0')
app = m.App(root, cap)
T.mute_keys(root)
m.PanelMenu.HIDDEN = True
pump(root, 1.2)
imgs = []
for name, burn, st in (('vec', None, None), ('osc', 14, 8), ('osc', 0, None)):
    app.panel_opts.pop(name, None)
    if burn is not None:
        app.panel_opts.setdefault(name, {})['burn'] = burn / 10.0
    if st is not None:
        app.panel_opts.setdefault(name, {})['strength'] = st
    app.refresh_panels()
    pm = app.panel_menu_build(name)
    app.popup = pm
    pm.popup(200, 200)
    root.update()
    # highlight the CRT burn row
    pump(root, 0.4)
    pm.hover = pm.stepper('CRT burn'); pm.draw(); pump(root, 0.4)
    imgs.append(grab(pm.top))
    pm.close()
W = sum(i.width for i in imgs) + 20 * (len(imgs) + 1); H = max(i.height for i in imgs) + 40
page = Image.new('RGB', (W, H), (12, 14, 18)); x = 20
for i in imgs:
    page.paste(i, (x, 20)); x += i.width + 20
page = page.resize((page.width * 2, page.height * 2), Image.Resampling.NEAREST)
page.save(sys.argv[1]); print(page.size)
cap.stop = True; root.destroy()
