import ctypes, sys, time, tkinter as tk
import numpy as np
import support as T
from support import m, demo_audio
m.App.THREADED = True
ctypes.windll.winmm.timeBeginPeriod(1)
T.sandbox()
cap = T.SynthCapture(); cap.start()
root = tk.Tk(); root.attributes('-alpha', 0.0); root.geometry('1916x1200+0+0')
app = m.App(root, cap)
T.mute_keys(root)
root.after(1000, root.quit); root.mainloop()
app.k = 1.55; app.build_ui(); root.geometry('1916x1200+0+0')
a_ = demo_audio(1)
app.open_loaded(m.Clip(a_ * 10 ** (-19 / 20), -19.0, name='probe.wav'))
root.after(1500, root.quit); root.mainloop()
tl = app.tl
print('timeline canvas %dx%d' % (tl.winfo_width(), tl.winfo_height()))
kinds = {}
for i in tl.find_all():
    kinds[tl.type(i)] = kinds.get(tl.type(i), 0) + 1
print('items by type:', kinds)
polys = [(i, len(tl.coords(i)) // 2) for i in tl.find_all() if tl.type(i) == 'polygon']
print('polygons (vertices):', sorted([n for _, n in polys], reverse=True)[:6])
def head_move_cost(label, n=60):
    t0 = time.perf_counter()
    for k in range(n):
        tl.delete('head')
        x = 100 + k * 5
        tl.create_line(x, 10, x, 250, fill='#fff', width=2, tags='head')
        tl.create_polygon(x - 7, 8, x + 7, 8, x, 20, fill='#fff', outline='', tags='head')
        root.update_idletasks()
    print('%-44s %.2f ms per head move (incl. Tk redraw)' % (label, (time.perf_counter() - t0) / n * 1000))
head_move_cost('as it is')
for i, _ in polys:
    if 'head' not in tl.gettags(i): tl.itemconfig(i, state='hidden')
head_move_cost('envelope polygons hidden')
for i in tl.find_all():
    if tl.type(i) in ('line', 'rectangle') and 'head' not in tl.gettags(i): tl.itemconfig(i, state='hidden')
head_move_cost('+ lines and rectangles hidden')
for i in tl.find_all():
    if 'head' not in tl.gettags(i): tl.itemconfig(i, state='hidden')
head_move_cost('everything but the head hidden')
cap.stop = True; root.destroy()
