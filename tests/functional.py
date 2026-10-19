"""drives the whole app in a hidden window with a synthetic input: live view, recording, review, selection, loop, export, comparing, input menu, scaling, settings"""
import json
import os
import re
import time
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
lines_ = txt.splitlines()
check('live: the levels text is hold, peak, session peak, clipped blocks (hold first, no unit letters)', [l_[:15].strip() for l_ in lines_] == ['hold', 'peak', 'session peak', 'clipped blocks'] and 'dBFS' not in txt, lines_)
check('live: the figures of the two channels are in two columns (the labels padded, the numbers right-aligned), with blank places where the letters L and R go',
      all(len(l_) == 35 and l_[15:18] == '   ' and l_[24:29] == '     ' and l_[18:24].strip() != '' and l_[29:35].strip() != '' for l_ in lines_) and 'L' not in txt and 'R' not in txt, lines_)
from tkinter import font as tkfont_l
mf_ = tkfont_l.Font(root=root, font=app.F(9))
lr_items = {app.c.itemcget(i, 'text'): i for i in app.c.find_all() if app.c.type(i) == 'text' and app.c.itemcget(i, 'text') in (chr(10).join('LLLL'), chr(10).join('RRRR'))}
tx_, ty_ = app.c.coords(app.m_txt)
check('live: all the Ls are one column in the left channel colour and all the Rs one column in the right channel colour, in the blank places of the figures',
      len(lr_items) == 2 and app.c.itemcget(lr_items[chr(10).join('LLLL')], 'fill') == app.CL and app.c.itemcget(lr_items[chr(10).join('RRRR')], 'fill') == app.CR
      and abs(app.c.coords(lr_items[chr(10).join('LLLL')])[0] - (tx_ + mf_.measure(' ' * 16))) < 0.6 and abs(app.c.coords(lr_items[chr(10).join('RRRR')])[0] - (tx_ + mf_.measure(' ' * 27))) < 0.6
      and abs(app.c.coords(lr_items[chr(10).join('LLLL')])[1] - ty_) < 0.6 and abs(app.c.coords(lr_items[chr(10).join('RRRR')])[1] - ty_) < 0.6, (lr_items, app.CL, app.CR))
bal_line = app.c.itemcget(app.bal_lbl, 'text')
check('live: the sign of the balance figure is in the column of the Ls above it', bal_line.startswith('balance') and bal_line.index(bal_line.split()[1]) == 16 and bal_line.endswith(' dB'), bal_line)
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
from tkinter import font as tkfont_
nf_ = tkfont_.Font(root=root, font=app.F(8))
wm_, w2_ = nf_.measure('-'), nf_.measure('48')
bar_mid = (app.bar_xs[0] + app.bar_xs[1] + app.S(50)) / 2.0
labels = {app.c.itemcget(i, 'text'): app.c.coords(i) for i in app.c.find_all()
          if app.c.type(i) == 'text' and app.c.itemcget(i, 'text') in ('0', '6', '12', '24', '48') and app.c.itemcget(i, 'anchor') == 'w'}
col0 = app.bal_x - (wm_ + w2_) / 2.0 + wm_
shift = {'12': 2, '24': 3, '48': 2}
check('the level bars are centred on the balance bar; the first digits of the dB numbers 0 and -6 are in one column, with the widest number centred on it',
      abs(bar_mid - app.bal_x) <= 1 and sorted(labels, key=int) == ['0', '6', '12', '24', '48'] and all(abs(labels[k][0] - col0) < 0.6 for k in ('0', '6')), (bar_mid, app.bal_x, labels))
check('the gap between the two digits of -12, -24 and -48 is on the centre line of the balance bar (each number sits a hair left of the column)',
      all(abs(labels[k][0] - (col0 - app.S(shift[k]))) < 0.6 and abs(labels[k][0] + nf_.measure(k[0]) - app.bal_x) <= app.S(1.6) for k in shift), {k: (labels[k][0], labels[k][0] + nf_.measure(k[0]), app.bal_x) for k in shift})
ticks = {}
for k, (lx_, ly_) in labels.items():
    lines = sorted((round(app.c.coords(j)[0], 1), round(app.c.coords(j)[2], 1)) for j in app.c.find_all()
                   if app.c.type(j) == 'line' and abs(app.c.coords(j)[1] - ly_) < 0.01 and abs(app.c.coords(j)[3] - ly_) < 0.01)
    ticks[k] = (ly_, lines)
minus = {round(app.c.coords(i)[1], 1): app.c.coords(i)[0] for i in app.c.find_all() if app.c.type(i) == 'text' and app.c.itemcget(i, 'text') == '-' and app.c.itemcget(i, 'anchor') == 'e'}
check('each dB number sits on its line (a line to the left and one to the right of it, the 0 line running on to the digit), the minus signs hang left of their digits, and the lines are where the bars say that level is',
      all(len(v[1]) == 2 for v in ticks.values()) and len(minus) == 4 and all(abs(minus[round(ticks[k][0], 1)] - labels[k][0]) < 0.6 for k in labels if k != '0')
      and all(abs(ticks[k][1][0][1] - (labels[k][0] - app.S(3) - (wm_ if k != '0' else 0))) < 0.6 and abs(ticks[k][1][1][0] - (labels[k][0] + nf_.measure(k) + app.S(3))) < 0.6 for k in labels)
      and abs(ticks['6'][0] - ticks['0'][0] - 0.1 * app.bar_h) < 0.6 and abs(ticks['48'][0] - ticks['0'][0] - 0.8 * app.bar_h) < 0.6, ticks)
mx0, my0, mx1, my1 = app.P['met']
txt_bb, lbl_bb = app.c.bbox(app.m_txt), app.c.bbox(app.bal_lbl)
bars_bottom = app.bar_top + app.bar_h
check('the text is one block at the bottom of the panel (the balance figure its last line, just above the bottom line), and the balance bar is level with the centre line of the vectorscope (between the level bars and the text)',
      my1 - lbl_bb[3] < app.S(14) and lbl_bb[3] <= my1 and lbl_bb[1] > txt_bb[3] - app.S(8) and abs(app.bal_y - (app.P['vec'][1] + app.P['vec'][3]) / 2.0) <= 1 and bars_bottom < app.bal_y - app.S(5) and app.bal_y + app.S(5) < txt_bb[1], (txt_bb, lbl_bb, my1, app.bal_y, bars_bottom, app.P['vec']))
all_text = [(app.c.itemcget(i, 'text'), app.c.coords(i)[0]) for i in app.c.find_all() if app.c.type(i) == 'text']
check('the levels panel has no L, R, LEFT or RIGHT words and the vectorscope title is just its name',
      not [t_ for t_, x_ in all_text if t_ in ('L', 'R', 'LEFT', 'RIGHT') and x_ >= app.P['met'][0]] and 'VECTORSCOPE' in [t_ for t_, _ in all_text] and not any('left across' in t_ for t_, _ in all_text), [t_ for t_, _ in all_text if len(t_) < 8][:20])
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
import time as time_
check("the canvas counts the double clicks itself (a press handler; Tk's own <Double-Button-1> would also fire for the third and fourth quick click)", bool(app.c.bind('<Button-1>')) and not app.c.bind('<Double-Button-1>'), (app.c.bind('<Double-Button-1>'), app.c.bind('<Button-1>')))
app.dbl_time = 0.3
x_, y_ = ((app.P['osc'][0] + app.P['osc'][2]) // 2, (app.P['osc'][1] + app.P['osc'][3]) // 2)
ev_ = Ev0(x=x_, y=y_)
app.click_last = None
app.scope_press(ev_)
check('a single click does nothing', app.zoom is None, app.zoom)
app.scope_press(ev_)
check('a double click enlarges the scope', app.zoom == 'osc', app.zoom)
app.scope_press(ev_)
check('a quick third click does not undo it (the second click of the double click was used up)', app.zoom == 'osc', app.zoom)
app.scope_press(ev_)
check('...but a quick fourth click makes a new double click with the third: the scope is small again', app.zoom is None, app.zoom)
app.scope_press(ev_)
app.scope_press(ev_)
app.scope_press(ev_)
check('click, click, click makes it big and leaves it big, however fast', app.zoom == 'osc', app.zoom)
time_.sleep(0.4)
app.scope_press(ev_)
check('a click that waited longer than the double-click time is a first click again (it takes a double click to go back)', app.zoom == 'osc', app.zoom)
app.scope_press(ev_)
check('...and the double click after it puts the scope back', app.zoom is None, app.zoom)
app.click_last = None
app.dbl_time = m.double_click_time()
check("the double-click time is the system's (or half a second)", 0.2 <= app.dbl_time <= 2.0, app.dbl_time)
app.click_last = None
normal_P, normal_frame = dict(app.P), dict(app.panel_frame)
mid = lambda n: ((app.P[n][0] + app.P[n][2]) // 2, (app.P[n][1] + app.P[n][3]) // 2)
for name in ('osc', 'vec', 'met', 'spec', 'hist'):
    x_, y_ = mid(name)
    app.scope_click(Ev0(x=x_, y=y_))
    pump(root, 0.5)
    no_error('zoomed ' + name)
    others = [n for n in ('osc', 'vec', 'met', 'spec', 'hist') if n != name]
    big = app.P[name][2] - app.P[name][0] > app.S(560) and app.P[name][3] - app.P[name][1] > app.S(500)
    check('clicking the %s fills the scope area and the other panels are out of sight' % name, app.zoom == name and big and all(app.P[n][0] >= app.CW for n in others), (app.zoom, app.P))
    if name == 'met':
        pm_ = app.P['met']
        app.draw()
        check('the enlarged levels keep their shape (314 : 276), are drawn bigger and centred, with all their parts inside the panel',
              app.mz > 1.5 and abs((pm_[0] + pm_[2]) / 2.0 - app.CW / 2.0) <= 1 and abs((pm_[2] - pm_[0]) / float(pm_[3] - pm_[1]) - 314.0 / 276.0) < 0.02
              and pm_[0] <= app.bar_xs[0] and app.bar_xs[1] + app.ms(50) <= pm_[2] and pm_[1] <= app.bar_top and app.bar_top + app.bar_h < app.bal_y < pm_[3]
              and app.c.itemcget(app.m_txt, 'state') != 'hidden' and pm_[0] <= app.c.coords(app.m_txt)[0] < app.CW and app.c.bbox(app.bal_lbl)[3] <= pm_[3], (app.mz, pm_, app.bar_xs, app.bar_top, app.bal_y))
        check('the enlarged levels draw their bars and balance bars bigger too', app.met_geom is not None and app.met_geom['bars'][0][2] - app.met_geom['bars'][0][0] == app.ms(50) and app.ms(50) > app.S(50) * 1.5, (app.met_geom['bars'][0], app.ms(50)))
    if name == 'vec':
        check('the zoomed vectorscope stays square', app.P['vec'][2] - app.P['vec'][0] == app.P['vec'][3] - app.P['vec'][1], app.P['vec'])
        check('the zoomed vectorscope gets a bigger beam screen, drawn from the sound', app.beam is not None and 300 < app.beam.size <= 520 and float(app.beam.buf.max()) > 0, app.beam.size if app.beam else None)
    if name == 'spec':
        check('the zoomed spectrum still names its ranges under the graph', any(app.c.itemcget(i, 'text') == 'Bass' and app.c.coords(i)[1] > app.P['spec'][3] and app.c.coords(i)[0] < app.CW for i in app.c.find_withtag('spec') if app.c.type(i) == 'text'))
    app.scope_click(Ev0(x=app.S(300), y=app.S(300)))
    pump(root, 0.3)
    check('clicking again shows all the panels again (%s)' % name, app.zoom is None and app.P == normal_P and app.panel_frame == normal_frame, (app.zoom,))
rows_ = lambda: [w_.winfo_manager() for w_ in (app.controls, app.transport)]
before_ = rows_()
app.scope_click(Ev0(x=mid('osc')[0], y=mid('osc')[1]))
titles_ = [i for i in app.c.find_all() if app.c.type(i) == 'text' and app.c.itemcget(i, 'text').split(' ')[0] in ('OSCILLOSCOPE', 'VECTORSCOPE', 'LEVELS', 'SPECTRUM', 'LEVEL')]
check('a scope fills the window alone: the button rows are out of sight, the canvas is all that is packed, and no title or status text is in view',
      rows_() == ['', ''] and app.c.winfo_manager() == 'pack' and len(titles_) >= 4 and all(app.c.coords(i)[0] >= app.CW for i in titles_) and app.c.coords(app.status)[0] >= app.CW, (rows_(), [app.c.coords(i) for i in titles_], app.CW))
app.scope_click(Ev0(x=app.S(300), y=app.S(300)))
check('and double-clicking again brings the button rows back, in their places', rows_() == before_ == ['pack', 'pack'] and app.c.winfo_manager() == 'pack', (rows_(), before_))
check('the levels panel can be double-clicked like the others (it is a window the mouse finds)', app.scope_hit((normal_P['met'][0] + normal_P['met'][2]) // 2, (normal_P['met'][1] + normal_P['met'][3]) // 2) == 'met' and app.zoom is None)
no_error('after zooming')

# ---- speed: the spectrum worked out all at once is the spectrum worked out band by band; the pictures on screen are the pictures made; the governor
rng_s = np.random.default_rng(11)
L_s, R_s = rng_s.standard_normal(4096) * 0.05, np.sin(np.arange(4096) * 0.31) * 0.2
app.panel_opts.clear()
app.refresh_panels()
app.draw_spectrum(L_s, R_s, 0.0)
x0_, y0_, x1_, y1_ = app.P['spec']
win_ = np.hanning(4096)
fr_ = np.fft.rfftfreq(4096, 1.0 / m.SR)
edges_ = np.logspace(np.log10(30), np.log10(20000), 140)
ref_pts = []
for data_ in (L_s, R_s):  # the way it was done: a band at a time
    mag_ = np.abs(np.fft.rfft(data_ * win_)) * 2.0 / win_.sum()
    px_, py_ = [], []
    for a_, b_ in zip(edges_[:-1], edges_[1:]):
        sel_ = (fr_ >= a_) & (fr_ < b_)
        v_ = float(mag_[sel_].max()) if sel_.any() else float(mag_[np.searchsorted(fr_, a_)])
        px_.append(app.fx(np.sqrt(a_ * b_)))
        py_.append(min(y1_, max(y0_, y0_ + (-m.db(v_)) / m.DB_RANGE * (y1_ - y0_))))
    ref_pts.append((np.array(px_), np.array(py_)))
check('the spectrum worked out all at once is, point for point, the spectrum worked out a band at a time', all(np.allclose(app.spec_pts[i_][0], ref_pts[i_][0]) and np.allclose(app.spec_pts[i_][1], ref_pts[i_][1], atol=1e-9) for i_ in (0, 1)) and len(app.spec_pts[0][0]) == 139,
      [float(np.abs(app.spec_pts[i_][1] - ref_pts[i_][1]).max()) for i_ in (0, 1)])
# the picture on screen is the picture made, after many frames with bands
app.work_ms = 0.0
for k_ in range(40):
    app.cap.pos  # (the live synthetic sound goes on by itself)
    app.draw()
    time.sleep(0.01)
mism_ = []
for n_ in ('osc', 'spec', 'met'):
    wk_ = app.plots[n_]
    made_ = np.asarray(wk_.plot.image())
    ph_, bi_, bph_ = app.photos[n_], app.band_items.get(n_), app.band_photos.get(n_)
    item_ = {'osc': app.osc_item, 'spec': app.spec_item, 'met': app.met_item}[n_]
    ix_, iy_ = app.c.coords(item_)
    by_ = int(round(app.c.coords(bi_)[1] - iy_)) if (bi_ is not None and app.c.itemcget(bi_, 'image')) else None
    bh_ = bph_.height() if bph_ is not None else 0
    probe_ = [(int(x_), int(y_)) for x_, y_ in zip(rng_s.integers(0, made_.shape[1], 300), rng_s.integers(0, made_.shape[0], 300))] + [(0, 0), (made_.shape[1] - 1, made_.shape[0] - 1)]
    lit_y = np.flatnonzero((made_.astype(int) - np.asarray(wk_.plot.base).astype(int)).sum(axis=(1, 2)) > 0)
    probe_ += [(int(rng_s.integers(0, made_.shape[1])), int(y_)) for y_ in rng_s.choice(lit_y, 120)] if len(lit_y) else []
    wrong_ = 0
    for x_, y_ in probe_:  # what is seen at that pixel: the little picture of the rows with light where there is one, the background elsewhere
        if by_ is not None and by_ <= y_ < by_ + wk_.last_band[1] - wk_.last_band[0]:
            got_ = tuple(int(v_) for v_ in app.root.tk.splitlist(app.root.tk.call(str(bph_), 'get', x_, y_ - by_)))
        else:
            got_ = tuple(int(v_) for v_ in app.root.tk.splitlist(app.root.tk.call(str(ph_), 'get', x_, y_)))
        if max(abs(a_ - b_) for a_, b_ in zip(got_, tuple(int(v_) for v_ in made_[y_, x_]))) > 2:
            wrong_ += 1
    mism_.append((n_, wrong_, by_, wk_.last_band))
check('the pictures in the window are the pictures that were made: the background and, on top, the rows with light: after many frames every pixel looked at is right (no old light left behind)', all(c_[1] == 0 for c_ in mism_), mism_)
# the governor: busy while the window cannot keep up, and it lets go only with plenty of room
app.work_ms, app.redraw_ms, app._busy = 5.0, 5.0, False
app.frame = 1
b0_ = app.busy()
app.work_ms, app.redraw_ms = 18.0, 10.0
app.frame = 1
b1_ = app.busy()
app.work_ms, app.redraw_ms = 12.0, 8.0
app.frame = 1
b2_ = app.busy()
app.work_ms, app.redraw_ms = 8.0, 5.0
app.frame = 1
b3_ = app.busy()
app.frame = 2
b4_ = (app.work_ms, app.redraw_ms, app.busy())
app.work_ms, app.redraw_ms, app._busy = 5.0, 3.0, False
check('the governor: busy only while a frame and its drawing take most of the 33 ms, stays busy until there is plenty of room, and then sits out every other frame only', (b0_, b1_, b2_, b3_) == (False, True, True, False) and b4_[2] is False, (b0_, b1_, b2_, b3_, b4_))
app.panel_opts.clear()
app.refresh_panels()

# ---- speed: the timeline's envelopes are one picture, so the playhead costs nothing; the spectrum's band dividers are only under the graph when its names are
app.go_live()
app.open_loaded(m.Clip(T.demo_audio(1).astype(np.float32), None, name='tl picture'))
pump(root, 0.3)
app.tl_key = None
app.draw_timeline()
tl_ = app.tl
kinds_ = {}
for i_ in tl_.find_all():
    kinds_[tl_.type(i_)] = kinds_.get(tl_.type(i_), 0) + 1
big_polys = [i_ for i_ in tl_.find_all() if tl_.type(i_) == 'polygon' and len(tl_.coords(i_)) > 12]
check('timeline: the level envelopes and flags are one picture on the canvas (no big polygons)', kinds_.get('image') == 1 and not big_polys, (kinds_, len(big_polys)))
lane0 = app.lanes()[0]
ph_ = app.tl_photo
cy_ = int((lane0[0] + lane0[1]) / 2)
want_ = tuple(int(app.th.env_l[i_:i_ + 2], 16) for i_ in (1, 3, 5))
row_ = [tuple(int(v_) for v_ in re.findall(r'\d+', str(app.root.tk.call(str(ph_), 'get', x_, cy_)))[:3]) for x_ in range(0, ph_.width(), 3)]
check('timeline: the envelope is in the picture, in the colour of its channel', any(max(abs(a_ - b_) for a_, b_ in zip(r_, want_)) <= 2 for r_ in row_), want_)
key_, n_items_ = app.tl_key, len(tl_.find_all())
app.seek_t(1.0)
app.draw_timeline()
app.seek_t(2.0)
app.draw_timeline()
check('timeline: moving the playhead changes only the playhead', app.tl_key == key_ and len(tl_.find_all()) == n_items_ and len(tl_.find_withtag('head')) == 2, (app.tl_key == key_, len(tl_.find_all()), n_items_))
app.go_live()
pump(root, 0.3)

def divider_lines():
    xx0, yy0, xx1, yy1 = app.P['spec']
    return [i_ for i_ in app.c.find_withtag('spec') if app.c.type(i_) == 'line' and app.c.coords(i_)[3] > yy1 + 3]

app.panel_opts.clear()
app.panel_opts['spec'] = {'info': True, 'grid': True}
app.refresh_panels()
with_names = len(divider_lines())
app.panel_opts['spec'] = {'info': False, 'grid': True}
app.refresh_panels()
no_names = len(divider_lines())
check('spectrum: with the names off, no band dividers stick out under the graph (they are there with the names on)', with_names >= 4 and no_names == 0, (with_names, no_names))
app.panel_opts.clear()
app.refresh_panels()

# ---- right click on a window: its grid, the crisp light levels, its own colours
check('the oscilloscope title is just its name (no list of the channel colours next to it)', [app.c.itemcget(i_, 'text') for i_ in app.c.find_all() if app.c.type(i_) == 'text' and app.c.itemcget(i_, 'text').startswith('OSCILLOSCOPE')] == ['OSCILLOSCOPE'])
rgb_ = lambda c_: tuple(int(c_[i_:i_ + 2], 16) for i_ in (1, 3, 5))
check('a right click on the canvas opens the menu of the window under it', bool(app.c.bind('<Button-3>')))
met_mid = ((app.P['met'][0] + app.P['met'][2]) // 2, (app.P['met'][1] + app.P['met'][3]) // 2)
check('the window under a point is found (the levels too), and nothing between the windows', all(app.panel_at(*mid(n_)) == n_ for n_ in ('osc', 'vec', 'spec', 'hist')) and app.panel_at(*met_mid) == 'met' and app.panel_at(1, 1) is None,
      {n_: app.panel_at(*mid(n_)) for n_ in ('osc', 'vec', 'spec', 'hist')})


def menu_labels(menu_):
    return [menu_.entrycget(i_, 'label') for i_ in range(menu_.index('end') + 1) if menu_.type(i_) in ('command', 'checkbutton')]


def stepper_labels(menu_):
    return [menu_.entrycget(i_, 'label') for i_ in range(menu_.index('end') + 1) if menu_.type(i_) == 'stepper']


mn_ = app.panel_menu_build('osc')
mv_ = app.panel_menu_build('vec')
check('the menu of a window: its name, Grid, Info, the stepper rows CRT burn and Line strength, the left and the right colour (and nothing to go back from yet)',
      menu_labels(mn_) == ['Oscilloscope', 'Grid', 'Info', 'Left colour...', 'Right colour...'] and stepper_labels(mn_) == ['CRT burn', 'Line strength'], (menu_labels(mn_), stepper_labels(mn_)))
check('the vectorscope has one colour, not two', menu_labels(mv_) == ['Vectorscope', 'Grid', 'Info', 'Colour...'], menu_labels(mv_))
check('the menu shows what is on now: the grid and the info are on, and the oscilloscope has CRT burn 0.4 (the vectorscope 1.0)', mn_._on == (True, True, True, 0.4) and mv_._on == (True, True, True, 1.0), (mn_._on, mv_._on))
check('a tick is a little picture left of the words (a blank one of the same size when off), not a Tk check mark that is drawn over them',
      all(mn_.type(i_) == 'command' for i_ in (2, 3)) and mn_.type(4) == 'stepper' and mn_.entrycget(2, 'compound') == 'left' and mn_.entrycget(2, 'image') == str(mn_._marks[0]) and mn_.entrycget(3, 'image') == str(mn_._marks[0])
      and (mn_._marks[0].width(), mn_._marks[0].height()) == (mn_._marks[1].width(), mn_._marks[1].height()) and mn_._marks[0].width() >= 10,
      (mn_.entrycget(2, 'image'), str(mn_._marks[0]), mn_._marks[0].width()))
check('the window name is a readable heading (not a greyed-out entry, which Windows draws as small embossed text), in a clear colour and bold', str(mn_.entrycget(0, 'state')) == 'normal' and str(mn_.entrycget(0, 'foreground')) == app.th.accent_hi and 'bold' in str(mn_.entrycget(0, 'font')), (mn_.entrycget(0, 'state'), mn_.entrycget(0, 'foreground'), mn_.entrycget(0, 'font')))
check('no entry in the menu is greyed out', all(str(mn_.entrycget(i_, 'state')) == 'normal' for i_ in range(mn_.index('end') + 1) if mn_.type(i_) != 'separator'))
app.panel_opts.clear()
n_vgrid = len(app.c.find_withtag('vgrid'))
mv_.invoke(2)  # Grid
check('Grid off for the vectorscope: its graticule lines are gone (and only its); on again: they are back', app.panel_opts['vec']['grid'] is False and len(app.c.find_withtag('vgrid')) == 0 and n_vgrid == 3
      and app.panel_grid('osc') and len(app.c.find_withtag('vgrid')) == 0, (n_vgrid, app.panel_opts))
app.panel_menu_build('vec').invoke(2)
check('...grid on again', app.panel_opts['vec']['grid'] is True and len(app.c.find_withtag('vgrid')) == 3, app.panel_opts)
base_px = lambda n_: tuple(int(v_) for v_ in np.asarray(app.beam_plot(n_).plot.base)[np.asarray(app.beam_plot(n_).plot.base).shape[0] // 2, 5])
on_px = base_px('osc')
app.panel_menu_build('osc').invoke(2)
check('Grid off for the oscilloscope: its centre line is not in the picture any more, the spectrum keeps its grid', on_px == rgb_(app.th.grid) and base_px('osc') == rgb_(app.th.bg) and app.panel_grid('spec'), (on_px, base_px('osc')))
app.panel_menu_build('spec').invoke(2)
spec_base = np.asarray(app.beam_plot('spec').plot.base)
check('Grid off for the spectrum: no dB lines and no tinted ranges in the picture, only the plain background (and the frame)', len({tuple(v_) for v_ in spec_base[3:-3, 3:-3].reshape(-1, 3)}) == 1 and app.panel_opts['spec']['grid'] is False,
      len({tuple(v_) for v_ in spec_base[3:-3, 3:-3].reshape(-1, 3)}))
app.panel_menu_build('met').invoke(2)
check('Grid off for the levels: the tick lines of the dB numbers are gone too', app.panel_opts['met']['grid'] is False and not [i_ for i_ in app.c.find_all() if app.c.type(i_) == 'line' and app.c.itemcget(i_, 'fill') in (app.th.peak, app.GRID)
      and abs(app.c.coords(i_)[1] - app.c.coords(i_)[3]) < 0.01 and app.P['met'][0] < app.c.coords(i_)[0] < app.P['met'][2] and app.P['met'][1] + app.S(10) < app.c.coords(i_)[1] < app.bar_top + app.bar_h + 2 and app.c.coords(i_)[2] - app.c.coords(i_)[0] < app.S(60)])
app.panel_opts.clear()
app.refresh_panels()
check('the default CRT burn: the oscilloscope, spectrum and level history 0.4, the vectorscope 1.0, the levels 1.0 (Classic: the vectorscope only)',
      all({n_: (lambda t_: (setattr(app, 'th', t_), app.panel_burn_level(n_))[1])(t_) for n_ in m.PANELS} == {'osc': 0.4, 'spec': 0.4, 'hist': 0.4, 'vec': 1.0, 'met': 1.0 if t_.glow else 0.4} for t_ in m.THEMES), [t_.name for t_ in m.THEMES])
app.th = m.THEMES[app.theme_i]
hm_ = app.panel_menu_build('hist')
hm_.set_stepper(hm_.entries.index(hm_.stepper('CRT burn')), 10)  # 1.0
check('CRT burn stepped to 1.0 for the history only: its glow changes, the oscilloscope and the vectorscope keep their own',
      app.panel_burn_level('hist') == 1.0 and app.beam_plot('hist').plot.glow == 1.0 and app.beam_plot('osc').plot.glow == 0.4 and app.panel_burn_level('vec') == 1.0, (app.panel_opts, app.th.name))
vm_ = app.panel_menu_build('vec')
vm_.set_stepper(vm_.entries.index(vm_.stepper('CRT burn')), 4)  # 0.4
app.draw()
check('and for the vectorscope (1.0 by default): its beam screen gets the new glow', app.panel_burn_level('vec') == 0.4 and app.plots['vec'].plot.glow == 0.4, app.plots['vec'].plot.glow)
app.panel_opts.clear()
app.refresh_panels()
app.set_spec_mode('spectrogram')
sm_ = app.panel_menu_build('spec')
check('the spectrogram has no CRT burn, no Overburn, no grid and no colours to choose (they do nothing to it): its menu is its name and Info', menu_labels(sm_) == ['Spectrogram', 'Info'], menu_labels(sm_))
sm_.invoke(2)
check('...and Info still turns its text off (and back on)', app.panel_opts['spec']['info'] is False and app.panel_menu_build('spec').index('end') == 2, app.panel_opts)
app.panel_menu_build('spec').invoke(2)
app.panel_opts.clear()
app.set_spec_mode('spectrum')
check('the spectrum menu has them all again', menu_labels(app.panel_menu_build('spec')) == ['Spectrum', 'Grid', 'Info', 'Left colour...', 'Right colour...'], menu_labels(app.panel_menu_build('spec')))
app.refresh_panels()
app.panel_opts.clear()
app.refresh_panels()
# Info: the numbers and text of a window


def visible_text(n_):
    x0_, y0_, x1_, y1_ = app.panel_frame.get(n_) or app.P[n_]
    return [app.c.itemcget(i_, 'text') for i_ in app.c.find_all() if app.c.type(i_) == 'text' and app.c.itemcget(i_, 'state') != 'hidden'
            and x0_ - 2 <= app.c.coords(i_)[0] <= x1_ and y0_ - app.S(22) <= app.c.coords(i_)[1] <= y1_ + (app.S(40) if n_ == 'spec' else app.S(4)) and app.c.itemcget(i_, 'text') != '']


app.set_spec_mode('spectrum')
before_info = {n_: visible_text(n_) for n_ in ('osc', 'vec', 'met', 'spec', 'hist')}
check('every window has some text or numbers to turn off', all(len(v_) >= 1 for v_ in before_info.values()), {k_: v_[:4] for k_, v_ in before_info.items()})
after_info = {}
for n_ in ('osc', 'vec', 'met', 'spec', 'hist'):
    app.panel_menu_build(n_).invoke(3)  # Info
    after_info[n_] = visible_text(n_)
    app.panel_menu_build(n_).invoke(3)
check('Info off: a window shows none of its text and numbers (title, scales, names, letters), and Info on brings them back', all(v_ == [] for v_ in after_info.values()) and {n_: len(visible_text(n_)) for n_ in before_info} == {n_: len(v_) for n_, v_ in before_info.items()},
      ({k_: v_[:4] for k_, v_ in after_info.items()}, {n_: sorted(visible_text(n_))[:5] for n_ in before_info}, {n_: sorted(v_)[:5] for n_, v_ in before_info.items()}))
app.panel_menu_build('spec').invoke(3)
check('Info off for the spectrum also takes its ranges and dB numbers, and the other windows keep theirs', visible_text('spec') == [] and visible_text('hist') == before_info['hist'] and visible_text('osc') == before_info['osc'], visible_text('spec'))
app.set_spec_mode('spectrogram')
check('the spectrogram has no caption, just its name', app.c.itemcget(app.spec_title, 'text') == 'SPECTROGRAM', app.c.itemcget(app.spec_title, 'text'))
app.set_spec_mode('spectrum')
app.panel_menu_build('met').invoke(3)
app.draw()
check('Info off for the levels: the text block, the balance figure and the numbers are hidden but still kept up to date', app.c.itemcget(app.m_txt, 'state') == 'hidden' and app.c.itemcget(app.bal_lbl, 'state') == 'hidden' and app.c.itemcget(app.m_txt, 'text').startswith('hold'), (app.c.itemcget(app.m_txt, 'state'), app.c.itemcget(app.m_txt, 'text')[:12]))
check('Info is kept in the settings as true or false', (app.save_settings() or True) and json.load(open(m.SETTINGS))['panels']['met']['info'] is False and json.load(open(m.SETTINGS))['panels']['spec']['info'] is False, json.load(open(m.SETTINGS)).get('panels'))
app.panel_opts.clear()
app.refresh_panels()
pf_h = app.panel_frame['hist']
check('with its info on the level history keeps a column for its dB numbers, and a line at the end of it', app.P['hist'][0] - pf_h[0] == app.S(46) and app.gutters['hist'] == app.S(46), (app.P['hist'], pf_h))
app.panel_menu_build('hist').invoke(3)  # Info off
check('with its info off there is no column for numbers (no gap): the graph starts at the left of the window', app.gutters['hist'] == 0 and app.P['hist'][0] == app.panel_frame['hist'][0] and app.gutters['spec'] == app.S(46), (app.P['hist'], app.panel_frame['hist']))
rect_at = lambda n_: [i_ for i_ in app.c.find_all() if app.c.type(i_) == 'rectangle' and tuple(app.c.coords(i_)) == tuple(float(v_) for v_ in (app.panel_frame.get(n_) or app.P[n_]))]
check('every window has a frame while its grid is on', all(len(rect_at(n_)) == 1 for n_ in ('osc', 'vec', 'met', 'spec', 'hist')), {n_: len(rect_at(n_)) for n_ in ('osc', 'vec', 'met', 'spec', 'hist')})
app.panel_menu_build('vec').invoke(2)  # Grid off
app.panel_menu_build('osc').invoke(2)
check('grid off in the normal layout keeps the border of the window (only the lines inside it go): the vectorscope keeps its box', len(rect_at('vec')) == 1 and len(rect_at('osc')) == 1 and len(rect_at('spec')) == 1 and len(rect_at('hist')) == 1 and len(app.c.find_withtag('vgrid')) == 0,
      {n_: len(rect_at(n_)) for n_ in ('osc', 'vec', 'met', 'spec', 'hist')})
base_osc = np.asarray(app.beam_plot('osc').plot.base)
check('...and the frame stays in the oscilloscope picture too, but not its centre line', tuple(base_osc[0, 5]) == rgb_(app.th.grid) and tuple(base_osc[base_osc.shape[0] // 2, 5]) == rgb_(app.th.bg), (tuple(base_osc[0, 5]), tuple(base_osc[base_osc.shape[0] // 2, 5])))
# full screen has a Grid and an Info of its own
app.panel_opts.clear()
app.refresh_panels()
app.zoom_panel('vec')
fm_ = app.panel_menu_build('vec')
check('in full screen the menu says so, and its Grid and Info are the full screen ones (separate from the normal layout)', menu_labels(fm_)[0] == 'Vectorscope (full screen)' and fm_._on[:2] == (True, True), menu_labels(fm_)[0])
fm_.invoke(2)  # Grid, in full screen
check('Grid off in full screen: the settings key is the full screen one, the box round the vectorscope and its lines are gone, the normal layout keeps its own', app.panel_opts == {'vec': {'fs_grid': False}} and not rect_at('vec') and len(app.c.find_withtag('vgrid')) == 0, app.panel_opts)
app.panel_menu_build('vec').invoke(3)  # Info, in full screen
check('Info off in full screen too: the picture is edge to edge (nothing round it, no margin)', app.panel_opts['vec'] == {'fs_grid': False, 'fs_info': False} and app.zoom == 'vec' and app.P['vec'][0] == (app.CW - app.CH) // 2 and app.P['vec'][1] == 0, (app.panel_opts, app.P['vec'], app.CW, app.CH))
app.zoom_panel(None)
check('back in the normal layout everything of the vectorscope is still there: its box, its lines and its letters', len(rect_at('vec')) == 1 and len(app.c.find_withtag('vgrid')) == 3 and app.panel_grid('vec') and app.panel_info('vec'), app.panel_opts)
app.zoom_panel('hist')
app.panel_menu_build('hist').invoke(2)
app.panel_menu_build('hist').invoke(3)
check('an enlarged history with both off: edge to edge, no gap for numbers, no border', app.P['hist'] == (0, 0, app.CW - 1, app.CH - 1) and app.gutters['hist'] == 0 and not [i_ for i_ in app.c.find_all() if app.c.type(i_) == 'rectangle' and app.c.coords(i_)[0] < app.CW], (app.P['hist'], app.CW, app.CH))
app.zoom_panel(None)
check('and the normal layout of the history keeps its numbers, its grid and its border', app.gutters['hist'] == app.S(46) and len(rect_at('hist')) == 1 and app.panel_info('hist') and app.panel_grid('hist'), app.panel_opts)
check('the full screen choices are kept in the settings file and read back', (app.save_settings() or True) and json.load(open(m.SETTINGS))['panels']['hist'] == {'fs_grid': False, 'fs_info': False}
      and m.clean_panel_opts({'osc': {'fs_grid': False, 'fs_info': 'x', 'grid': True}}) == {'osc': {'fs_grid': False, 'grid': True}}, json.load(open(m.SETTINGS)).get('panels'))
app.panel_opts.clear()
app.refresh_panels()
app.panel_opts.clear()
app.refresh_panels()
# the colours
app.ask_color = lambda initial, title: '#12ab34'
app.pick_panel_color('osc', 'left')
th_ = app.th
check('a colour picked for the left of the oscilloscope: its left trace has it, its right trace and the other windows keep the theme colours',
      app.panel_colors('osc') == ('#12ab34', th_.right) and app.beam_plot('osc').plot.luts[0].tolist() == m.beam_palette(th_.bg, '#12ab34', light=True).tolist()
      and app.beam_plot('osc').plot.luts[1].tolist() == m.beam_palette(th_.bg, th_.right, light=True).tolist() and app.panel_colors('spec') == (th_.left, th_.right) and app.panel_colors('hist') == (th_.left, th_.right), app.panel_opts)
check('once the window has a colour of its own, "back to the theme colours" is in its menu (readable, not greyed out)', menu_labels(app.panel_menu_build('osc'))[-1] == 'Back to the theme colours' and str(app.panel_menu_build('osc').entrycget(app.panel_menu_build('osc').index('end'), 'state')) == 'normal', menu_labels(app.panel_menu_build('osc')))
app.ask_color = lambda initial, title: '#ff00ff'
app.pick_panel_color('vec', 'color')
check('a colour picked for the vectorscope (it has one): its beam palette is that colour', app.vec_lut.tolist() == m.beam_palette(app.BG, '#ff00ff').tolist() and app.panel_vec_color() == '#ff00ff', app.panel_opts)
app.ask_color = lambda initial, title: '#00ffaa'
app.pick_panel_color('met', 'right')
lr_txt = {app.c.itemcget(i_, 'text'): app.c.itemcget(i_, 'fill') for i_ in app.c.find_all() if app.c.type(i_) == 'text' and app.c.itemcget(i_, 'text') in (chr(10).join('LLLL'), chr(10).join('RRRR'))}
check('a colour picked for the right of the levels: the level bar and the letters R in the levels text have it', app.panel_colors('met')[1] == '#00ffaa' and lr_txt[chr(10).join('RRRR')] == '#00ffaa' and lr_txt[chr(10).join('LLLL')] == th_.left
      and app.beam_plot('met').plot.luts[1].tolist() == m.beam_palette(th_.bg, '#00ffaa', light=True).tolist(), (lr_txt, app.panel_opts))
app.ask_color = lambda initial, title: 'red'
before_ = {k_: dict(v_) for k_, v_ in app.panel_opts.items()}
app.pick_panel_color('hist', 'left')
check('something that is not a #rrggbb colour is ignored', app.panel_opts == before_, app.panel_opts)
app.save_settings()
saved_ = json.load(open(m.SETTINGS))
check('the choices are kept in the settings file, and read back (anything invalid in it is dropped)', saved_['panels'] == app.panel_opts and m.clean_panel_opts(saved_['panels']) == app.panel_opts
      and m.clean_panel_opts({'osc': {'grid': 'yes', 'left': '#GGGGGG', 'classic': True, 'info': 'no'}, 'bogus': {'grid': False}, 'vec': {'color': '#ABCDEF', 'left': '#123456'}, 'hist': 5}) == {'osc': {'burn': 0.4}, 'vec': {'color': '#abcdef'}}
      and m.clean_panel_opts(None) == {}, (saved_.get('panels'), app.panel_opts))
app.panel_menu_build('osc').invoke(9)  # back to the theme colours
app.reset_panel_colors('vec')
app.reset_panel_colors('met')
check('"back to the theme colours" gives the window the theme colours again, and forgets the choice', app.panel_colors('osc') == (th_.left, th_.right) and app.panel_vec_color() == th_.vec and app.panel_colors('met') == (th_.left, th_.right)
      and not any(k_ in o_ for o_ in app.panel_opts.values() for k_ in ('left', 'right', 'color')), app.panel_opts)
del app.ask_color
app.panel_opts.clear()
app.refresh_panels()
# ---- CRT burn (0 = clean lines, to 3, steps of 0.1) and Line strength (0 to 10) are steppers in the menu of the beam windows
app.go_live()
pump(root, 0.2)
app.panel_opts.clear()
app.refresh_panels()
for n_ in ('osc', 'vec', 'spec', 'hist'):
    app.draw()
bm_ = {n_: app.panel_menu_build(n_) for n_ in ('osc', 'vec', 'spec', 'hist', 'met')}
check('CRT burn and Line strength are stepper rows in the menu of the oscilloscope, vectorscope, spectrum and history; the levels have CRT burn only',
      all(stepper_labels(bm_[n_]) == ['CRT burn', 'Line strength'] for n_ in ('osc', 'vec', 'spec', 'hist')) and stepper_labels(bm_['met']) == ['CRT burn'], [stepper_labels(bm_[n_]) for n_ in bm_])
check('the start: CRT burn 0.4 (the vectorscope 1.0, the levels 1.0 unless the theme is Classic), Line strength 6, none for the levels',
      [app.panel_burn_level(n_) for n_ in ('osc', 'spec', 'hist', 'vec', 'met')] == [0.4, 0.4, 0.4, 1.0, 1.0 if app.th.glow else 0.4] and all(app.panel_strength(n_) == 6 for n_ in ('osc', 'vec', 'spec', 'hist')) and app.panel_strength('met') == 1
      and [m.burn_text(n_) for n_ in (0, 4, 14, 30)] == ['Off', '0.4', '1.4', '3.0'] and [m.strength_text(n_) for n_ in (1, 6, 9, 10)] == ['1', '6', '9', '10'], bm_['osc']._on)
lifts_ = {n_: [sc_.lift for sc_ in app.beam_plot(n_).plot.screens] for n_ in ('osc', 'spec', 'hist', 'met')}
lifts_['vec'] = [app.plots['vec'].plot.screen.lift]
check('the beams are drawn with the Light lift (0.75) and their glow; the level bars as they were', all(abs(v_[0] - 0.75) < 1e-9 for n_, v_ in lifts_.items() if n_ != 'met') and lifts_['met'] == [1.0, 1.0]
      and app.beam_plot('osc').plot.glow == 0.4 and app.plots['vec'].plot.glow == 1.0, lifts_)
# stepping: live, without building the window again
pl_before = app.beam_plot('osc')
mo_ = app.panel_menu_build('osc')
i_burn = mo_.entries.index(mo_.stepper('CRT burn'))
i_str = mo_.entries.index(mo_.stepper('Line strength'))
moved_ = mo_.step(i_burn, 1)
check('a step of CRT burn: 0.5, the beam is drawn with it at once and the picture is not started again; it is in the settings file',
      moved_ and app.panel_burn_level('osc') == 0.5 and app.beam_plot('osc') is pl_before and pl_before.plot.glow == 0.5 and json.load(open(m.SETTINGS))['panels']['osc']['burn'] == 0.5, (app.panel_opts, moved_))
mo_.set_stepper(i_burn, 30)
check('up to 3.0 and no further', app.panel_burn_level('osc') == 3.0 and pl_before.plot.glow == 3.0 and not mo_.step(i_burn, 1) and mo_.stepper('CRT burn')['n'] == 30, app.panel_opts)
mo_.step(i_str, 3)
check('Line strength: 9 lifts the beam with 0.6 at once, the others keep theirs, and it is in the settings file',
      app.panel_strength('osc') == 9 and all(abs(sc_.lift - 0.6) < 1e-9 for sc_ in pl_before.plot.screens) and abs(app.beam_plot('hist').plot.screens[0].lift - 0.75) < 1e-9
      and json.load(open(m.SETTINGS))['panels']['osc']['strength'] == 9 and app.beam_plot('osc') is pl_before, (app.panel_opts, [sc_.lift for sc_ in pl_before.plot.screens]))
mo_.set_stepper(i_str, 0)
check('Line strength 1 (the lowest) is the beam as it is: no lift at all, and it does not go below', app.panel_strength('osc') == 1 and mo_.stepper('Line strength')['n'] == 1 and not mo_.step(i_str, -1) and [sc_.lift for sc_ in pl_before.plot.screens] == [1.0, 1.0], [sc_.lift for sc_ in pl_before.plot.screens])
mo_.set_stepper(i_burn, 0)
mq_ = app.panel_menu_build('osc')
check('CRT burn 0 is clean lines: the window is made again without the beam, and Line strength is not offered', not app.panel_crt('osc') and app.beam_plot('osc').plot.clean and not mo_.visible(mo_.stepper('Line strength')) and not mq_.visible(mq_.stepper('Line strength'))
      and mq_.stepper('CRT burn')['n'] == 0, app.panel_opts)
mo_.set_stepper(i_burn, 5)
check('and back to 0.5: the beam is back, with the strength it had', app.panel_crt('osc') and not app.beam_plot('osc').plot.clean and app.beam_plot('osc').plot.glow == 0.5 and app.panel_strength('osc') == 1 and mo_.visible(mo_.stepper('Line strength')), app.panel_opts)
ml_ = app.panel_menu_build('met')
ml_.set_stepper(ml_.entries.index(ml_.stepper('CRT burn')), 20)
check('the levels step too (2.0)', app.panel_burn_level('met') == 2.0 and app.beam_plot('met').plot.glow == 2.0, app.panel_opts.get('met'))
check('settings: CRT burn is 0 to 3 in tenths, Line strength 1 to 10; the older Off / On / Overburn and Default / Light / Strong choices are read as numbers; anything else is dropped',
      m.clean_panel_opts({'osc': {'burn': 1.26, 'strength': 7}}) == {'osc': {'burn': 1.3, 'strength': 7}} and m.clean_panel_opts({'osc': {'burn': 3.5}}) == {} and m.clean_panel_opts({'osc': {'burn': True, 'strength': 11}}) == {} and m.clean_panel_opts({'osc': {'strength': 0}}) == {}
      and m.clean_panel_opts({'osc': {'crt': False, 'overburn': True}}) == {'osc': {'burn': 0.0}} and m.clean_panel_opts({'osc': {'overburn': True}}) == {'osc': {'burn': 1.0}}
      and m.clean_panel_opts({'osc': {'overburn': False}}) == {'osc': {'burn': 0.4}} and m.clean_panel_opts({'osc': {'glow': True}}) == {'osc': {'burn': 1.0}} and m.clean_panel_opts({'osc': {'classic': True}}) == {'osc': {'burn': 0.4}}
      and m.clean_panel_opts({'osc': {'strength': 'Strong'}}) == {'osc': {'strength': 9}} and m.clean_panel_opts({'osc': {'bold': True}}) == {'osc': {'strength': 6}} and m.clean_panel_opts({'osc': {'bold': 'Off'}}) == {'osc': {'strength': 1}}
      and m.clean_panel_opts({'osc': {'strength': 'Nope'}}) == {})
app.panel_opts.clear()
app.refresh_panels()

# ---- the starting choices of a first run (the tests run with everything on and the first theme; here the shipped ones are checked and tried)
import types
sh_ = m.SHIPPED
th_sh = [t_ for t_ in m.THEMES if t_.name == sh_['theme']][0]
check('the shipped theme is Orange + blue', sh_['theme'] == 'Orange + blue' and th_sh.name == 'Orange + blue', sh_['theme'])
m.PANEL_DEFAULTS.update(sh_['panels'])
try:
    stub_ = types.SimpleNamespace(panel_opts={}, zoom=None, th=th_sh)
    stub_.panel_burn_level = lambda n_: m.App.panel_burn_level(stub_, n_)
    normal_ = {n_: (m.App.panel_grid(stub_, n_), m.App.panel_info(stub_, n_)) for n_ in m.PANELS}
    full_ = {}
    for n_ in m.PANELS:
        stub_.zoom = n_
        full_[n_] = (m.App.panel_grid(stub_, n_), m.App.panel_info(stub_, n_))
    stub_.zoom = None
    check('first run, normal layout: grid and info on everywhere, except the spectrum which starts without its grid', normal_ == {'osc': (True, True), 'vec': (True, True), 'met': (True, True), 'spec': (False, True), 'hist': (True, True)}, normal_)
    check('first run, enlarged: clean (no grid, no info) for the oscilloscope, vectorscope, levels and history; the spectrum has no grid but keeps its range names',
          full_ == {'osc': (False, False), 'vec': (False, False), 'met': (False, False), 'spec': (False, True), 'hist': (False, False)}, full_)
    burn_ = {n_: m.App.panel_burn_level(stub_, n_) for n_ in m.PANELS}
    check('first run: the oscilloscope, spectrum and history start on CRT burn 0.4, the vectorscope and levels on 1.0; every beam window starts on Line strength 6',
          burn_ == {'osc': 0.4, 'vec': 1.0, 'met': 1.0 if th_sh.glow else 0.4, 'spec': 0.4, 'hist': 0.4} and all(m.App.panel_crt(stub_, n_) for n_ in m.PANELS)
          and all(m.App.panel_strength(stub_, n_) == 6 for n_ in ('osc', 'vec', 'spec', 'hist')) and m.App.panel_strength(stub_, 'met') == 1, burn_)
    stub_.panel_opts = {'spec': {'grid': True}, 'osc': {'fs_info': True, 'fs_grid': True}}
    stub_.zoom = 'osc'
    check('a choice made in a window\'s menu wins over the starting one', m.App.panel_grid(stub_, 'spec') is True and m.App.panel_grid(stub_, 'osc') is True and m.App.panel_info(stub_, 'osc') is True and m.App.panel_info(stub_, 'hist') is True, stub_.panel_opts)
    stub_.zoom = None
    check('...and the spectrum\'s own grid choice in the normal layout', m.App.panel_grid(stub_, 'spec') is True)
    # the real window with the shipped choices: every window enlarged and back
    app.panel_opts.clear()
    app.refresh_panels()
    for n_ in ('osc', 'vec', 'hist', 'met', 'spec'):
        app.zoom_panel(n_)
        for _ in range(2):
            app.draw()
            pump(root, 0.05)
        edge_ = app.P[n_] == (0, 0, app.CW - 1, app.CH - 1)
        if n_ == 'vec':  # (square, in the middle)
            edge_ = app.P['vec'][0] == (app.CW - app.CH) // 2 and app.P['vec'][1] == 0
        if n_ == 'met':  # (the levels keep their shape)
            edge_ = True
        check('shipped choices, %s enlarged: %s' % (n_, 'its range names stay, no grid' if n_ == 'spec' else 'clean'),
              (not app.panel_grid(n_) and app.panel_info(n_)) if n_ == 'spec' else (edge_ and not app.panel_grid(n_) and not app.panel_info(n_)), (app.P[n_], app.CW, app.CH))
        app.zoom_panel(None)
    no_error('the shipped choices, every window enlarged')
    sp_ = app.panel_menu_build('spec')
    check('shipped choices, normal layout: the spectrum menu shows Grid off and Info on, the others have both on', sp_._on[:2] == (False, True) and all(app.panel_menu_build(n_)._on[:2] == (True, True) for n_ in ('osc', 'vec', 'hist', 'met')), sp_._on)
    xx0_, yy0_, xx1_, yy1_ = app.P['spec']
    check('shipped choices: no band dividers under the spectrum (its grid is off), the names are there', not [i_ for i_ in app.c.find_withtag('spec') if app.c.type(i_) == 'line' and app.c.coords(i_)[3] > yy1_ + 3] and any(app.c.type(i_) == 'text' for i_ in app.c.find_withtag('spec')))
finally:
    m.PANEL_DEFAULTS.clear()
    app.panel_opts.clear()
    app.refresh_panels()

no_error('after the window menus')
check('live: the timeline and the rows under the transport are collapsed', app.mode == 'live' and app.tl.winfo_manager() == '' and app.clip_row.winfo_manager() == '' and app.cmp_row.winfo_manager() == '', (app.tl.winfo_manager(), app.clip_row.winfo_manager()))

# ---- record
app.rec_toggle()
pump(root, 0.5)
check('recording opens the timeline', app.mode == 'rec' and app.tl.winfo_manager() == 'pack', (app.mode, app.tl.winfo_manager()))
app.tl_key, app.tl_built = None, 0.0
app.draw_timeline()
k_real = app.tl_key
app.tl_key = k_real[:3] + (-1,) + k_real[4:]  # (something about the timeline changed ...)
app.tl_built = time.perf_counter()  # ... just now made
app.draw_timeline()
held = app.tl_key == k_real[:3] + (-1,) + k_real[4:]
app.tl_built = time.perf_counter() - 0.2
app.draw_timeline()
check('recording: the timeline is not made again within 55 ms, and is after that', held and app.tl_key[3] != -1 and app.tl_built > time.perf_counter() - 0.1, (held, app.tl_key[3]))
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


def history_cur(total, cur):
    app.draw_history(peaks[max(0, total - 3100):total], 0.0, total, cur)
    return np.stack([app.hist_pts[0][0], app.hist_pts[0][1]], axis=1)


base_cur = 4000 * hw / 3000.0
pa_, pb_, pc_ = history_cur(4000, base_cur), history_cur(4000, base_cur + 0.25), history_cur(4000, base_cur + 0.5)
check('history: with a position in fractions of a column the whole line moves smoothly (a quarter of a pixel, a half), and every column keeps its height',
      len(pa_) == len(pb_) == len(pc_) and bool(np.allclose(pb_[:, 0] - pa_[:, 0], -0.25)) and bool(np.allclose(pc_[:, 0] - pa_[:, 0], -0.5)) and bool(np.allclose(pa_[:, 1], pc_[:, 1])), (len(pa_), (pb_[:3, 0] - pa_[:3, 0]).tolist()))
check('history: shifted by a fraction, the line still reaches the left edge of the panel and ends within two pixels of the right edge', pa_[0, 0] <= hx0 + 1 and pc_[0, 0] <= hx0 + 1 and hx1 - 2.5 <= pc_[-1, 0] <= hx1 and hx1 - 2.5 <= pa_[-1, 0] <= hx1, (pa_[0, 0], pc_[-1, 0], pa_[-1, 0], hx0, hx1))
steps_c = [history_cur(4000 + k_, (4000 + k_) * hw / 3000.0)[-1, 0] for k_ in range(0, 60)]
check('history: as the position creeps on, the line moves left with it and only ever steps back when a column is added (never forwards)', all(b_ - a_ < 1e-9 or abs(b_ - a_ - 1.0) < 1.0 for a_, b_ in zip(steps_c, steps_c[1:])), steps_c[:8])
app.pos_clock = None
sp_a = app.smooth_pos(48000, True)
sp_b = app.smooth_pos(48000, True)
sp_c = app.smooth_pos(48000 + 2 * m.SR, True)
sp_d = app.smooth_pos(123, False)
check('the history clock: the first call gives the real position, a repeat runs on a little with the time, a jump or a stopped sound gives the real position again',
      sp_a == 48000.0 and 48000.0 <= sp_b < 48000.0 + 0.05 * m.SR and sp_c == 48000 + 2 * m.SR and sp_d == 123.0, (sp_a, sp_b, sp_c, sp_d))
app.pos_clock = None
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
    check('theme %s: the L and R letters of the levels text are in the left and right channel colours' % th.name, sorted(app.c.itemcget(i, 'fill') for i in app.c.find_all() if app.c.type(i) == 'text' and app.c.itemcget(i, 'text') in (chr(10).join('LLLL'), chr(10).join('RRRR'))) == sorted([app.CL, app.CR]) and (app.CL, app.CR) == (th.left, th.right), (app.CL, app.CR, th.left, th.right))
    check('theme %s: the level bars and the balance bars are drawn in the two channel colours' % th.name, app.plots['met'].plot.luts[0].tolist() == m.beam_palette(th.bg, th.left, light=True).tolist() and app.plots['met'].plot.luts[1].tolist() == m.beam_palette(th.bg, th.right, light=True).tolist(), th.name)
check('cycling through every theme comes back to the first', app.th.name == first)
app.cycle_theme()
pump(root, 0.6)
check('a theme with glow draws its graphs as phosphor pictures: the oscilloscope, spectrum and history at the low light level, the vectorscope and the levels at the high one', app.th.glow and all(app.plots[n_].plot.glow == 0.4 for n_ in ('osc', 'spec', 'hist')) and app.plots['vec'].plot.glow == 1.0 and app.plots['met'].plot.glow == 1.0 and app.plots['hist'].plot.blend == 'white' and all(app.photos.get(n_) is not None for n_ in ('osc', 'spec', 'hist')), (app.th.name, sorted(app.plots), sorted(app.photos)))
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
check('Classic is as it was: crisp lines (a weaker halo) everywhere but the vectorscope, which keeps its glow', not app.th.glow and all(app.plots[n_].plot.glow < 0.5 for n_ in ('osc', 'spec', 'hist', 'met')) and app.plots['vec'].plot.glow == 1.0, (app.th.glow, {n_: app.plots[n_].plot.glow for n_ in app.plots}))
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
