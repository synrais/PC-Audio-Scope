"""Scope rate: the capture can run at 96 or 192 kHz, the 48 kHz stream is made from it, and the oscilloscope and the vectorscope draw from the fast one (a circle above 24 kHz is a circle, not a hot spot)"""
import json
import os
import tkinter as tk

import numpy as np

import support as T
from support import check, m, pump, SR, BLOCK

tmp = T.sandbox()

# ---- the decimator: the same answer whatever the blocks, a tone passes, a tone above 24 kHz does not, the delay is what it says
for k in (2, 4):
    rate = SR * k
    n = int(rate * 0.5)
    t = np.arange(n) / rate
    x = np.stack([0.5 * np.sin(2 * np.pi * 5000 * t), 0.5 * np.sin(2 * np.pi * 30000 * t) if k == 4 else 0.5 * np.sin(2 * np.pi * 26000 * t)], axis=1).astype(np.float32)
    whole = m.StreamDecimator(k, rate).process(x)
    d = m.StreamDecimator(k, rate)
    parts = np.concatenate([d.process(x[i:i + BLOCK * k]) for i in range(0, n, BLOCK * k)])
    check('the decimator at %d kHz: blocks of 10 ms give the same stream as the whole signal in one go' % (rate // 1000), whole.shape == parts.shape and float(np.abs(whole - parts).max()) < 1e-5, float(np.abs(whole - parts).max()))
    tail = slice(len(whole) // 2, None)
    a5 = float(np.abs(whole[tail, 0]).max())
    a30 = float(np.abs(whole[tail, 1]).max())
    check('the decimator at %d kHz: a 5 kHz tone passes at full size (%.3f of 0.5) and a tone above 24 kHz is 60 dB down (%.5f)' % (rate // 1000, a5, a30), 0.49 < a5 < 0.51 and a30 < 0.5 * 0.001, (a5, a30))
    p = 5 * BLOCK * k + 7 * k  # an impulse at a multiple of k
    imp = np.zeros((10 * BLOCK * k, 2), np.float32)
    imp[p, 0] = 1.0
    dd = m.StreamDecimator(k, rate)
    out = dd.process(imp)
    j = int(np.argmax(np.abs(out[:, 0])))
    check('the decimator at %d kHz: its delay is what it says (the output sample j is the input at j * k - delay)' % (rate // 1000), abs(j * k - dd.delay - p) <= k, (j, j * k - dd.delay, p, dd.delay))

# ---- the capture's fast ring: the same stretch of time as the 48 kHz window, k times as many frames
K = 4
rate = SR * K
cap = m.Capture()
dec = m.StreamDecimator(K, rate)
cap.hk, cap.hdelay, cap.hring, cap.hpos = K, dec.delay, np.zeros((rate * 2, 2), np.float32), 0
total = int(2.6 * 100)  # 2.6 s of 10 ms blocks: the rings wrap
tt = np.arange(total * BLOCK * K) / rate
sig = np.stack([0.4 * np.sin(2 * np.pi * 3000 * tt), 0.3 * np.sin(2 * np.pi * 33000 * tt)], axis=1).astype(np.float32)  # 3 kHz and a 33 kHz tone (which the 48 kHz stream cannot carry)
for i in range(total):
    hi = sig[i * BLOCK * K:(i + 1) * BLOCK * K]
    cap.push(dec.process(hi), hi)
check('the capture counts both streams: pos in 48 kHz frames, hpos k times as many', cap.pos == total * BLOCK and cap.hpos == total * BLOCK * K, (cap.pos, cap.hpos))
w48 = cap.window(cap.pos, 960)
wh, k_ = cap.hi_window(cap.pos, 960)
check('hi_window gives k times the frames of the same stretch and says k', k_ == K and wh.shape == (960 * K, 2), (k_, wh.shape))
a = (cap.pos - 960) * K - dec.delay
check('hi_window is the fast stream as it was written (also after the ring has wrapped), shifted by the delay of the filter', float(np.abs(wh - sig[a:a + 960 * K]).max()) < 1e-6, float(np.abs(wh - sig[a:a + 960 * K]).max()))
check('the 33 kHz tone is in the fast stream (0.3) and not in the 48 kHz one (below 0.0005)', 0.29 < float(np.abs(wh[:, 1]).max()) < 0.31 and float(np.abs(w48[:, 1]).max()) < 0.0005, (float(np.abs(wh[:, 1]).max()), float(np.abs(w48[:, 1]).max())))
cap1 = m.Capture()
cap1.push(np.ones((BLOCK, 2), np.float32) * 0.25)
w1, k1 = cap1.hi_window(cap1.pos, 100)
check('at 48 kHz hi_window is just the window (k = 1)', k1 == 1 and w1.shape == (100, 2) and float(np.abs(w1 - cap1.window(cap1.pos, 100)).max()) == 0.0)
cap1.set_hi_rate(96000)
cap1.set_hi_rate(12345)
check('set_hi_rate takes the rates of the list and falls back to 48 kHz for anything else', cap1.hi_rate == SR)
cap1.set_hi_rate(0)
check('0 is Auto', cap1.hi_rate == 0)
check('auto_scope_rate picks the highest of 48 / 96 / 192 kHz that the output carries (44.1 and unknown give 48)', [m.auto_scope_rate(r_) for r_ in (192000, 176400, 96000, 88200, 48000, 44100, None)] == [192000, 192000, 96000, 96000, 48000, 48000, 48000])
for mix_, want_ in ((192000, 192000), (96000, 96000), (48000, 48000), (None, 48000)):
    cap1.mix_rate = mix_
    cap1.set_hi_rate(0)
    got_ = cap1.chosen_rate()
    check('Auto on an output mixed at %s Hz reads at %d Hz' % (mix_, want_), got_ == want_, got_)
cap1.mix_rate = 48000
cap1.set_hi_rate(192000)
check('a rate that was asked for stays, whatever the output is mixed at (the status line then says what arrives)', cap1.chosen_rate() == 192000)

# ---- the picture: a circle at 33 kHz (a ball of Jerobeam Fenderson) is a circle at 192 kHz and a hot spot at 48 kHz; the brightness stays the same
S = 276
nseg = 4 * BLOCK * K // 4  # a few thousand samples
ts = np.arange(nseg * K) / rate
cu, cv = 0.7 * np.cos(2 * np.pi * 33000 * ts), 0.7 * np.sin(2 * np.pi * 33000 * ts)
hi_screen = m.BeamScreen(S)
hi_screen.add(cu, cv, 0.0, 1.0 / K)
lo = dec.process(np.stack([cu, cv], axis=1).astype(np.float32))
lo_screen = m.BeamScreen(S)
lo_screen.add(lo[:, 0], lo[:, 1], 0.0)
def radius_spread(buf):
    """how much of the light lies within 6 % of the (weighted median) radius from the middle: 1.0 is a perfect circle"""
    h_, w_ = buf.shape
    yy, xx = np.mgrid[0:h_, 0:w_]
    r = np.hypot(xx - (w_ - 1) / 2.0, yy - (h_ - 1) / 2.0)
    wt = buf.ravel().astype(np.float64)
    order = np.argsort(r.ravel())
    cum = np.cumsum(wt[order])
    rm = float(r.ravel()[order][np.searchsorted(cum, cum[-1] / 2.0)]) if cum[-1] > 0 else 0.0
    near = (np.abs(r - rm) < 0.06 * max(rm, 1.0))
    return float(buf[near].sum() / max(buf.sum(), 1e-9)), rm


up_x = np.sin(2 * np.pi * 33000 * np.arange(400) / rate)
up_y = m.sinc_upsample(up_x, 4)
want = np.sin(2 * np.pi * 33000 * np.arange(1600) / (rate * 4))
check('sinc_upsample: the points between the samples lie on the sine (33 kHz at 192 kHz, 5.8 samples a turn), away from the ends', len(up_y) == 1600 and float(np.abs(up_y[200:1400] - want[200:1400]).max()) < 0.004, float(np.abs(up_y[200:1400] - want[200:1400]).max()))
check('sinc_upsample: every fourth point is the sample itself', float(np.abs(up_y[0::4][50:350] - up_x[50:350]).max()) < 1e-3, float(np.abs(up_y[0::4][50:350] - up_x[50:350]).max()))
tone = np.arange(nseg * K) / rate
tu, tv = 0.6 * np.cos(2 * np.pi * 1000 * tone), 0.6 * np.sin(2 * np.pi * 1000 * tone)
b_hi, b_lo = m.BeamScreen(S), m.BeamScreen(S)
b_hi.add(tu, tv, 0.0, 1.0 / K)
tl = dec.process(np.stack([tu, tv], axis=1).astype(np.float32))
b_lo.add(tl[:, 0], tl[:, 1], 0.0)
ratio = float(b_hi.buf.sum() / b_lo.buf.sum())
check('with the energy shared out (1 / k a sample) the fast picture is as bright as the 48 kHz one: %.2f' % ratio, 0.8 < ratio < 1.25, ratio)

# ---- the app: the setting, the menu rows, the drawing
cap2 = T.SynthCapture()
cap2.start()
root = tk.Tk()
root.withdraw()
app = m.App(root, cap2)
check('the scope rate starts on Auto', app.cap.hi_rate == 0)
rows = {n_: [e_['label'] for e_ in app.panel_menu_build(n_).entries if e_['kind'] == 'stepper'] for n_ in m.PANELS}
check('the oscilloscope and the vectorscope have a Scope rate row, no other window has', all('Scope rate' in rows[n_] for n_ in ('osc', 'vec')) and not any('Scope rate' in rows[n_] for n_ in ('spec', 'hist', 'met')), rows)
menu = app.panel_menu_build('osc')
e = [e_ for e_ in menu.entries if e_.get('label') == 'Scope rate'][0]
check('the row shows Auto / 48 / 96 / 192 kHz and starts on Auto', [e['text'](i) for i in range(e['n_max'] + 1)] == ['Auto', '48 kHz', '96 kHz', '192 kHz'] and e['n'] == 0, [e['text'](i) for i in range(e['n_max'] + 1)])
e['change'](3)
check('choosing 192 kHz sets the capture and saves it', app.cap.hi_rate == 192000 and json.load(open(m.SETTINGS)).get('scope_rate') == 192000, json.load(open(m.SETTINGS)).get('scope_rate'))
check('the menu then shows 192 kHz', [e_ for e_ in app.panel_menu_build('vec').entries if e_.get('label') == 'Scope rate'][0]['n'] == 3)
app.set_scope_rate(2)
check('and 96 kHz', app.cap.hi_rate == 96000)
app.set_scope_rate(1)
check('and 48 kHz', app.cap.hi_rate == SR)
app.set_scope_rate(0)
check('and back to Auto (saved as 0)', app.cap.hi_rate == 0 and json.load(open(m.SETTINGS)).get('scope_rate') == 0)

# a capture that has a fast stream: the picture and the oscilloscope take it (nothing is played; the thread of the stand-in is stopped first)
cap2.stop = True
pump(root, 0.3)
K2 = 4
dec2 = m.StreamDecimator(K2, SR * K2)
cap2.hk, cap2.hdelay, cap2.hring = K2, dec2.delay, np.zeros((SR * K2 * 2, 2), np.float32)
cap2.hpos = cap2.pos * K2
tt2 = np.arange(60 * BLOCK * K2) / (SR * K2)
sig2 = np.stack([0.5 * np.sin(2 * np.pi * 440 * tt2), 0.5 * np.sin(2 * np.pi * 660 * tt2)], axis=1).astype(np.float32)
for i in range(60):
    hi = sig2[i * BLOCK * K2:(i + 1) * BLOCK * K2]
    cap2.push(dec2.process(hi), hi)
app.vec_last = None
app.paused = False
app.draw()
check('the oscilloscope draws k times as many points when the capture has a fast stream (1536 x 4)', len(app.osc_pts[0][0]) == 1536 * K2, len(app.osc_pts[0][0]))
check('and the vectorscope has light on it', float(app.beam.buf.sum()) > 10.0, float(app.beam.buf.sum()))

# the user's case: a 33 kHz circle (a ball of Jerobeam Fenderson, 5.8 samples a turn at 192 kHz) is a round ring on the vectorscope, with the path interpolated; at 48 kHz it is a hot spot
def circle_screen(up_on, rate_k, circle_hz):
    cap_ = m.Capture()
    dec_ = m.StreamDecimator(rate_k, SR * rate_k) if rate_k > 1 else None
    cap_.hk, cap_.hdelay, cap_.hring, cap_.hpos = rate_k, (dec_.delay if dec_ else 0), (np.zeros((SR * rate_k * 2, 2), np.float32) if rate_k > 1 else None), 0
    tt_ = np.arange(60 * BLOCK * rate_k) / (SR * rate_k)
    sg_ = np.stack([0.7 * np.cos(2 * np.pi * circle_hz * tt_), 0.7 * np.sin(2 * np.pi * circle_hz * tt_)], axis=1).astype(np.float32)
    for i in range(60):
        hi = sg_[i * BLOCK * rate_k:(i + 1) * BLOCK * rate_k]
        cap_.push(dec_.process(hi) if dec_ else hi, hi if dec_ else None)
    old = m.SCOPE_SMOOTH
    m.SCOPE_SMOOTH = 4 if up_on else 1
    app.cap = cap_
    app.vec_last, app.gain = None, 1.0
    app.draw()
    m.SCOPE_SMOOTH = old
    return app.beam.buf.copy()


ring_smooth, r_s = radius_spread(circle_screen(True, 4, 33000))
ring_poly, r_p = radius_spread(circle_screen(False, 4, 33000))
check('a 33 kHz circle at 192 kHz with the path interpolated is a round ring (%.0f %% of the light within 6 %% of its radius, radius %.0f px)' % (100 * ring_smooth, r_s), ring_smooth > 0.90 and r_s > 40, (ring_smooth, r_s))
check('without the interpolation the same samples draw a hexagon (%.0f %%): the interpolation is what makes it round' % (100 * ring_poly), ring_poly < ring_smooth - 0.15, (ring_poly, ring_smooth))
# the status line says what rate arrives
cap2.hk, cap2.mix_rate, cap2.hi_rate = K2, None, 192000
app.cap = cap2
app.vec_last = None
app.draw()
txt = app.c.itemcget(app.status, 'text')
check('the status line says the sample rate, and does not say it twice when the Scope rate is the same: Sample rate 192k', '   |   Sample rate 192k   |   ' in txt and 'Scope rate' not in txt, txt)
cap2.mix_rate = 48000
app.draw()
txt = app.c.itemcget(app.status, 'text')
check('when Windows delivers less than the chosen Scope rate the line shows both: Sample rate 48k (Scope rate 192k)', '   |   Sample rate 48k (Scope rate 192k)   |   ' in txt and 'arriving' not in txt, txt)
cap2.hi_rate, cap2.mix_rate = 0, 192000
app.draw()
check('on Auto the status line has only the sample rate: Sample rate 192k (nothing about a Scope rate)', '   |   Sample rate 192k   |   ' in app.c.itemcget(app.status, 'text') and 'Scope rate' not in app.c.itemcget(app.status, 'text'), app.c.itemcget(app.status, 'text'))
cap2.mix_rate, cap2.hk, cap2.hi_rate = 192000, 1, SR
app.draw()
check('with a Scope rate of 48 kHz on an output mixed at 192 kHz the line says Sample rate 192k (Scope rate 48k)', '   |   Sample rate 192k (Scope rate 48k)   |   ' in app.c.itemcget(app.status, 'text'), app.c.itemcget(app.status, 'text'))
cap2.mix_rate, cap2.hi_rate, cap2.hk = 48000, SR, 1
app.draw()
check('a sample rate of 48k with the Scope rate set to 48k says 48k once: Sample rate 48k', '   |   Sample rate 48k   |   ' in app.c.itemcget(app.status, 'text') and 'Scope rate' not in app.c.itemcget(app.status, 'text'), app.c.itemcget(app.status, 'text'))
check('a capture starts without a known mix rate', m.Capture().mix_rate is None)
app.quit() if hasattr(app, 'quit') and False else None
root.destroy()
T.finish()
