"""the vectorscope's simulated phosphor screen: the path, brightness from speed, persistence, the glow and the picture"""
import numpy as np

import support as T
from support import check, m

# ---- the path: straight pieces cut into bits, every sample carries one unit of energy
xy = np.array([[10.0, 10.0], [10.0, 50.0], [60.0, 50.0]])
pts, w = m.beam_points(xy)
check('beam_points: the weights add up to the number of pieces (one unit of energy per sample)', abs(w.sum() - 2.0) < 1e-9, w.sum())
first = pts[:50]
check('beam_points: the bits of the first piece lie on it, less than a pixel apart', bool(np.all(first[:, 0] == 10.0)) and first[:, 1].min() > 10.0 and first[:, 1].max() < 50.0 and np.diff(first[:, 1]).max() < 0.85, (first[0], first[-1]))
check('beam_points: the bits of the second piece lie on the second', bool(np.all(pts[-60:, 1] == 50.0)) and pts[-1, 0] < 60.0, pts[-1].tolist())
rng = np.random.default_rng(3)
noisy = rng.uniform(0, 275, size=(1600, 2))
pn, wn = m.beam_points(noisy)
check('beam_points: a noisy signal does not blow up the number of points', len(pn) <= 130000 and abs(wn.sum() - 1599) < 5, (len(pn), wn.sum()))
check('beam_points: standing still still counts (a piece of no length carries its energy on one point)', abs(m.beam_points(np.zeros((5, 2)))[1].sum() - 4.0) < 1e-9)

# ---- slow is bright, fast is dim
S = 276
b = m.BeamScreen(S)
slow_u = np.linspace(-0.8, 0.8, 400)  # 400 samples over about 210 pixels
fast_u = np.linspace(-0.8, 0.8, 40)   # 40 samples over the same distance
b.add(slow_u, np.full(400, 0.5), 0.0)
b.add(fast_u, np.full(40, -0.5), 0.0)
h = (S - 1) / 2.0
row_slow, row_fast = int(round(h * (1 - 0.96 * 0.5))), int(round(h * (1 + 0.96 * 0.5)))
e_slow, e_fast = b.buf[row_slow - 1:row_slow + 2].sum(), b.buf[row_fast - 1:row_fast + 2].sum()
check('a slow beam is brighter than a fast one: ten times the samples over the same line, ten times the energy', 8.0 < e_slow / e_fast < 12.0, (e_slow, e_fast))
check('all the energy of the samples is in the picture (nothing lost, nothing made)', abs(b.buf.sum() - (399 + 39)) < 2.0, b.buf.sum())

# ---- persistence
b = m.BeamScreen(100)
b.add(np.linspace(-0.3, 0.3, 50), np.zeros(50), 0.0)
e0 = float(b.buf.sum())
b.add([0.0], [0.0], 0.05)  # no new samples: the picture only fades
check('persistence: the screen fades by exp(-dt / tau)', abs(b.buf.sum() / e0 - np.exp(-0.05 / m.BeamScreen.TAU)) < 1e-4, (b.buf.sum() / e0, np.exp(-0.05 / m.BeamScreen.TAU)))
b.clear()
check('clear empties the screen', b.buf.max() == 0.0)

# ---- points off the screen are dropped, not wrapped round
b = m.BeamScreen(100)
b.add(np.array([5.0, -5.0, 5.0, 0.0]), np.array([5.0, 5.0, -5.0, 0.0]), 0.0)
check('points far off the screen do not crash or wrap round', np.isfinite(b.buf).all() and b.buf.shape == (100, 100))

# ---- the picture
th = m.THEMES[0]
lut = m.beam_palette(th.bg, th.vec)
bg = tuple(int(th.bg[i:i + 2], 16) for i in (1, 3, 5))
check('the palette starts at the background colour and ends white-hot', lut.shape == (256, 3) and lut.dtype == np.uint8 and tuple(int(v) for v in lut[0]) == bg and int(lut[255].min()) > 190, (lut[0], lut[255]))
b = m.BeamScreen(S)
for k in range(10):
    b.add(np.linspace(-0.6, 0.6, 300), np.zeros(300), 1 / 30.0)  # a horizontal line through the middle
img = b.render(lut)
px = np.asarray(img).astype(int)
check('the picture is RGB at the screen size, background in the corners', img.size == (S, S) and img.mode == 'RGB' and tuple(px[0, 0]) == bg, (img.size, img.mode, tuple(px[0, 0])))
mid, col = S // 2, S // 2
core, near, far = int(px[mid, col].sum()), int(px[mid - 5, col].sum()), int(px[mid - 40, col].sum())
check('the beam is bright, with a glow around it that fades with distance and is gone far away', core > 450 and core > near > far + 15 and far == sum(bg), (core, near, far, sum(bg)))

# ---- the other graphs: a background picture and a two-channel plot over it
th = [t for t in m.THEMES if t.name == 'Orange + blue'][0]
rgb = lambda c: tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
tint = '#202830'
base = m.plot_base(100, 50, th.bg, th.grid, th.peak, rows=[0, 25, 49], cols=[30], bands=[(10, 20)], tint=tint)
check('plot_base: background, tinted band, vertical line, horizontal lines (the first in the peak colour) and a frame',
      base.shape == (50, 100, 3) and base.dtype == np.uint8 and tuple(base[40, 60]) == rgb(th.bg) and tuple(base[40, 15]) == rgb(tint) and tuple(base[40, 30]) == rgb(th.grid)
      and tuple(base[25, 60]) == rgb(th.grid) and tuple(base[0, 60]) == rgb(th.peak) and tuple(base[40, 0]) == rgb(th.grid), (tuple(base[0, 60]), tuple(base[40, 15])))
pl = m.BeamPlot(base, th.bg, (th.left, th.right), 0.03, 1.3, 0.5)
xs = np.linspace(5, 95, 200)
pl.add(0, xs, np.full(200, 12.0), 0.0)
pl.add(1, xs, np.full(200, 38.0), 0.0)
img = np.asarray(pl.image()).astype(int)
left_px, right_px, far_px = img[12, 50], img[38, 50], img[45, 50]
check('BeamPlot: the picture has the size of the graph', pl.image().size == (100, 50) and pl.f == 1.0)
lc_, rc_ = np.array(rgb(th.left)), np.array(rgb(th.right))
check('BeamPlot: the left channel lights its line in the left colour, the right channel in the right colour', float((left_px - right_px) @ (lc_ - rc_)) > 10000, (left_px.tolist(), right_px.tolist(), lc_.tolist(), rc_.tolist()))
check('BeamPlot: the lines are far brighter than the background, and a few pixels away only a faint glow is left', left_px.sum() > base[12, 50].sum() + 150 and far_px.sum() <= base[45, 50].astype(int).sum() + 30, (left_px.sum(), far_px.tolist()))
wide = m.BeamPlot(m.plot_base(1500, 300, th.bg, th.grid), th.bg, (th.left, th.right), 0.03, 1.3)
wide.add(0, np.linspace(0, 1499, 400), np.full(400, 150.0), 0.0)
check('BeamPlot: a very wide graph is drawn smaller and enlarged, still to its own size', wide.f < 1.0 and wide.screens[0].w < 1500 and wide.image().size == (1500, 300), (wide.f, wide.screens[0].w))

# ---- the worker: the graph is drawn on a thread of its own
import threading
import time

wk = m.BeamWorker(m.BeamPlot(base, th.bg, (th.left, th.right), 0.03, 1.3, 0.5), threaded=True)
check('BeamWorker: nothing is drawn before the first job', wk.take() is None and wk.thread.is_alive())
for k in range(20):  # twenty frames handed over at once: they are all applied, in order, and drawn as one picture
    wk.add(lambda p, k=k: p.add(0, xs, np.full(200, 5.0 + k), 0.0))
img = None
t0 = time.time()
while img is None and time.time() - t0 < 5.0:
    img = wk.take()
    time.sleep(0.01)
time.sleep(0.2)
check('BeamWorker: a finished picture is handed over, with the size of the graph', img is not None and img.size == (100, 50), None if img is None else img.size)
rows_lit = np.flatnonzero(wk.plot.screens[0].buf.sum(axis=1) > 0)
check('BeamWorker: every job was applied (the twenty lines are all in the screen)', rows_lit.min() <= 5 and rows_lit.max() >= 24, (rows_lit.min(), rows_lit.max()))
check('BeamWorker: take() gives each picture only once', wk.take() is None or wk.seq > wk.taken - 1)
wk.add(lambda p: 1 / 0)
t0 = time.time()
while wk.error is None and time.time() - t0 < 5.0:
    time.sleep(0.01)
check('BeamWorker: an error in a job is kept for the window to report, and the thread lives on', wk.error is not None and 'ZeroDivisionError' in wk.error and wk.thread.is_alive())
wk.stop()
wk.thread.join(5.0)
check('BeamWorker: stop() ends the thread', not wk.thread.is_alive())
sync = m.BeamWorker(m.BeamPlot(base, th.bg, (th.left, th.right), 0.03, 1.3, 0.5), threaded=False)
sync.add(lambda p: p.add(1, xs, np.full(200, 20.0), 0.0))
check('BeamWorker without a thread: the job is run and the picture is ready at once', sync.thread is None and sync.take() is not None and sync.take() is None)
vec = m.BeamVector(120, 100, m.beam_palette(th.bg, th.vec))
vec.screen.add(np.linspace(-0.5, 0.5, 50), np.zeros(50), 0.0)
check('BeamVector: the picture is as wide as the side asked for', vec.image().size == (100, 100))

# ---- where the two channels overlap: 'add' burns out to white, 'max' keeps each colour
bl_add = m.BeamPlot(m.plot_base(100, 50, th.bg, th.grid), th.bg, (th.left, th.right), 0.03, 0.15)
bl_max = m.BeamPlot(m.plot_base(100, 50, th.bg, th.grid), th.bg, (th.left, th.right), 0.03, 0.15, blend='max')
for b_ in (bl_add, bl_max):
    for ch in (0, 1):
        b_.add(ch, np.linspace(5, 95, 200), np.full(200, 25.0), 0.0)
p_add, p_max = np.asarray(bl_add.image())[25, 50].astype(int), np.asarray(bl_max.image())[25, 50].astype(int)
check('blend: added light on top of each other is whiter than the brighter of the two', p_add.sum() > p_max.sum() + 40, (p_add.tolist(), p_max.tolist()))
bl_white = m.BeamPlot(m.plot_base(100, 50, th.bg, th.grid), th.bg, (th.left, th.right), 0.03, 0.15, blend='white')
bl_max2 = m.BeamPlot(m.plot_base(100, 50, th.bg, th.grid), th.bg, (th.left, th.right), 0.03, 0.15, blend='max')
for b_ in (bl_white, bl_max2):
    for ch in (0, 1):
        b_.add(ch, np.linspace(5, 95, 200), np.full(200, 25.0), 0.0)  # both channels on one line
    b_.add(0, np.linspace(5, 95, 200), np.full(200, 8.0), 0.0)  # and each alone on a line of its own
    b_.add(1, np.linspace(5, 95, 200), np.full(200, 42.0), 0.0)
iw, im2 = np.asarray(bl_white.image()).astype(int), np.asarray(bl_max2.image()).astype(int)
check('blend white: where both channels are lit the line is much whiter than with max (no colour cast left)', iw[25, 50].min() > im2[25, 50].min() + 25 and iw[25, 50].min() > 0.75 * iw[25, 50].max(), (iw[25, 50].tolist(), im2[25, 50].tolist()))
check('blend white: a channel on its own keeps its colour exactly as with max', iw[8, 50].tolist() == im2[8, 50].tolist() and iw[42, 50].tolist() == im2[42, 50].tolist() and abs(iw[8, 50][0] - iw[8, 50][2]) > 40, (iw[8, 50].tolist(), im2[8, 50].tolist(), iw[42, 50].tolist()))
T.finish()
