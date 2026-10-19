"""the real window (fully transparent, so nothing shows on the desktop): it is as tall as what shows, the timeline makes it grow and shrink without changing the scale, and a long message never makes it wider"""
import sys
import tkinter as tk

import support as T
from support import check, m, pump

if sys.platform != 'win32':
    print('window_fit: only checked on Windows')
    sys.exit(0)

import ctypes
ctypes.windll.winmm.timeBeginPeriod(1)  # as the program itself does: without it a timer fires 15.6 ms late
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
check('the enlarged scope fills the canvas to a small margin', app.panel_frame['spec'][0] == app.S(8) and app.panel_frame['spec'][2] == ww0 - app.S(8) - 1 and app.panel_frame['spec'][1] == app.S(8), (app.panel_frame['spec'], ww0))
root.geometry('%dx%d' % (ww0 - 100, wh0 - 60))
pump(root, 1.0)
check('resizing the window refits the enlarged scope to it', app.zoom == 'spec' and (app.CW, app.CH) == (root.winfo_width(), root.winfo_height()) and app.panel_frame['spec'][2] == root.winfo_width() - app.S(8) - 1, (app.CW, app.CH, root.winfo_width(), root.winfo_height()))
root.geometry('%dx%d' % (ww0, wh0))
pump(root, 1.0)
app.zoom_panel(None)
pump(root, 1.0)
check('back again: the rows are in place and the window is as tall as its content', app.zoom is None and app.controls.winfo_manager() == 'pack' and app.transport.winfo_manager() == 'pack' and root.winfo_height() == root.winfo_reqheight() and (app.CW, app.CH) == (app.S(app.BASE_W), app.S(app.BASE_H)), (root.winfo_height(), root.winfo_reqheight(), app.CW, app.CH))
for n_ in ('hist', 'vec', 'osc', 'spec'):  # grid and info both off: an enlarged window is edge to edge, nothing round it and no gap
    app.set_panel_opt(n_, 'fs_grid', False)
    app.set_panel_opt(n_, 'fs_info', False)
    app.zoom_panel(n_)
    pump(root, 0.5)
    ww_, wh_ = root.winfo_width(), root.winfo_height()
    pf = app.panel_frame.get(n_) or app.P[n_]
    rects_ = [i_ for i_ in app.c.find_all() if app.c.type(i_) == 'rectangle' and app.c.coords(i_)[0] < app.CW]
    check('enlarged %s with its grid and info off: edge to edge, no frame, no column for numbers (nothing is left but the picture)' % n_,
          app.zoom == n_ and (app.CW, app.CH) == (ww_, wh_) and not rects_ and app.P[n_][0] == pf[0] and ((pf[0], pf[1], pf[2], pf[3]) == (0, 0, ww_ - 1, wh_ - 1) if n_ in ('hist', 'osc', 'spec') else (min(pf[0], pf[1]) == 0 and max(pf[2] - pf[0], pf[3] - pf[1]) >= min(ww_, wh_) - 1)),
          (n_, pf, app.P[n_], ww_, wh_, rects_))
    app.zoom_panel(None)
    app.set_panel_opt(n_, 'fs_grid', True)
    app.set_panel_opt(n_, 'fs_info', True)
pump(root, 0.8)
# ---- the popup menu of a window, for real (a window of its own, shown fully transparent): the arrows are clicked and held, keys step it, it stays open, Escape and a click outside close it
import json
import time
import types
m.PanelMenu.HIDDEN = True
app.zoom_panel(None)
pump(root, 0.5)
ox_, oy_ = app.P['osc'][0] + 40, app.P['osc'][1] + 40
app.panel_opts.pop('osc', None)
app.popup = None
app.panel_menu(types.SimpleNamespace(x=ox_, y=oy_, x_root=root.winfo_rootx() + app.c.winfo_x() + ox_, y_root=root.winfo_rooty() + app.c.winfo_y() + oy_))
pm_ = app.popup
root.update()
check('right click: the popup of the window opens, with its rows laid out inside it', pm_ is not None and pm_.top is not None and pm_.top.winfo_exists() and pm_.width > 100 and pm_.height > 100 and len(pm_.rows) >= 5, (pm_ and pm_.width, pm_ and pm_.height))
sx0_, sy0_ = pm_.top.winfo_rootx(), pm_.top.winfo_rooty()
check('the popup is on screen', 0 <= sx0_ and sx0_ + pm_.width <= pm_.top.winfo_screenwidth() and 0 <= sy0_ and sy0_ + pm_.height <= pm_.top.winfo_screenheight(), (sx0_, sy0_, pm_.width, pm_.height))


def rowof(label_):
    return next(r_ for r_ in pm_.rows if r_[0].get('label') == label_)


def click_at(x_, y_):
    pm_.top.event_generate('<Motion>', x=x_, y=y_, rootx=sx0_ + x_, rooty=sy0_ + y_)
    pm_.top.event_generate('<ButtonPress-1>', x=x_, y=y_, rootx=sx0_ + x_, rooty=sy0_ + y_)
    root.update()


def release_at(x_, y_):
    pm_.top.event_generate('<ButtonRelease-1>', x=x_, y=y_, rootx=sx0_ + x_, rooty=sy0_ + y_)
    root.update()


e_, y0_, y1_ = rowof('Narrow burn')
lx0_, lx1_, rx0_, rx1_ = e_['boxes']
ym_ = (y0_ + y1_) // 2
start_ = e_['n']
click_at((rx0_ + rx1_) // 2, ym_)
release_at((rx0_ + rx1_) // 2, ym_)
check('a click on the right arrow steps Narrow burn up by 0.1 and the menu stays open', e_['n'] == start_ + 1 and app.panel_burn_level('osc') == (start_ + 1) / 10.0 and app.popup is pm_ and pm_.top is not None
      and app.beam_plot('osc').plot.glow == (start_ + 1) / 10.0, (e_['n'], start_))
click_at((lx0_ + lx1_) // 2, ym_)
release_at((lx0_ + lx1_) // 2, ym_)
check('a click on the left arrow steps it back', e_['n'] == start_ and app.panel_burn_level('osc') == start_ / 10.0, e_['n'])
click_at((rx0_ + rx1_) // 2, ym_)  # held: it runs
t0_ = time.time()
while time.time() - t0_ < 1.2:
    root.update()
    time.sleep(0.01)
ran_ = e_['n'] - start_
release_at((rx0_ + rx1_) // 2, ym_)
check('an arrow held down runs on (after a moment, several steps a second) and the choice is saved when it is let go', ran_ >= 6 and json.load(open(m.SETTINGS))['panels']['osc']['burn'] == e_['n'] / 10.0 and not pm_.unsaved, (ran_, e_['n']))
nrun_ = e_['n']
time.sleep(0.4)
root.update()
check('and it stops when the arrow is let go', e_['n'] == nrun_, (e_['n'], nrun_))
# the keys (the highlight, then Left / Right / Home / End), through the popup's own handler
pm_.hover = None
for key_ in ('Down', 'Down', 'Down'):
    pm_.on_key(types.SimpleNamespace(keysym=key_))
check('Down moves the highlight along the rows (the heading is skipped)', pm_.hover is not None and not pm_.hover.get('heading') and pm_.hover['label'] == 'Narrow burn', pm_.hover and pm_.hover['label'])
n1_ = e_['n']
pm_.on_key(types.SimpleNamespace(keysym='Right'))
pm_.on_key(types.SimpleNamespace(keysym='Right'))
pm_.on_key(types.SimpleNamespace(keysym='Left'))
check('Right and Left step the highlighted stepper', e_['n'] == n1_ + 1, (e_['n'], n1_))
pm_.on_key(types.SimpleNamespace(keysym='End'))
check('End takes it to 3.0', e_['n'] == 30 and app.panel_burn_level('osc') == 3.0, e_['n'])
pm_.on_key(types.SimpleNamespace(keysym='Home'))
check('Home takes it to Off: clean lines, and the Line strength row goes from the menu', e_['n'] == 0 and not app.panel_crt('osc') and not pm_.visible(pm_.stepper('Line strength')) and all(r_[0].get('label') != 'Line strength' for r_ in pm_.rows), e_['n'])
pm_.on_key(types.SimpleNamespace(keysym='Right'))
check('and one step on it is the beam again at 0.1, with the Line strength row back', app.panel_crt('osc') and app.panel_burn_level('osc') == 0.1 and any(r_[0].get('label') == 'Line strength' for r_ in pm_.rows), app.panel_opts.get('osc'))
pm_.on_key(types.SimpleNamespace(keysym='Down'))
ewide_ = pm_.hover
pm_.on_key(types.SimpleNamespace(keysym='Right'))
check('Wide burn steps with the keys too: 0.1 is a wide glow of gain 0.4', ewide_['label'] == 'Wide burn' and app.panel_wide_level('osc') == 0.1 and abs(app.beam_plot('osc').plot.screens[0].wide - 0.4) < 1e-9, (ewide_['label'], app.panel_wide_level('osc')))
pm_.on_key(types.SimpleNamespace(keysym='Down'))
es_ = pm_.hover
pm_.on_key(types.SimpleNamespace(keysym='Right'))
check('Line strength steps with the keys too', es_['label'] == 'Line strength' and es_['n'] == 7 and app.panel_strength('osc') == 7, (es_['label'], es_['n']))
pm_.on_key(types.SimpleNamespace(keysym='Home'))
pm_.on_key(types.SimpleNamespace(keysym='Left'))
check('Home takes Line strength to 1, and Left does not go below it', es_['n'] == 1 and app.panel_strength('osc') == 1, es_['n'])
pm_.on_key(types.SimpleNamespace(keysym='End'))
check('End takes it to 10', es_['n'] == 10 and app.panel_strength('osc') == 10 and abs(app.strength_lift('osc') - 0.55) < 1e-9, es_['n'])
pm_.on_key(types.SimpleNamespace(keysym='Escape'))
root.update()
check('Escape closes the menu', app.popup is None and pm_.top is None, app.popup)
# a click outside closes it; a click on Grid does what the old menu did and closes it
app.panel_menu(types.SimpleNamespace(x=ox_, y=oy_, x_root=root.winfo_rootx() + app.c.winfo_x() + ox_, y_root=root.winfo_rooty() + app.c.winfo_y() + oy_))
pm_ = app.popup
root.update()
sx0_, sy0_ = pm_.top.winfo_rootx(), pm_.top.winfo_rooty()
pm_.top.event_generate('<ButtonPress-1>', x=-40, y=-40, rootx=sx0_ - 40, rooty=sy0_ - 40)
root.update()
check('a click outside the popup closes it', app.popup is None and pm_.top is None, app.popup)
app.panel_menu(types.SimpleNamespace(x=ox_, y=oy_, x_root=root.winfo_rootx() + app.c.winfo_x() + ox_, y_root=root.winfo_rooty() + app.c.winfo_y() + oy_))
pm_ = app.popup
root.update()
sx0_, sy0_ = pm_.top.winfo_rootx(), pm_.top.winfo_rooty()
eg_, gy0_, gy1_ = rowof('Grid')
was_grid_ = app.panel_grid('osc')
click_at(pm_.width // 2, (gy0_ + gy1_) // 2)  # (a command is done when the button goes down, and the menu closes)
pump(root, 0.3)
check('a click on Grid toggles it and closes the menu', app.panel_grid('osc') != was_grid_ and app.popup is None, (was_grid_, app.panel_grid('osc')))
app.panel_opts.clear()
app.refresh_panels()
m.PanelMenu.HIDDEN = False
pump(root, 0.5)

# ---- the graphs are drawn on their own threads and the window thread stays light
import threading
import time
pump(root, 3.0)
check('the graphs have threads of their own, and their pictures reach the window', all(n_ in app.plots and app.plots[n_].thread.is_alive() for n_ in ('osc', 'spec', 'vec')) and all(app.photos.get(n_) is not None for n_ in ('osc', 'spec', 'vec')), (sorted(app.plots), sorted(app.photos)))
check('the window thread spends little time per frame (the drawing is not done on it: it used to be over 25 ms, with the history redrawing 30 times a second it is about 15 ms)', app.work_ms < 20.0, round(app.work_ms, 1))
s0, h0_, hh0_, t_0 = app.plots['spec'].seq, app.plots['osc'].seq, app.plots['hist'].seq, time.time()
root.after(2000, root.quit)  # the real main loop (the pump of the tests sleeps between its looks at the window, which hides the real pace of the frames)
root.mainloop()
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
ctypes.windll.winmm.timeEndPeriod(1)
T.finish()
