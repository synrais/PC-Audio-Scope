"""the real window (fully transparent, so nothing shows on the desktop): it is as tall as what shows, the timeline makes it grow and shrink without changing the scale, and a long message never makes it wider"""
import sys
import tkinter as tk

import support as T
from support import check, m, pump

if sys.platform != 'win32':
    print('window_fit: only checked on Windows')
    sys.exit(0)

T.sandbox()
m.App.THREADED = True  # the real thing: the graphs are drawn on threads of their own
cap = T.SynthCapture()
cap.start()
root = tk.Tk()
root.attributes('-alpha', 0.0)
root.geometry('+0+0')
app = m.App(root, cap)
T.mute_keys(root)
pump(root, 1.0)
w0, h0 = root.winfo_width(), root.winfo_height()
check('live: the window is as wide as the scope and as tall as what shows (no timeline)', w0 == app.CW and h0 == root.winfo_reqheight() and app.tl.winfo_manager() == '', (w0, h0, app.CW, root.winfo_reqheight()))
k0 = app.k
app.rec_toggle()
pump(root, 1.2)
h1 = root.winfo_height()
check('recording: the window grew by the timeline, same width, same scale', h1 >= h0 + app.TH and root.winfo_width() == w0 and app.k == k0, (h0, h1, app.TH, root.winfo_width(), app.k, k0))
app.rec_toggle()
pump(root, 1.2)
app.msg('a very long message ' * 40)
pump(root, 0.6)
check('a long message in the transport row does not widen the window', root.winfo_width() == w0 and root.winfo_reqwidth() > w0, (root.winfo_width(), root.winfo_reqwidth(), w0))
app.msg('')
app.go_live()
pump(root, 1.2)
check('back to live: the window shrinks to its first size and the scale is unchanged', (root.winfo_width(), root.winfo_height()) == (w0, h0) and app.k == k0, (root.winfo_width(), root.winfo_height(), w0, h0))

# ---- real mouse events (the hidden window of functional.py does not get them): Tk counts single, double, triple clicks, the scope must not follow it
sx_, sy_ = (app.P['osc'][0] + app.P['osc'][2]) // 2, (app.P['osc'][1] + app.P['osc'][3]) // 2
app.click_last = None
states = []
for k_ in range(3):
    app.c.event_generate('<Button-1>', x=sx_, y=sy_)
    root.update()
    states.append(app.zoom)
check('real mouse events: click, click, click (Tk calls the third a triple click) enlarges a scope and leaves it big', states == [None, 'osc', 'osc'], states)
app.c.event_generate('<Button-1>', x=sx_, y=sy_)
root.update()
check('real mouse events: the fourth click is the second of a new double click and puts the scope back', app.zoom is None, app.zoom)
app.click_last = None
pump(root, 0.5)

# ---- a scope enlarged: it is the whole window, nothing else in it
root.update_idletasks()
ww0, wh0 = root.winfo_width(), root.winfo_height()
app.zoom_panel('spec')
pump(root, 0.8)
check('an enlarged scope: the canvas is as big as the window (which keeps its size), and the button rows are gone', (app.c.winfo_width(), app.c.winfo_height()) == (ww0, wh0) == (root.winfo_width(), root.winfo_height()) and app.controls.winfo_manager() == '' and app.transport.winfo_manager() == '', (app.c.winfo_width(), app.c.winfo_height(), ww0, wh0))
check('the enlarged scope fills the canvas to a small margin', app.panel_frame['spec'][0] == app.S(8) and app.panel_frame['spec'][2] == ww0 - app.S(8) and app.panel_frame['spec'][1] == app.S(8), (app.panel_frame['spec'], ww0))
root.geometry('%dx%d' % (ww0 - 100, wh0 - 60))
pump(root, 1.0)
check('resizing the window refits the enlarged scope to it', app.zoom == 'spec' and (app.CW, app.CH) == (root.winfo_width(), root.winfo_height()) and app.panel_frame['spec'][2] == root.winfo_width() - app.S(8), (app.CW, app.CH, root.winfo_width(), root.winfo_height()))
root.geometry('%dx%d' % (ww0, wh0))
pump(root, 1.0)
app.zoom_panel(None)
pump(root, 1.0)
check('back again: the rows are in place and the window is as tall as its content', app.zoom is None and app.controls.winfo_manager() == 'pack' and app.transport.winfo_manager() == 'pack' and root.winfo_height() == root.winfo_reqheight() and (app.CW, app.CH) == (app.S(app.BASE_W), app.S(app.BASE_H)), (root.winfo_height(), root.winfo_reqheight(), app.CW, app.CH))
# ---- the graphs are drawn on their own threads and the window thread stays light
import threading
import time
pump(root, 3.0)
check('the graphs have threads of their own, and their pictures reach the window', all(n_ in app.plots and app.plots[n_].thread.is_alive() for n_ in ('osc', 'spec', 'vec')) and all(app.photos.get(n_) is not None for n_ in ('osc', 'spec', 'vec')), (sorted(app.plots), sorted(app.photos)))
check('the window thread spends little time per frame (the drawing is not done on it: it used to be over 25 ms, with the history redrawing 30 times a second it is about 15 ms)', app.work_ms < 20.0, round(app.work_ms, 1))
s0, h0_, hh0_, t_0 = app.plots['spec'].seq, app.plots['osc'].seq, app.plots['hist'].seq, time.time()
pump(root, 2.0)
rate_spec, rate_osc, rate_hist = (app.plots['spec'].seq - s0) / (time.time() - t_0), (app.plots['osc'].seq - h0_) / (time.time() - t_0), (app.plots['hist'].seq - hh0_) / (time.time() - t_0)
check('the spectrum and the oscilloscope get a new picture about every frame (no skipped frames)', rate_spec >= 24 and rate_osc >= 24, (round(rate_spec, 1), round(rate_osc, 1)))
check('the level history gets a new picture about every frame too (it moves by a fraction of a pixel each time, not a pixel at a time)', rate_hist >= 24, round(rate_hist, 1))
workers = [wk.thread for wk in app.plots.values()]
app.stop_plots()
for th_ in workers:
    th_.join(5.0)
check('stopping the graphs ends their threads', not any(th_.is_alive() for th_ in workers), [th_.is_alive() for th_ in workers])
cap.stop = True
root.destroy()
T.finish()
