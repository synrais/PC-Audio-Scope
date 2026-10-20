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

# ---- only the rows that have light are worked out and put on screen
def lined(pl, rng, n=6):
    for _ in range(n):
        for ch in range(2):
            pl.add(ch, np.linspace(0, pl.w - 1, 140), pl.h * (0.3 + 0.4 * rng.random(140)), 0.033)


for (bw, bh) in ((100, 50), (1500, 300), (605, 277)):
    rng_ = np.random.default_rng(bw)
    base_ = np.full((bh, bw, 3), rgb(th.bg), np.uint8)
    base_[bh // 2, :] = rgb(th.grid)
    pl_ = m.BeamPlot(base_.copy(), th.bg, (th.left, th.right), 0.04, 3.2, 0.25, 64, 1.0, 'add')
    lined(pl_, rng_)
    full_ = np.asarray(pl_.image()).astype(int)
    ar_ = pl_.active_rows()
    worst = 0
    for y0_, y1_ in ((0, bh), (bh // 5, bh // 2), (ar_[0], ar_[1]), (bh // 2, bh - 1)):
        if y1_ > y0_:
            worst = max(worst, int(np.abs(np.asarray(pl_.image_rows(y0_, y1_)).astype(int) - full_[y0_:y1_]).max()))
    check('image_rows: any rows of the picture made alone are the same rows of the whole picture (%dx%d, to within a level)' % (bw, bh), worst <= 2, worst)
    outside_ = np.concatenate([full_[:ar_[0]], full_[ar_[1]:]])
    check('active_rows: every row outside them is exactly the background (%dx%d), and the rows with light are inside them' % (bw, bh), bool((outside_ == np.concatenate([base_[:ar_[0]], base_[ar_[1]:]]).astype(int)).all()) and 0 < ar_[1] - ar_[0] < bh + 1, ar_)
quiet_ = m.BeamPlot(np.full((50, 100, 3), rgb(th.bg), np.uint8), th.bg, (th.left, th.right), 0.04, 3.2)
check('active_rows: a picture without light has no rows with light', quiet_.active_rows() == (0, 0), quiet_.active_rows())

# a banded worker hands over the rows that differ from the background; shown on top of the background (as the window does, skipping some pictures when it is slow) they always give the whole picture
for (bw, bh) in ((120, 60), (1500, 300)):
    rng_ = np.random.default_rng(bw + 1)
    base_ = np.full((bh, bw, 3), rgb(th.bg), np.uint8)
    pl_ = m.BeamPlot(base_.copy(), th.bg, (th.left, th.right), 0.03, 3.2, 0.25, 64, 1.0, 'add')
    wkb = m.BeamWorker(pl_, threaded=False, banded=True)
    bad = 0
    bands_seen = []
    shown_ = base_.astype(int).copy()
    for step in range(60):
        ysb = bh * (0.3 + 0.4 * rng_.random())
        xs_b = np.linspace(0, bw - 1, 60)
        wkb.add(lambda pl, ysb=ysb, xs_b=xs_b, rng_=rng_: [pl.add(ch, xs_b, ysb + 0.05 * bh * np.sin(xs_b * (0.05 + 0.1 * ch)) + rng_.random(60) * 3, 0.033) for ch in range(2)])
        if rng_.random() < 0.55:  # the window comes for a picture (not after every one)
            img_ = wkb.take()
            if wkb.fresh:
                bd_ = wkb.last_band
                bands_seen.append(bd_)
                shown_ = base_.astype(int).copy()  # the background, and on top of it the rows with light
                if img_ is not None:
                    shown_[bd_[0]:bd_[1]] = np.asarray(img_).astype(int)
                bad = max(bad, int(np.abs(shown_ - np.asarray(pl_.image()).astype(int)).max()))
    check('banded BeamWorker (%dx%d): the rows with light shown over the background, some pictures skipped, always give the whole picture (to within a level)' % (bw, bh), bad <= 2 and any(b_ != (0, bh) for b_ in bands_seen), (bad, bands_seen[:4]))
    check('banded BeamWorker (%dx%d): a band is only the rows that differ from the background, and fresh says when there is a new picture' % (bw, bh), all(b_[1] - b_[0] < bh for b_ in bands_seen) and (wkb.take(), wkb.take() is None and wkb.fresh is False)[1], bands_seen[:3])
ordered_ = m.pool_map(lambda v_: v_ * v_, list(range(12)))
check('pool_map: the results come back in order', ordered_ == [v_ * v_ for v_ in range(12)], ordered_)

# ---- line strength: the weak end of the beam's brightness raised, the glow and the bright end as they were
lt_ = np.array(m._lift_table(0.7))
check('_lift_table: 0 stays 0, 255 stays 255, it only goes up, in order', lt_[0] == 0 and lt_[255] == 255 and bool((lt_ >= np.arange(256)).all()) and bool((np.diff(lt_) >= 0).all()) and lt_[20] > 35, (lt_[:3].tolist(), lt_[20], lt_[255]))
check('_lift_table: a lift of 1 changes nothing', m._lift_table(1.0) == list(range(256)))
for lift_ in (0.75, 0.6):
    pair_ = []
    for l_ in (1.0, lift_):
        sc_ = m.BeamScreen(120, 80, 0.05, 3.2)
        sc_.lift = l_
        sc_.buf[40, 20:100] = 0.02  # a weak line
        sc_.buf[20, 20:100] = 5.0  # a strong one
        pair_.append(np.asarray(sc_.render(m.beam_palette('#07090d', '#ff8a1f'), 1.0)).astype(int))
    plain_, bold_ = pair_
    check('line strength (%.2f): the picture is never darker, the weak line is clearly brighter, the strong one and the empty parts are as they were' % lift_,
          bool((bold_ >= plain_).all()) and bold_[40, 60].sum() > 1.2 * plain_[40, 60].sum() and bold_[20, 60].tolist() == plain_[20, 60].tolist() and bold_[75, 5].tolist() == plain_[75, 5].tolist(),
          (plain_[40, 60].tolist(), bold_[40, 60].tolist(), plain_[20, 60].tolist(), bold_[20, 60].tolist()))
pl_b = m.BeamPlot(np.full((60, 200, 3), (7, 9, 13), np.uint8), '#07090d', ('#2fb5ff', '#ff8a1f'), 0.04, 3.2, 0.25, 64, 0.35, 'add')
for sc_ in pl_b.screens:
    sc_.lift = 0.7
pl_b.add(0, np.linspace(0, 199, 80), 30 + 10 * np.sin(np.linspace(0, 9, 80)), 0.033)
whole_ = np.asarray(pl_b.image()).astype(int)
ar_ = pl_b.active_rows()
rows_ = np.asarray(pl_b.image_rows(ar_[0], ar_[1])).astype(int)
check('line strength: the rows worked out alone are the same rows of the whole picture, and no row outside the active ones has any light', int(np.abs(rows_ - whole_[ar_[0]:ar_[1]]).max()) <= 2 and bool((np.concatenate([whole_[:ar_[0]], whole_[ar_[1]:]]) == np.array([7, 9, 13])).all()), ar_)
# ---- glow: a third glow, very broad and faint, made in floating point
lut_w = m.beam_palette('#07090d', '#ff8a1f')


def wide_pic(wide, glow=0.4):
    sc_ = m.BeamScreen(300, 200, 0.05, 3.2)
    sc_.buf[100, 60:240] = 3.0  # a bright line across the middle
    sc_.wide = wide
    return np.asarray(sc_.render(lut_w, glow)).astype(int).sum(axis=2)


w0_, w4_, w8_ = wide_pic(0.0), wide_pic(8.0), wide_pic(16.0)
check('glow: with it on, light reaches far from a bright line (30 px away is dark without it), more with more gain, and it never darkens anything',
      w0_[70, 150] <= 29 + 1 and w4_[70, 150] > w0_[70, 150] + 3 and w8_[70, 150] > w4_[70, 150] + 3 and bool((w4_ >= w0_).all()) and bool((w8_ >= w4_).all()), (w0_[70, 150], w4_[70, 150], w8_[70, 150]))
col_ = wide_pic(16.0, glow=0.0)[10:68, 150].astype(int)  # (without the narrow glow: just the wide one, from far away up to 32 px from the line)
check('glow: the glow fades smoothly with the distance from the line (a step of at most a level in each colour, no blocks), brighter toward the line',
      bool((np.abs(np.diff(col_)) <= 4).all()) and bool((np.diff(col_) >= -1).all()) and col_[-1] > col_[0] + 3, (col_[::10].tolist(),))
check('glow does not depend on the narrow glow: with the narrow glow at 0 it still shines', wide_pic(8.0, glow=0.0)[70, 150] > wide_pic(0.0, glow=0.0)[70, 150] + 3, (wide_pic(8.0, glow=0.0)[70, 150], wide_pic(0.0, glow=0.0)[70, 150]))
imp_s = np.zeros((20, 20), np.float32)
imp_s[10, 10] = 100.0
bs_ = m._blur_small(imp_s, 2.0)
check('_blur_small: a Gaussian that keeps the light (to a percent, nothing is lost near the middle), is symmetric and falls off from the middle', abs(float(bs_.sum()) - 100.0) < 1.0 and np.allclose(bs_, bs_.T, atol=1e-5) and bs_[10, 10] > bs_[10, 12] > bs_[10, 15], (bs_.sum(), bs_[10, 10]))
pw_b = m.BeamPlot(np.full((260, 400, 3), (7, 9, 13), np.uint8), '#07090d', ('#2fb5ff', '#ff8a1f'), 0.04, 3.2, 0.25, 64, 0.4, 'add')
r0_ = pw_b._reach()
for sc_ in pw_b.screens:
    sc_.wide = 4.0
check('glow: the glow of a lit row reaches three times as far, so the rows worked out alone include it', pw_b._reach() > 2.5 * r0_, (r0_, pw_b._reach()))
pw_b.add(0, np.linspace(10, 390, 90), 120 + 25 * np.sin(np.linspace(0, 8, 90)), 0.033)
wh_ = np.asarray(pw_b.image()).astype(int)
arw_ = pw_b.active_rows()
rw_ = np.asarray(pw_b.image_rows(arw_[0], arw_[1])).astype(int)
check('glow: the rows worked out alone are the same rows of the whole picture, and the rows outside them are the background', int(np.abs(rw_ - wh_[arw_[0]:arw_[1]]).max()) <= 3 and int(np.abs(np.concatenate([wh_[:arw_[0]], wh_[arw_[1]:]]) - np.array([7, 9, 13])).max()) <= 1, arw_)

T.finish()
