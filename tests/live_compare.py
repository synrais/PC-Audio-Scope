"""live comparison, in real time: a recorded clip against a simulated live source that starts 7.3 s into it"""
import glob
import os
import tkinter as tk

import numpy as np

import support as T
from support import check, m, pump, SR

T.sandbox()
clip_a, _ = T.make_synthetic_clips()           # chime 0-5 s, silence, game sound 9-23 s
OFFSET = 7.3                                   # the live sound starts 7.3 s into the clip
cap = T.SynthCapture()
cap.src = (clip_a.data, int(OFFSET * SR))
cap.vol = (-19.0, 0.11, False)
cap.start()
root = tk.Tk()
root.withdraw()
app = m.App(root, cap)
T.mute_keys(root)


def status():
    return app.c.itemcget(app.status, 'text')


pump(root, 0.5)
app.open_loaded(clip_a)
app.compare_live_start(clip_a)
expect = OFFSET + cap.pos / SR                 # where the fake source was when the live recording started
check('live compare started', app.mode == 'compare' and app.cmp.get('live'))
check('PLAY disabled during live compare', str(app.b_play.cget('state')) == 'disabled')
pump(root, 3.0)
check('auto-align has not fired yet (after 3 s)', app.cmp['auto_pending'] is True)
pump(root, 5.0)
check('auto-align fired once by itself', app.cmp['auto_pending'] is False)
check('auto-align found the running point (live 0 = clip %.2f s)' % expect, abs(app.cmp['sb'] - expect) < 0.05, app.cmp['sb'])
check('auto-align score high', (app.cmp['score'] or 0) > 0.9, app.cmp['score'])
pump(root, 5.0)
check('no drawing error', 'error' not in status().lower(), status()[:80])
check('stats being collected', app.cmp['stats'] is not None)
if app.cmp['stats'] is not None:
    sim = app.cmp['stats']['sim']
    ok = ~np.isnan(sim)
    check('live sound matches the recording', ok.any() and float(np.nanmedian(sim[ok])) > 0.9, (int(ok.sum()), float(np.nanmedian(sim[ok])) if ok.any() else None))
rep = app.live_report()
check('live report text', 'match' in rep and 'running point' in rep, rep.splitlines()[1])

running_point = app.head_t() - app.cmp['sa']
check('running point is where the live sound is in the clip', abs(running_point - (OFFSET + app.cap.pos / SR)) < 0.1, running_point)
before = app.cmp['sb']
app.seek_t(app.head_t() + 2.0)
check('moving the running point changes the alignment', abs(app.cmp['sb'] - (before + 2.0)) < 0.05, app.cmp['sb'])
app.nudge(-0.5)
check('nudge works in live compare', abs(app.cmp['sb'] - (before + 1.5)) < 0.01, app.cmp['sb'])
app.cmp['active'] = 'A'
app.v_active.set('A')
pump(root, 0.5)
check('showing the recorded clip at the running point: no error', 'error' not in status().lower(), status()[:80])
app.v_active.set('B')
app.cmp_activate()
pump(root, 3.0)
app.cmp_auto()
check('pressing Auto-align fires it again and corrects the position', abs(app.cmp['sb'] - expect) < 0.05, app.cmp['sb'])
pump(root, 4.0)

sb = app.cmp['sb']
app.cmp_close()
check('stop live opens an ordinary comparison', app.mode == 'compare' and not app.cmp.get('live'))
check('live session saved', len(glob.glob(os.path.join(m.REC_DIR, 'live_*.wav'))) == 1)
check('alignment carried over', abs(app.cmp['sb'] - sb) < 1e-6, (app.cmp['sb'], sb))
for _ in range(100):
    pump(root, 0.1)
    if app.cmp['stats'] is not None:
        break
check('ordinary comparison computed', app.cmp['stats'] is not None and 'error' not in status().lower())
cap.stop = True
root.destroy()
T.finish()
