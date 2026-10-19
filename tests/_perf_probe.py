"""how snappy the program is, in a real (invisible) window with the real Tk main loop, live synthetic sound, threads on.
   python perf_probe.py WIDTH HEIGHT [zoom: none|osc|vec|met|spec|hist] [crt: 1|0]
Measures: frames a second, time the window thread spends in a frame (our code), time Tk then needs to put the changed pictures on screen, how late a 5 ms timer fires (how fast the window answers),
the time the picture builders (threads) take, and the whole process cpu"""
import ctypes, os, sys, time, tkinter as tk
import numpy as np
import support as T
from support import m
W, H = int(sys.argv[1]), int(sys.argv[2])
zoom = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != 'none' else None
crt = (sys.argv[4] != '0') if len(sys.argv) > 4 else True
m.App.THREADED = True
ctypes.windll.winmm.timeBeginPeriod(1)
T.sandbox()
cap = T.SynthCapture(); cap.start()
root = tk.Tk(); root.attributes('-alpha', 0.0); root.geometry('%dx%d+0+0' % (W, H))
app = m.App(root, cap)
T.mute_keys(root)
root.after(1200, root.quit); root.mainloop()   # let the window settle (it rescales itself)
if len(sys.argv) > 5:
    app.k = float(sys.argv[5]); app.build_ui()
    root.geometry('%dx%d+0+0' % (W, H)); root.after(800, root.quit); root.mainloop()
if not crt:
    for n_ in m.PANELS:
        app.panel_opts.setdefault(n_, {})['crt'] = False
    app.refresh_panels()
if zoom:
    app.zoom_panel(zoom)
import os as _os
mode_ = _os.environ.get('PROBE_MODE')
if mode_ == 'spectrogram':
    app.set_spec_mode('spectrogram')
elif mode_ == 'review':
    from support import demo_audio
    a_ = demo_audio(1)
    app.open_loaded(m.Clip(a_ * 10 ** (-19 / 20), -19.0, name='probe.wav'))
    app.play_toggle()
elif mode_ == 'rec':
    app.rec_toggle()
root.after(1500, root.quit); root.mainloop()
acc = {}
def wrap(obj, name, label):
    orig = getattr(obj, name)
    def f(*a, **k):
        t0 = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            acc.setdefault(label, []).append((time.perf_counter() - t0) * 1000)
    setattr(obj, name, f)
for n in ('draw', 'show_plot', 'draw_spectrum', 'draw_osc', 'draw_vector', 'draw_bars', 'refresh_history', 'update_transport', 'draw_spectrogram', 'draw_timeline', 'refresh_rows', 'cmp_poll'):
    wrap(m.App, n, n)
orig_tick = m.App.tick
def tick(self):
    t0 = time.perf_counter()
    orig_tick(self)
    t1 = time.perf_counter()
    root.update_idletasks()   # Tk puts what changed on screen
    acc.setdefault('TICK (our code)', []).append((t1 - t0) * 1000)
    acc.setdefault('TK REDRAW after the tick', []).append((time.perf_counter() - t1) * 1000)
m.App.tick = tick
orig_d = m.BeamWorker._draw
def _draw(self):
    t0 = time.perf_counter()
    orig_d(self)
    key = 'builder %s %dx%d' % (type(self.plot).__name__, getattr(self.plot, 'w', 0) or getattr(getattr(self.plot, 'screen', None), 'w', 0), getattr(self.plot, 'h', 0) or getattr(getattr(self.plot, 'screen', None), 'h', 0))
    acc.setdefault(key, []).append((time.perf_counter() - t0) * 1000)
m.BeamWorker._draw = _draw
late = []
def ping(due):
    late.append((time.perf_counter() - due) * 1000)
    nd = time.perf_counter() + 0.005
    root.after(5, lambda: ping(nd))
nd0 = time.perf_counter() + 0.005
root.after(5, lambda: ping(nd0))
seqs0 = {k: w.seq for k, w in app.plots.items()}
f0, cpu0, t0 = app.frame, time.process_time(), time.perf_counter()
root.after(8000, root.quit); root.mainloop()
dur = time.perf_counter() - t0
cpu = (time.process_time() - cpu0) / dur
fps = (app.frame - f0) / dur
rates = ', '.join('%s %.0f/s' % (k, (w.seq - seqs0.get(k, 0)) / dur) for k, w in sorted(app.plots.items()))
tk_ = acc.get('TICK (our code)', [0]); rd = acc.get('TK REDRAW after the tick', [0])
la = np.array(late)
print('%dx%d zoom=%s crt=%s k=%.2f canvas %dx%d' % (W, H, zoom, crt, app.k, app.CW, app.CH))
print('  frames/s %.1f | our code per frame: mean %.1f ms max %.1f | Tk redraw per frame: mean %.1f ms max %.1f | together %.1f ms of a 33 ms frame' % (fps, np.mean(tk_), np.max(tk_), np.mean(rd), np.max(rd), np.mean(tk_) + np.mean(rd)))
print('  window answers a 5 ms timer: median %.1f ms late, p95 %.1f, max %.1f | cpu %.0f%% of a core | pictures/s: %s' % (np.median(la), np.percentile(la, 95), la.max(), cpu * 100, rates))
for k, v in sorted(acc.items(), key=lambda kv: -sum(kv[1]) / max(1, 1)):
    if k.startswith('TICK') or k.startswith('TK'):
        continue
    print('    %-34s mean %6.2f ms  max %6.1f ms  calls/s %.1f' % (k, np.mean(v), np.max(v), len(v) / dur))
print('STATUS:', app.c.itemcget(app.status, 'text')[:200])
print('worker errors:', {k: (w.error or '')[-200:] for k, w in app.plots.items() if w.error})
cap.stop = True
root.destroy()
ctypes.windll.winmm.timeEndPeriod(1)
