import sys, time, tkinter as tk
import support as T
from support import m, pump
m.App.THREADED = True
T.sandbox()
cap = T.SynthCapture(); cap.start()
root = tk.Tk(); root.attributes('-alpha', 0.0); root.geometry('+0+0')
app = m.App(root, cap)
T.mute_keys(root)
pump(root, 3.0)
s0 = {k: w.seq for k, w in app.plots.items()}
f0, t0 = app.frame, time.time()
pump(root, 3.0)
dt = time.time() - t0
print('frames/s %.1f' % ((app.frame - f0) / dt), {k: round((w.seq - s0[k]) / dt, 1) for k, w in app.plots.items()}, 'work_ms %.1f redraw_ms %.1f busy %s' % (app.work_ms, app.redraw_ms, app.__dict__.get('_busy')))
cap.stop = True
root.destroy()
