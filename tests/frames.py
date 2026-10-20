"""Frame rate: automatic, anywhere from 30 to 60 frames a second as the computer allows; the smoothing steps and the counters that were counted in frames follow the rate"""
import tkinter as tk

import support as T
from support import check, m, pump

m.App.THREADED = True  # (the frames are timed with the graphs on their threads, as in the program)
T.sandbox()
cap = T.SynthCapture()
cap.start()
root = tk.Tk()
root.withdraw()
app = m.App(root, cap)

check('it starts at 30 frames a second', app.fps == m.FPS_MIN == 30.0)
check('at 30 a step per frame is the step as written, and 0.1 s is 3 frames', abs(app.rate(0.2) - 0.2) < 1e-12 and app.every(100) == 3 and app.every(333) == 10)
app.fps = 60.0
check('at 60 a step per frame is a smaller step that makes the same progress in the same time, and 0.1 s is 6 frames', abs((1 - app.rate(0.2)) ** 2 - 0.8) < 1e-9 and app.every(100) == 6 and app.every(333) == 20, (app.rate(0.2), app.every(100)))
app.fps = 45.0
check('in between the steps follow the rate too: 45 fps is 4 or 5 frames in 0.1 s and a step of 0.2 at 30 is the same progress over 1.5 frames', app.every(100) in (4, 5) and abs((1 - app.rate(0.2)) ** 1.5 - 0.8) < 1e-9)


def run(load, start, n):
    """the frame rates after n looks at a frame that takes `load` ms"""
    app.fps = start
    app.work_ms, app.redraw_ms = load * 0.7, load * 0.3
    seen = [app.fps]
    for _ in range(n):
        app.auto_frame_rate()
        seen.append(app.fps)
    return seen


up = run(7.0, 30.0, 10)
check('a window with room climbs to 60 by 4 a second and stops there: %s' % up[:10], up[1] == 34.0 and up[-1] == 60.0 and max(up) == 60.0 and all(b - a <= 4.0 + 1e-9 for a, b in zip(up, up[1:])), up)
down = run(30.0, 60.0, 10)
check('a window with no room falls to 30 by 8 a second and stops there: %s' % down[:6], down[1] == 52.0 and down[-1] == 30.0 and min(down) == 30.0 and all(a - b <= 8.0 + 1e-9 for a, b in zip(down, down[1:])), down)
mid = run(14.0, 60.0, 4)
check('in between it settles in between: 14 ms a frame is 50 fps (70 % of its 20 ms)', abs(mid[-1] - 50.0) < 1e-6, mid)
mid = run(17.5, 30.0, 12)
check('17.5 ms a frame is 40 fps', abs(mid[-1] - 40.0) < 1e-6, mid)
check('and the frame rate never leaves 30 to 60', all(30.0 <= v <= 60.0 for v in up + down + mid))

# the busy test: only at the slowest frame rate (above it the frame rate gives way first)
app.fps = 30.0
app.work_ms, app.redraw_ms, app._busy = 18.0, 8.0, False
app.busy()
check('at 30 the window is busy from 24 ms of load', app._busy is True, app._busy)
app.work_ms, app.redraw_ms = 12.0, 8.0
app.busy()
check('and stays busy until the load is under 17 ms', app._busy is True, app._busy)
app.work_ms, app.redraw_ms = 10.0, 5.0
app.busy()
check('then it is not', app._busy is False, app._busy)
app.fps = 60.0
app.work_ms, app.redraw_ms, app._busy = 18.0, 8.0, False
app.busy()
check('at 60 the same load is not busy: the frame rate gives way first', app._busy is False, app._busy)
app.work_ms = app.redraw_ms = 0.0

# there is no frame rate row in the menus
check('no window menu has a Frame rate row', not any('Frame rate' in [e_['label'] for e_ in app.panel_menu_build(n_).entries if e_['kind'] == 'stepper'] for n_ in m.PANELS))

# the frames really come at that pace (the automatic setting switched off for the measurement)
app.auto_frame_rate = lambda: None
app.fps = 60.0
f0 = app.frame
pump(root, 1.0)
n60 = app.frame - f0
app.fps = 30.0
f0 = app.frame
pump(root, 1.0)
n30 = app.frame - f0
check('the frames come at the pace: %d in a second at 60, %d at 30' % (n60, n30), 15 <= n30 <= 36 and n60 > 1.3 * n30, (n60, n30))

# the brightness of a graph that is drawn again every frame is the same at any frame rate, and a worker that falls behind drops the frames that piled up
import math
build_up = lambda dt, tau: m.frame_gain(dt, tau) / (1.0 - math.exp(-dt / tau))
check('a frame of 1/30 s keeps its light (gain 1), a shorter frame gets less', abs(m.frame_gain(1 / 30.0, m.OSC_TAU) - 1.0) < 1e-12 and m.frame_gain(1 / 60.0, m.OSC_TAU) < 0.75, (m.frame_gain(1 / 60.0, m.OSC_TAU)))
check('and the light that builds up is the same at 30, 45 and 60 frames a second, for the oscilloscope and the spectrum',
      all(abs(build_up(1.0 / fps, tau) - build_up(1 / 30.0, tau)) < 1e-9 for fps in (30.0, 45.0, 60.0, 17.0) for tau in (m.OSC_TAU, m.SPEC_TAU)))


class Stub:
    clean = False

    def image(self):
        return None


import threading
gate, ran = threading.Event(), []
wk = m.BeamWorker(Stub(), True)
wk.add(lambda pl: gate.wait(5))  # keeps the thread busy while the others pile up
pump(root, 0.2)
for i in range(5):
    wk.add(m.stale(lambda pl, extra=0.0, i=i: ran.append((i, round(extra, 3))), 0.02))
gate.set()
pump(root, 0.5)
check('a worker that fell behind runs only the newest of the jobs that redraw from the sound as it is now, with the time of the others', ran == [(4, 0.08)], ran)
ran2 = []
gate2 = threading.Event()
wk2 = m.BeamWorker(Stub(), True)
wk2.add(lambda pl: gate2.wait(5))
pump(root, 0.2)
for i in range(4):
    wk2.add(lambda pl, i=i: ran2.append(i))
gate2.set()
pump(root, 0.5)
check('the jobs that add new sound (not marked) all run, in order', ran2 == [0, 1, 2, 3], ran2)
wk.stop()
wk2.stop()

cap.stop = True
T.finish()
