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
keys = ['<space>', '<F5>', 'c', 'r', 'u', 'l', '<Control-o>', 'g', 'f', 'm', '<Delete>', '<Prior>', '<Next>', 'i', 'o', 'x', 'p', 'e', '1', '2', '3',
        '<Left>', '<Right>', '<Shift-Left>', '<Alt-Left>', '<Alt-Shift-Left>', '<Alt-Control-Left>', '<Home>', '<End>', 'q', '<Escape>']
check('all documented keys are bound', all(root.bind(k) for k in keys), [k for k in keys if not root.bind(k)])
check('the scope gain controls are gone: their keys are unbound and nothing of them is left', not any(root.bind(k) for k in ('<plus>', '<equal>', '<minus>', 'a')) and not callable(getattr(app, 'zoom', None)) and not hasattr(app, 'b_auto') and not hasattr(app, 'auto'))
labels = []
for w_ in app.controls.winfo_children():
    try:
        labels.append(str(w_.cget('text')))
    except tk.TclError:
        pass
check('the controls row has no gain, auto gain or Windows volume button, and Reset peaks sits right after Theme', not [t_ for t_ in labels if 'gain' in t_.lower() or 'volume' in t_.lower()] and not hasattr(app, 'b_comp')
      and [t_ for t_ in labels if t_.startswith('Theme')] and labels.index([t_ for t_ in labels if t_.startswith('Theme')][0]) + 1 == labels.index('Reset peaks  (R)'), labels)
app.cap.sess = [0.5, 0.4]
app.cap.flat = [3, 2]
app.hold[:] = [-3.0, -4.0]
app.b_reset.invoke()
check('Reset peaks clears the session peaks, the clipped-block counts and the held peaks', list(app.cap.sess) == [0.0, 0.0] and list(app.cap.flat) == [0, 0] and list(app.hold) == [m.FLOOR, m.FLOOR], (app.cap.sess, app.cap.flat, app.hold))
check('the levels are shown as measured by default (the C key can ignore the Windows volume)', app.comp is False and bool(root.bind('c')))
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
check('live: the levels text has no LUFS line', 'LUFS' not in txt and 'short-term' not in txt and 'integrated' not in txt and txt.splitlines()[-1].startswith('clipped blocks') and 'flat-top' not in txt, txt.splitlines()[-1])
bal_txt = app.c.itemcget(app.bal_lbl, 'text')
bal_n = float(bal_txt.split()[1])
bl, br = list(app.met_geom['bal'][0]), list(app.met_geom['bal'][1])
len_l, len_r = app.bal_x - bl[0], br[2] - app.bal_x
check('the balance label is just "balance"', bal_txt.startswith('balance ') and 'L-R' not in bal_txt and 'R-L' not in bal_txt, bal_txt)
check('the balance shows both channels at once: the left bar grows to the left of the centre, the right bar to the right, each by its own level', len_l > 0 and len_r > 0 and bl[2] == app.bal_x and br[0] == app.bal_x, (bl, br, app.bal_x))
check('a positive balance figure means the left is louder, so its bar is the longer one', (bal_n > 0.05 and len_l > len_r) or (bal_n < -0.05 and len_r > len_l) or abs(bal_n) <= 0.05, (bal_txt, len_l, len_r))
check('vectorscope: the picture of a beam screen is drawn from the sound', app.beam is not None and app.photos.get('vec') is not None and float(app.beam.buf.max()) > 0 and bool(app.c.itemcget(app.vec_item, 'image')), (app.beam is not None, app.photos.get('vec') is not None))
app.cap.eq_note = 'Equalizer APO undone'
pump(root, 0.3)
check('the status line says when a system equaliser is being undone, and only then', 'Equalizer APO undone' in app.c.itemcget(app.status, 'text'), app.c.itemcget(app.status, 'text'))
app.cap.eq_note = ''
pump(root, 0.3)
check('...and it does not when there is none', 'Equalizer' not in app.c.itemcget(app.status, 'text'))
check('the U key is for the undoing of the equaliser (the capture has the switch, on by default)', app.cap.undo_eq is True)
check('live: no correlation meter any more', not hasattr(app, 'cor_lbl') and not hasattr(app, 'cor_mark') and not any('correlation' in app.c.itemcget(i, 'text') for i in app.c.find_all() if app.c.type(i) == 'text'))
check('clip row hidden while live', app.clip_row.winfo_manager() == '' and app.cmp_row.winfo_manager() == '', (app.clip_row.winfo_manager(), app.cmp_row.winfo_manager()))

# ---- input menu
app.fill_src_menu()
check('input menu lists the default output first', app.src_menu.index('end') is not None and 'Default output' in app.src_menu.entrycget(0, 'label'), app.src_menu.entrycget(0, 'label'))
check('input button shows the current input', app.mb_src.cget('text') not in ('', '...'), app.mb_src.cget('text'))
app.pick_source(dict(kind='default', id=None, label='Default output'))
check('picking an input asks the capture for it', app.cap.want == ('default', None))

# ---- toggle buttons
app.b_spec.invoke()
check('Spectrogram button switches the view', app.spec_mode == 'spectrogram')
app.b_spec.invoke()
check('Spectrogram button switches back', app.spec_mode == 'spectrum')
# ---- live spectrogram
app.set_spec_mode('spectrogram')
pump(root, 1.5)
no_error('live spectrogram')
check('live spectrogram: image drawn', app.sg_photo is not None)
app.set_spec_mode('spectrum')
# ---- the spectrum names the equaliser ranges along its bottom, and the oscilloscope no longer prints its gain
texts = [app.c.itemcget(i, 'text') for i in app.c.find_withtag('spec') if app.c.type(i) == 'text']
need = ['Bass', 'Mids', 'Sub', '60-250', '500-2k', '6k-20k']
check('spectrum: the equaliser ranges are named along the bottom', all(any(t_.startswith(n) or t_ == n for t_ in texts) for n in need), texts)
px0, py0, px1, py1 = app.P['spec']
check('spectrum: the names sit under the graph, and the traces stay inside it',
      all(app.c.coords(i)[1] > py1 for i in app.c.find_withtag('spec') if app.c.type(i) == 'text' and app.c.itemcget(i, 'text') in need) and all(py0 - 1 <= y_ <= py1 + 1 for y_ in app.spec_pts[0][1]), (app.P['spec'],))
def db_rows(tag):
    out = {}
    for i in app.c.find_withtag(tag):
        if app.c.type(i) == 'text' and app.c.itemcget(i, 'text').endswith(' dB'):
            out[app.c.itemcget(i, 'text')] = (app.c.coords(i)[0], app.c.coords(i)[1])
    return out
rows_s, rows_h = db_rows('spec'), db_rows('hist')
check('spectrum and level history: the same dB numbers on the same rows (they sit side by side)', len(rows_s) == 9 and {k: v[1] for k, v in rows_s.items()} == {k: v[1] for k, v in rows_h.items()}, (rows_s, rows_h))
check('spectrum and level history: both graphs end on the -80 dB line, at the same row', abs(rows_s['-80 dB'][1] - py1) <= 1 and app.P['spec'][1::2] == app.P['hist'][1::2], (rows_s.get('-80 dB'), app.P['spec'], app.P['hist']))
check('the dB numbers have their own column: left of every graph, so no trace can run through them', all(x_ < app.P['spec'][0] for x_, _ in rows_s.values()) and all(x_ < app.P['hist'][0] for x_, _ in rows_h.values()) and px0 > app.panel_frame['spec'][0] + app.S(30), (px0, app.panel_frame['spec']))
app.draw_spectrum(np.zeros(4096), np.zeros(4096), 0.0)
app.draw_history([(0.0, 0.0)] * 3100, 0.0, 4000)
ys_s, ys_h = app.spec_pts[0][1], app.hist_pts[0][1]
check('with no sound the spectrum and the level history both draw their line on the same bottom row', set(ys_s) == {float(py1)} and set(ys_h) == {float(py1)}, (sorted(set(ys_s))[:3], sorted(set(ys_h))[:3], py1))
check('the spectrum and level history headers are plain', app.c.itemcget(app.spec_title, 'text') == 'SPECTRUM' and app.c.itemcget(app.hist_title, 'text') == 'LEVEL HISTORY', (app.c.itemcget(app.spec_title, 'text'), app.c.itemcget(app.hist_title, 'text')))
pump(root, 0.3)
check('the status line says nothing about the levels unless the Windows volume is being ignored', 'levels as measured' not in app.c.itemcget(app.status, 'text') and 'ignored' not in app.c.itemcget(app.status, 'text'), app.c.itemcget(app.status, 'text'))
check('oscilloscope: no gain text in the panel', not any('gain' in app.c.itemcget(i, 'text') for i in app.c.find_all() if app.c.type(i) == 'text'))
check('no hint line under the panels', not any('F5 record' in app.c.itemcget(i, 'text') or 'SPACE play' in app.c.itemcget(i, 'text') for i in app.c.find_all() if app.c.type(i) == 'text'))
icon = m.draw_icon(64)
check('the window uses the program icon (the same drawing as the icon of the file), not the Tk feather', len(app.icons) == 4 and icon.size == (64, 64) and icon.getpixel((0, 0))[3] == 0 and icon.getpixel((32, 32))[3] == 255 and m.draw_icon(1024).size == (1024, 1024))

# ---- click a scope: it fills the whole scope area; click again: all of them are back
from types import SimpleNamespace as Ev0
check('it takes a double click: the canvas answers <Double-Button-1> and a single click does nothing', bool(app.c.bind('<Double-Button-1>')) and not app.c.bind('<Button-1>'), (app.c.bind('<Double-Button-1>'), app.c.bind('<Button-1>')))
normal_P, normal_frame = dict(app.P), dict(app.panel_frame)
mid = lambda n: ((app.P[n][0] + app.P[n][2]) // 2, (app.P[n][1] + app.P[n][3]) // 2)
for name in ('osc', 'vec', 'spec', 'hist'):
    x_, y_ = mid(name)
    app.scope_click(Ev0(x=x_, y=y_))
    pump(root, 0.5)
    no_error('zoomed ' + name)
    others = [n for n in ('osc', 'vec', 'met', 'spec', 'hist') if n != name]
    big = app.P[name][2] - app.P[name][0] > app.S(560) and app.P[name][3] - app.P[name][1] > app.S(500)
    check('clicking the %s fills the scope area and the other panels are out of sight' % name, app.zoom == name and big and all(app.P[n][0] >= app.CW for n in others), (app.zoom, app.P))
    if name == 'vec':
        check('the zoomed vectorscope stays square', app.P['vec'][2] - app.P['vec'][0] == app.P['vec'][3] - app.P['vec'][1], app.P['vec'])
        check('the zoomed vectorscope gets a bigger beam screen, drawn from the sound', app.beam is not None and 300 < app.beam.size <= 520 and float(app.beam.buf.max()) > 0, app.beam.size if app.beam else None)
    if name == 'spec':
        check('the zoomed spectrum still names its ranges under the graph', any(app.c.itemcget(i, 'text') == 'Bass' and app.c.coords(i)[1] > app.P['spec'][3] and app.c.coords(i)[0] < app.CW for i in app.c.find_withtag('spec') if app.c.type(i) == 'text'))
    app.scope_click(Ev0(x=app.S(300), y=app.S(300)))
    pump(root, 0.3)
    check('clicking again shows all the panels again (%s)' % name, app.zoom is None and app.P == normal_P and app.panel_frame == normal_frame, (app.zoom,))
app.scope_click(Ev0(x=(normal_P['met'][0] + normal_P['met'][2]) // 2, y=(normal_P['met'][1] + normal_P['met'][3]) // 2))
check('the levels panel is not enlarged by a click', app.zoom is None)
no_error('after zooming')
check('live: the timeline and the rows under the transport are collapsed', app.mode == 'live' and app.tl.winfo_manager() == '' and app.clip_row.winfo_manager() == '' and app.cmp_row.winfo_manager() == '', (app.tl.winfo_manager(), app.clip_row.winfo_manager()))

# ---- record
app.rec_toggle()
pump(root, 0.5)
check('recording opens the timeline', app.mode == 'rec' and app.tl.winfo_manager() == 'pack', (app.mode, app.tl.winfo_manager()))
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
pump(root, 0.3)
check('going live collapses the timeline again', app.tl.winfo_manager() == '' and app.clip_row.winfo_manager() == '' and app.cmp_row.winfo_manager() == '', (app.tl.winfo_manager(),))
check('fit_k counts the timeline only while it shows', app.fit_k(1240, 800, True) < app.fit_k(1240, 800, False) or app.fit_k(1240, 800, True) == app.fit_k(1240, 800, False) == 1.0, (app.fit_k(1240, 800, True), app.fit_k(1240, 800, False)))

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
    pts = np.stack([app.hist_pts[0][0], app.hist_pts[0][1]], axis=1)
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
check('history: the picture moves by 0 or exactly 1 pixel per block (the panel width x 300 / 3000 pixels in 300 blocks)', set(steps) <= {0, 1} and abs(sum(steps) - hw * 300 / m.HIST_BLOCKS) <= 2, (sorted(set(steps)), sum(steps), hw * 300 / m.HIST_BLOCKS))
history_at(15)
check('history: a very short run draws nothing and does not fail', True)

# ---- auto gain: a loud peak in the drawn part never runs into the edge of the scope
n_gain = m.SR * 6
tt = np.arange(n_gain) / m.SR
sig = 0.05 * np.sin(2 * np.pi * 220 * tt)
sig[2 * m.SR:2 * m.SR + 1200] = 0.8 * np.sin(2 * np.pi * 220 * tt[:1200])  # a loud burst, older than the last 2048 samples of the window but inside the part that is drawn
app.open_loaded(m.Clip(np.stack([sig, sig], axis=1), None, name='gain test'))
ox0, oy0, ox1, oy1 = app.P['osc']
worst = []
for start_gain in (1.0, 18.0, 400.0):
    app.gain = start_gain
    app.player.pos = 2 * m.SR - 300 + 4096  # the burst sits at 300 to 1500 of the 4096-sample window
    app.draw()
    ys = app.osc_pts[0][1]
    worst.append((round(float(ys.min()), 1), round(float(ys.max()), 1)))
check('auto gain: a loud peak in the drawn part never runs into the edge of the scope', all(lo > oy0 + 1.5 and hi < oy1 - 1.5 for lo, hi in worst), (worst, (oy0, oy1)))
app.gain = 1.0
app.player.pos = 4 * m.SR  # a quiet part: the gain climbs gently instead of jumping
app.draw()
check('auto gain: it rises gently when the sound is quiet', 1.0 < app.gain < 5.0, app.gain)
# the balance bars follow their own channel: a clip with sound in the left channel only
only_left = np.stack([sig, np.zeros_like(sig)], axis=1)
app.open_loaded(m.Clip(only_left, None, name='left only'))
app.player.pos = 2 * m.SR + 4096
for _ in range(40):
    app.draw()
bl, br = list(app.met_geom['bal'][0]), list(app.met_geom['bal'][1])
check('left channel only: the left bar is long and the right bar has no length', app.bal_x - bl[0] > app.S(60) and br[2] - app.bal_x < 1, (bl, br, app.bal_x))
rows = np.flatnonzero(app.beam.buf.sum(axis=1) > 0)
mid_row = (app.beam.size - 1) / 2.0
check('left channel only: the beam draws a horizontal line through the middle of the vectorscope', len(rows) and rows.min() >= mid_row - 1.5 and rows.max() <= mid_row + 1.5, (rows.min() if len(rows) else None, rows.max() if len(rows) else None, mid_row))
held = float(app.beam.buf.sum())
app.draw()
check('with no new samples (paused) the vectorscope picture stays as it is', float(app.beam.buf.sum()) == held)
app.open_loaded(m.Clip(only_left[:, ::-1].copy(), None, name='right only'))
app.player.pos = 2 * m.SR + 4096
for _ in range(40):
    app.draw()
bl, br = list(app.met_geom['bal'][0]), list(app.met_geom['bal'][1])
check('right channel only: the right bar is long and the left bar has no length', br[2] - app.bal_x > app.S(60) and app.bal_x - bl[0] < 1, (bl, br, app.bal_x))
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
check('DC readout: is hidden for a clean stretch', abs(app.dc_now[0]) < 1.0 and abs(app.dc_now[1]) < 1.0 and app.c.itemcget(app.dc_txt, 'text') == '', (app.dc_now, app.c.itemcget(app.dc_txt, 'text')))
tt2 = np.arange(3 * m.SR) / float(m.SR)
s2 = 0.3 * np.sin(2 * np.pi * 220 * tt2)
for dc_amount, shown in ((0.005, False), (0.02, True)):
    app.open_loaded(m.Clip(np.stack([s2 + dc_amount, s2], axis=1).astype(np.float32), None, name='dc %.1f' % (dc_amount * 100)))
    app.player.pos = 2 * m.SR
    app.frame = 0
    app.draw()
    txt = app.c.itemcget(app.dc_txt, 'text')
    check('DC readout: %.1f %% is %s' % (dc_amount * 100, 'shown (and not red below 3 %)' if shown else 'hidden (under 1 %)'),
          ('DC' in txt and app.c.itemcget(app.dc_txt, 'fill') == app.th.dim) if shown else txt == '', (txt, app.dc_now))
app.go_live()
app.frame = 0
app.draw()
check('DC readout: nothing to say about the live sound while it has no offset', app.c.itemcget(app.dc_txt, 'text') == '', (app.c.itemcget(app.dc_txt, 'text'), app.dc_now))

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
    def painted(color):
        n = 0
        for item in app.c.find_all():
            try:
                n += app.c.itemcget(item, 'fill') == color
            except tk.TclError:
                pass
        return n
    check('theme %s: the 0 dB lines and their labels use its peak colour' % th.name, painted(th.peak) >= 4, painted(th.peak))
    check('theme %s: the level bars and the balance bars are drawn in the two channel colours' % th.name, app.plots['met'].plot.luts[0].tolist() == m.beam_palette(th.bg, th.left, light=True).tolist() and app.plots['met'].plot.luts[1].tolist() == m.beam_palette(th.bg, th.right, light=True).tolist(), th.name)
check('cycling through every theme comes back to the first', app.th.name == first)
app.cycle_theme()
pump(root, 0.6)
check('a theme with glow draws its graphs with a halo: the oscilloscope, spectrum and history screens are phosphor pictures at full glow', app.th.glow and all(app.plots[n_].plot.glow == 1.0 for n_ in ('osc', 'spec', 'hist')) and app.plots['hist'].plot.blend == 'max' and all(app.photos.get(n_) is not None for n_ in ('osc', 'spec', 'hist')), (app.th.name, sorted(app.plots), sorted(app.photos)))
check('changing the theme prints no message (the change is obvious)', 'theme' not in app.lbl_msg.cget('text').lower(), app.lbl_msg.cget('text'))
app.set_spec_mode('spectrogram')
pump(root, 1.0)
no_error('themed spectrogram')
app.set_spec_mode('spectrum')
lut = m.palette(base='#2bff70')
check('the spectrogram palette follows the theme colour', tuple(lut[0]) == (0, 0, 0) and lut[190][1] > 2 * lut[190][0] and lut[-1].min() > 150, (tuple(lut[190]), tuple(lut[-1])))
app.theme_i = 0
app.use_theme()
app.build_ui()
pump(root, 0.5)
check('Classic keeps crisp lines: a weaker halo', not app.th.glow and all(app.plots[n_].plot.glow < 0.5 for n_ in ('osc', 'spec')), (app.th.glow, {n_: app.plots[n_].plot.glow for n_ in app.plots if n_ != 'vec'}))
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
app.comp = True
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
check('settings restored', (app2.comp, app2.spec_mode, app2.player.loop) == (False, 'spectrogram', True), (app2.comp, app2.spec_mode, app2.player.loop))
check('the gain and the Windows volume switch are not settings: every start is automatic gain, levels as measured', 'auto' not in saved and 'gain' not in saved and 'comp' not in saved, sorted(saved))
check('the theme is restored', app2.th.name == 'Amber phosphor', app2.th.name)
root2.destroy()
T.finish()
