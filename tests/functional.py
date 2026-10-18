"""drives the whole app in a hidden window with a synthetic input: live view, recording, review, selection, loop, export, comparing, input menu, scaling, settings"""
import json
import os
import tkinter as tk

import numpy as np

import support as T
from support import check, m, pump, SR

tmp = T.sandbox()
cap = T.SynthCapture()
cap.start()
root = tk.Tk()
root.withdraw()
app = m.App(root, cap)

# ---- every documented key is bound
keys = ['<space>', '<F5>', '<plus>', '<minus>', 'a', 'c', 'r', 'l', '<Control-o>', 'g', 'f', 'm', '<Delete>', '<Prior>', '<Next>', 'i', 'o', 'x', 'p', 'e', '1', '2', '3',
        '<Left>', '<Right>', '<Shift-Left>', '<Alt-Left>', '<Alt-Shift-Left>', '<Alt-Control-Left>', '<Home>', '<End>', 'q', '<Escape>']
check('all documented keys are bound', all(root.bind(k) for k in keys), [k for k in keys if not root.bind(k)])
T.mute_keys(root)


def status():
    return app.c.itemcget(app.status, 'text')


def no_error(tag):
    s = status()
    check(tag + ': no drawing error', 'error' not in s.lower(), s[:90])


# ---- live view
pump(root, 1.0)
no_error('live')
txt = app.c.itemcget(app.m_txt, 'text')
check('live: LUFS line present', 'LUFS' in txt, txt.splitlines()[-1])
check('live: correlation label present', 'correlation' in app.c.itemcget(app.cor_lbl, 'text'), app.c.itemcget(app.cor_lbl, 'text'))
check('live: loudness line reads short-term / integrated', 'short-term' in txt and 'integrated' in txt, txt.splitlines()[-1])
check('clip row hidden while live', app.clip_row.winfo_manager() == '' and app.cmp_row.winfo_manager() == '', (app.clip_row.winfo_manager(), app.cmp_row.winfo_manager()))

# ---- input menu
app.fill_src_menu()
check('input menu lists the default output first', app.src_menu.index('end') is not None and 'Default output' in app.src_menu.entrycget(0, 'label'), app.src_menu.entrycget(0, 'label'))
check('input button shows the current input', app.mb_src.cget('text') not in ('', '...'), app.mb_src.cget('text'))
app.pick_source(dict(kind='default', id=None, label='Default output'))
check('picking an input asks the capture for it', app.cap.want == ('default', None))

# ---- toggle buttons
app.b_auto.invoke()
check('Auto gain button toggles', app.auto is False)
app.b_auto.invoke()
check('Auto gain button toggles back', app.auto is True)
comp = app.comp
app.b_comp.invoke()
check('Add back Windows volume button toggles', app.comp is (not comp))
app.b_comp.invoke()
app.b_spec.invoke()
check('Spectrogram button switches the view', app.spec_mode == 'spectrogram')
app.b_spec.invoke()
check('Spectrogram button switches back', app.spec_mode == 'spectrum')
app.zoom(1.25)
check('manual gain turns auto gain off', app.auto is False)
app.auto = True

# ---- live spectrogram
app.set_spec_mode('spectrogram')
pump(root, 1.5)
no_error('live spectrogram')
check('live spectrogram: image drawn', app.sg_photo is not None)
app.set_spec_mode('spectrum')

# ---- record
app.rec_toggle()
pump(root, 0.5)
app.marker_add()
pump(root, 2.5)
app.rec_toggle()
pump(root, 0.5)
check('record: review mode', app.mode == 'review', app.mode)
pump(root, 0.3)
check('clip row shown in review', app.clip_row.winfo_manager() == 'pack', app.clip_row.winfo_manager())
check('record: clip saved to disk', app.clip.path and os.path.exists(app.clip.path), app.clip.path)
check('record: marker kept', len(app.clip.markers) == 1, app.clip.markers)
check('record: sidecar has markers', os.path.exists(os.path.splitext(app.clip.path)[0] + '.json'))
no_error('review')

# ---- selection, loop, markers
app.seek_t(0.5)
app.sel_point(0)
app.seek_t(1.5)
app.sel_point(1)
check('selection set', app.sel and abs(app.sel[1] - app.sel[0] - 1.0) < 0.05, app.sel)
check('selection stats text', 'LUFS' in app.sel_stats_text(), app.sel_stats_text())
app.loop_toggle()
app.sync_player_region()
check('loop region set', app.player.region is not None and app.player.loop, app.player.region)
out = np.zeros((1024, 2), np.float32)           # the player callback, without audio hardware
app.player.pos = app.player.region[1] - 100
app.player.clip = app.clip
app.player._cb(out, 1024, None, None)
check('loop: wraps inside the selection', app.player.region[0] <= app.player.pos < app.player.region[1], app.player.pos)
app.loop_toggle()
app.marker_add()
app.marker_jump(-1)
no_error('markers')
before = len(app.clip.markers)
app.marker_delete()
check('delete removes the nearest marker', len(app.clip.markers) == before - 1, len(app.clip.markers))
app.set_spec_mode('spectrogram')
pump(root, 0.8)
no_error('review spectrogram')
app.set_spec_mode('spectrum')

# ---- export
m.filedialog.asksaveasfilename = lambda **k: os.path.join(tmp, 'export_sel.wav')
app.export()
check('export: selection written', os.path.exists(os.path.join(tmp, 'export_sel.wav')))
x = m.Clip.load(os.path.join(tmp, 'export_sel.wav'))
check('export: length = selection', abs(x.duration - (app.sel[1] - app.sel[0])) < 0.03, x.duration)

# ---- compare two clips
ca, cb = T.make_synthetic_clips()
app.open_loaded(ca)
app.compare_start(ca, cb, auto=True)
check('compare: auto-align found the game offset (B starts -1.9 s)', abs(app.cmp['sb'] - (-1.9)) < 0.01, app.cmp['sb'])
for _ in range(100):
    pump(root, 0.1)
    if app.cmp['stats'] is not None:
        break
check('compare: statistics computed', app.cmp['stats'] is not None)
no_error('compare')
st = app.cmp['stats']
times = st['win_t'] + app.cmp['origin']
sim_game = float(np.nanmean(st['sim'][(times > 11) & (times < 14)]))
check('compare: game part matches at the auto alignment', sim_game > 0.95, sim_game)
check('compare: corrupted stretch flagged', np.nanmin(st['sim'][(times > 14.4) & (times < 16.4)]) < 0.5)
check('compare: level difference about -6 dB', abs(st['level_db'] - (-6.0)) < 1.0, st['level_db'])
rep = app.cmp_report()
check('compare: report text', 'null test' in rep and 'loudness' in rep, rep.splitlines()[0])

# ---- editing the start positions
before = app.cmp['sb']
app.nudge(0.1)
check('nudge moves B', abs(app.cmp['sb'] - (before + 0.1)) < 1e-6, app.cmp['sb'])
app.v_move.set('A')
app.nudge(-0.01)
check('nudge moves A', abs(app.cmp['sa'] - (-0.01)) < 1e-6, app.cmp['sa'])
app.e_sb.delete(0, 'end')
app.e_sb.insert(0, '-1.5')
app.set_start_from_entry('B')
check('typed start for B', abs(app.cmp['sb'] - (-1.5)) < 1e-6, app.cmp['sb'])
app.cmp_reset()
check('reset puts both at 0', app.cmp['sa'] == 0 and app.cmp['sb'] == 0)

# ---- markers on both clips, then align them
app.seek_t(13.0)
app.v_move.set('A')
app.marker_add()
app.v_move.set('B')
app.seek_t(13.0)
app.marker_add()
app.cmp['B'].markers = [{'t': 14.9, 'name': 'M1'}]           # the same event, 1.9 s later in B
app.cmp_align_markers()
check('align markers: B starts 1.9 s earlier', abs(app.cmp['sb'] - (-1.9)) < 0.01, app.cmp['sb'])
for _ in range(100):
    pump(root, 0.1)
    if app.cmp['stats'] is not None and app.cmp['dirty'] is None and not app.cmp_busy:
        break
st = app.cmp['stats']
times = st['win_t'] + app.cmp['origin']
check('after align markers: game matches again', float(np.nanmean(st['sim'][(times > 11) & (times < 14)])) > 0.95)

# ---- listening to A, B, the difference
for which in ('B', 'D', 'A'):
    app.cmp_listen(which)
    pump(root, 0.3)
    no_error('listen ' + which)
check('listen: active virtual clip', app.active_clip() is not None and len(app.active_clip().data) > 0)

# ---- auto-align on a selection (the chime: B starts where A does)
app.sel = (0.5, 4.5)
app.cmp_auto()
check('auto-align on the chime selection: B starts at 0', abs(app.cmp['sb'] - app.cmp['sa']) < 0.01, app.cmp['sb'])
pump(root, 1.5)
app.set_spec_mode('spectrogram')
pump(root, 1.0)
no_error('compare spectrogram')
app.set_spec_mode('spectrum')

# ---- scaling
app.k = 0.7
app.build_ui()
pump(root, 0.6)
no_error('scale 0.7')
check('rebuilt at another scale and compare row still there', abs(app.k - 0.7) < 1e-6 and app.cmp_row.winfo_manager() == 'pack', app.cmp_row.winfo_manager())
check('fit_k: a smaller window gives a smaller scale', app.fit_k(700, 500) < app.fit_k(1400, 1100), (app.fit_k(700, 500), app.fit_k(1400, 1100)))
check('fit_k: scale is limited by the narrower side', abs(app.fit_k(620, 5000) - app.fit_k(620, 900)) < 0.06, (app.fit_k(620, 5000), app.fit_k(620, 900)))
app.k = 1.0
app.build_ui()
pump(root, 0.4)

# ---- leaving compare, going live
app.cmp_close()
check('close compare: back to review of A', app.mode == 'review' and app.clip is ca)
app.go_live()
check('live again', app.mode == 'live')

# ---- the open dialogs (answered by the test)
exported = os.path.join(tmp, 'export_sel.wav')
m.filedialog.askopenfilename = lambda **k: exported
app.open_clip()
check('Open...: the chosen clip is shown in review', app.mode == 'review' and app.clip.name == 'export_sel.wav', (app.mode, app.clip and app.clip.name))
app.compare_open()
check('Compare...: the chosen clip becomes B of the open clip', app.mode == 'compare' and app.cmp['B'].name == 'export_sel.wav' and app.cmp['A'].name == 'export_sel.wav')
app.cmp_close()
app.compare_live_open()
check('Compare to live...: uses the open clip', app.mode == 'compare' and app.cmp.get('live') and app.cmp['A'].name == 'export_sel.wav')
app.cmp_close()
check('Stop live with almost no sound keeps nothing and shows the clip', app.mode == 'review' and not app.cmp)
app.go_live()
app.compare_live_open()
check('Compare to live... from the live view asks for the clip', app.mode == 'compare' and app.cmp.get('live'))
app.cmp_close()
app.go_live()

# ---- timeline mouse handling
from types import SimpleNamespace as Ev
app.open_loaded(ca)
pump(root, 0.4)
x = app.t2x
app.hist_key = None
check('history: it redraws when asked, then waits for the next pixel', app.refresh_history() is True and app.refresh_history() is False)
app.player.pos = 1500 * m.BLOCK
check('history: it redraws when the playhead moves a pixel or more', app.refresh_history() is True)
app.player.pos = 0
app.tl_press(Ev(x=int(x(5.0)), y=60, state=0))
check('click on the timeline seeks', abs(app.head_t() - 5.0) < 0.1, app.head_t())
app.tl_drag(Ev(x=int(x(8.0)), y=60, state=0))
check('dragging on the timeline seeks', abs(app.head_t() - 8.0) < 0.1, app.head_t())
app.tl_release(Ev(x=int(x(8.0)), y=60, state=0))
app.seek_rel(1)
check('arrow key seeks one second', abs(app.head_t() - 9.0) < 0.1, app.head_t())
app.tl_sel_press(Ev(x=int(x(2.0)), y=60, state=1))
app.tl_sel_drag(Ev(x=int(x(4.0)), y=60, state=1))
check('shift-drag selects A-B', app.sel and abs(app.sel[0] - 2.0) < 0.1 and abs(app.sel[1] - 4.0) < 0.1, app.sel)
app.sel_clear()
check('Clear removes the selection', app.sel is None and app.player.region is None)
span = app.view[1] - app.view[0]
app.tl_wheel(Ev(x=int(x(10.0)), y=60, delta=120, state=0))
check('wheel up zooms in', app.view[1] - app.view[0] < span * 0.9, app.view)
v0 = app.view[0]
app.tl_pan_start(Ev(x=600, y=60))
app.tl_pan(Ev(x=500, y=60))
check('right-drag pans', app.view[0] > v0, (v0, app.view[0]))
app.tl_full(Ev(x=0, y=0))
check('double-click shows the whole clip', abs(app.view[0] - 0.0) < 1e-6 and abs(app.view[1] - ca.duration) < 1e-6, app.view)
app.compare_start(ca, cb, auto=False)
pump(root, 0.3)
lane_y = (app.lanes()['B'][0] + app.lanes()['B'][1]) // 2
sb0 = app.cmp['sb']
app.tl_press(Ev(x=int(x(10.0)), y=lane_y, state=0))
app.tl_drag(Ev(x=int(x(10.0)) + 50, y=lane_y, state=0))
app.tl_release(Ev(x=int(x(10.0)) + 50, y=lane_y, state=0))
check('dragging lane B moves its start', app.cmp['sb'] > sb0 + 0.1 and app.v_move.get() == 'B' and app.cmp['dirty'] is not None, app.cmp['sb'])
app.cmp_close()

# ---- play / pause (the audio stream is a stand-in: nothing is played)
import sounddevice as sd


class FakeStream:
    def __init__(self, **kw):
        self.callback = kw['callback']

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


sd.OutputStream = FakeStream
app.seek_t(0.0)
app.play_toggle()
check('PLAY starts the player', app.player.playing and app.player.error is None, app.player.error)
app.play_toggle()
check('PLAY again pauses it', not app.player.playing)
app.go_live()
app.play_toggle()
check('PLAY does nothing while live', not app.player.playing)


# ---- level history: one column per pixel, moving left a pixel at a time
rng = np.random.default_rng(1)
peaks = np.abs(rng.standard_normal((9000, 2))) * 0.05 + 0.02
hx0, hy0, hx1, hy1 = app.P['hist']
hw = int(hx1 - hx0)


def history_at(total):
    """the line the panel shows after `total` blocks: the absolute column of each vertex and the vertices"""
    app.draw_history(peaks[max(0, total - 3100):total], 0.0, total)
    pts = np.array(app.c.coords(app.h_l[-1][0]), dtype=float).reshape(-1, 2)
    newest = (total - 1) * hw // 3000 - 1  # the newest complete column sits at the right edge
    return newest - (hx1 - pts[:, 0]), pts


cols0, p0 = history_at(4000)
check('history: one vertex per pixel column, exactly one pixel apart', len(p0) == hw and bool(np.all(np.diff(p0[:, 0]) == 1)), (len(p0), hw))
check('history: the newest column is at the right edge and nothing is left of the panel', p0[-1, 0] == hx1 and p0[0, 0] > hx0)
moved = []
for total in (4000, 4001, 4003, 4007, 4010, 4234):
    ca_, pa = history_at(total)
    cb_, pb = history_at(total + 3)
    ya, yb = dict(zip(ca_.tolist(), pa[:, 1])), dict(zip(cb_.tolist(), pb[:, 1]))
    moved.append(max(abs(ya[c] - yb[c]) for c in set(ya) & set(yb)))
check('history: a column keeps its height when new blocks arrive', max(moved) < 1e-9, moved)
steps = [int(history_at(t_)[0][-1] - history_at(t_ - 1)[0][-1]) for t_ in range(4000, 4300)]
check('history: the picture moves by 0 or exactly 1 pixel per block (60 pixels in 300 blocks)', set(steps) <= {0, 1} and 58 <= sum(steps) <= 62, (sorted(set(steps)), sum(steps)))
history_at(15)
check('history: a very short run draws nothing and does not fail', True)

# ---- auto gain: a loud peak in the drawn part never runs into the edge of the scope
n_gain = m.SR * 6
tt = np.arange(n_gain) / m.SR
sig = 0.05 * np.sin(2 * np.pi * 220 * tt)
sig[2 * m.SR:2 * m.SR + 1200] = 0.8 * np.sin(2 * np.pi * 220 * tt[:1200])  # a loud burst, older than the last 2048 samples of the window but inside the part that is drawn
app.open_loaded(m.Clip(np.stack([sig, sig], axis=1), None, name='gain test'))
app.auto = True
ox0, oy0, ox1, oy1 = app.P['osc']
worst = []
for start_gain in (1.0, 18.0, 400.0):
    app.gain = start_gain
    app.player.pos = 2 * m.SR - 300 + 4096  # the burst sits at 300 to 1500 of the 4096-sample window
    app.draw()
    ys = np.array(app.c.coords(app.o_l[-1][0])).reshape(-1, 2)[:, 1]
    worst.append((round(float(ys.min()), 1), round(float(ys.max()), 1)))
check('auto gain: a loud peak in the drawn part never runs into the edge of the scope', all(lo > oy0 + 1.5 and hi < oy1 - 1.5 for lo, hi in worst), (worst, (oy0, oy1)))
app.gain = 1.0
app.player.pos = 4 * m.SR  # a quiet part: the gain climbs gently instead of jumping
app.draw()
check('auto gain: it rises gently when the sound is quiet', 1.0 < app.gain < 5.0, app.gain)
app.go_live()

# ---- finding problems in a clip: button, markers, panel, saved report, DC readout
fx, expected = T.faulty_demo()
faulty_path = os.path.join(tmp, 'faulty.wav')
faulty = m.Clip(fx.astype(np.float32), None, name='faulty.wav')
faulty.save(faulty_path)
app.go_live()
app.find_problems_key()
check('Find problems: with nothing open it says what to do', 'open or record a clip' in app.lbl_msg.cget('text'), app.lbl_msg.cget('text'))
app.open_loaded(faulty)
app.find_problems_key()
check('Find problems: the clip is scanned and the panel shows the findings', faulty.findings is not None and len(faulty.findings) >= 7 and app.findings_on)
app.draw()
check('Find problems: the panel names the channel and the fault', app.c.itemcget(app.cmp_txt, 'state') == 'normal' and 'RIGHT' in app.c.itemcget(app.cmp_txt, 'text') and 'blast' in app.c.itemcget(app.cmp_txt, 'text') and app.c.itemcget(app.hist_title, 'text').startswith('FINDINGS'), app.c.itemcget(app.hist_title, 'text'))
bangs = [q for q in faulty.markers if q['name'].startswith('!')]
check('Find problems: markers starting with ! are put on the timeline', len(bangs) >= 6 and any(q['name'] == '!R blast' for q in bangs), [q['name'] for q in bangs])
check('Find problems: the report, JSON and picture are saved next to the clip', all(os.path.exists(os.path.join(tmp, 'faulty.analysis.' + e)) for e in ('txt', 'json', 'png')))
check('Find problems: and the markers are in the clip file', any(q['name'] == '!R blast' for q in json.load(open(os.path.join(tmp, 'faulty.json')))['markers']))
app.find_problems_key()
app.draw()
check('Find problems: F again hides the panel and the level history comes back', not app.findings_on and app.c.itemcget(app.cmp_txt, 'state') == 'hidden' and app.c.itemcget(app.hist_title, 'text').startswith('LEVEL HISTORY'))
n_before = len(faulty.markers)
faulty.findings = None
app.find_problems_key()
check('Find problems: scanning again does not pile up markers', len(faulty.markers) == n_before, (n_before, len(faulty.markers)))
app.open_loaded(m.Clip(T.demo_audio(1).astype(np.float32), None, name='clean.wav'))
check('opening another clip closes the findings panel', not app.findings_on)
app.find_problems_key()
app.draw()
check('Find problems: clean music has nothing above "worth knowing"', not [q for q in app.clip.findings if q['severity'] >= 2], [(q['t'], q['kind']) for q in app.clip.findings if q['severity'] >= 2])
app.find_problems_key()
# the DC readout in the title row of the levels panel
app.open_loaded(faulty)
app.player.pos = 10 * m.SR  # the right channel carries +25 % DC here
app.frame = 0
app.draw()
txt = app.c.itemcget(app.dc_txt, 'text')
check('DC readout: shows the offset per channel', 'DC' in txt and abs(app.dc_now[1] - 25.0) < 3.0 and abs(app.dc_now[0]) < 3.0, (txt, app.dc_now))
check('DC readout: is highlighted when an offset is large', app.c.itemcget(app.dc_txt, 'fill') == app.th.peak, app.c.itemcget(app.dc_txt, 'fill'))
app.player.pos = 2 * m.SR
app.frame = 0
app.draw()
check('DC readout: is quiet for a clean stretch', abs(app.dc_now[0]) < 3.0 and abs(app.dc_now[1]) < 3.0 and app.c.itemcget(app.dc_txt, 'fill') == app.th.dim, (app.dc_now, app.c.itemcget(app.dc_txt, 'fill')))
app.go_live()
app.frame = 0
app.draw()
check('DC readout: works on the live sound', 'DC' in app.c.itemcget(app.dc_txt, 'text'))

# ---- themes
def rgb(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]

import re


def hex_colours(theme):
    out = []
    for key, val in vars(theme).items():
        if key in ('name', 'lname', 'rname'):
            continue
        out += val if isinstance(val, list) else ([val] if isinstance(val, str) else [])
    return out


names = [t.name for t in m.THEMES]
check('theme names are unique and Classic comes first', len(set(names)) == len(names) and names[0] == 'Classic', names)
bad = [c for t in m.THEMES for c in hex_colours(t) if not re.match(r'^#[0-9a-f]{6}$', c)]
check('every theme colour is a valid #rrggbb', not bad, bad[:3])
first = app.th.name
for _ in m.THEMES:
    app.cycle_theme()
    pump(root, 0.35)
    no_error('theme ' + app.th.name)
    th = app.th
    cm = app.c.itemcget(app.cor_mark, 'fill')
    check('theme %s: the correlation marker uses its colours' % th.name, cm in (th.good, th.mid, th.bad), cm)
    def painted(color):
        n = 0
        for item in app.c.find_all():
            try:
                n += app.c.itemcget(item, 'fill') == color
            except tk.TclError:
                pass
        return n
    check('theme %s: the 0 dB lines and their labels use its peak colour' % th.name, painted(th.peak) >= 4, painted(th.peak))
    bm = rgb(app.c.itemcget(app.bal_mark, 'fill'))
    lo, hi = zip(*[sorted(pair) for pair in zip(rgb(th.left), rgb(th.right))])
    check('theme %s: the balance marker is a blend of its two channel colours' % th.name, all(l_ - 2 <= v <= h_ + 2 for v, l_, h_ in zip(bm, lo, hi)), (bm, th.left, th.right))
check('cycling through every theme comes back to the first', app.th.name == first)
check('a theme with glow draws each trace as a bright line with four dimmer ones around it', (app.cycle_theme() or True) and app.th.glow and len(app.o_l) == 5 and len(app.s_l) == 5 and len(app.h_r) == 5)
app.set_spec_mode('spectrogram')
pump(root, 1.0)
no_error('themed spectrogram')
app.set_spec_mode('spectrum')
lut = m.palette(base='#2bff70')
check('the spectrogram palette follows the theme colour', tuple(lut[0]) == (0, 0, 0) and lut[190][1] > 2 * lut[190][0] and lut[-1].min() > 150, (tuple(lut[190]), tuple(lut[-1])))
app.theme_i = 0
app.use_theme()
app.build_ui()
check('Classic has no glow', not app.th.glow and len(app.o_l) == 1)
app.compare_start(ca, cb, auto=False)
app.cycle_theme()
pump(root, 0.5)
no_error('theme change while comparing')
check('compare row survives a theme change', app.mode == 'compare' and app.cmp_row.winfo_manager() == 'pack')
app.cmp_close()
app.go_live()

# ---- settings
app.theme_i = 2
app.use_theme()
app.auto = False
app.gain = 7.5
app.comp = False
app.set_spec_mode('spectrogram')
app.player.loop = True
app.save_settings()
check('settings written', os.path.exists(m.SETTINGS))
saved = json.load(open(m.SETTINGS))
check('the theme is saved by name', saved.get('theme') == 'Amber phosphor', saved.get('theme'))
check('settings hold the window size and the input', 'w' in saved and 'h' in saved and saved.get('source') == ['default', None], {k: saved.get(k) for k in ('w', 'h', 'source')})
app.quit()
try:
    alive = root.winfo_exists()
except tk.TclError:
    alive = 0
check('quit closes the window', not alive)
cap.stop = True
root2 = tk.Tk()
root2.withdraw()
app2 = m.App(root2, T.SynthCapture())
check('settings restored', (app2.auto, app2.gain, app2.comp, app2.spec_mode, app2.player.loop) == (False, 7.5, False, 'spectrogram', True),
      (app2.auto, app2.gain, app2.comp, app2.spec_mode, app2.player.loop))
check('the theme is restored', app2.th.name == 'Amber phosphor', app2.th.name)
root2.destroy()
T.finish()
