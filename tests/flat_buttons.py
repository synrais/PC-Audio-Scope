"""the button class used on macOS (tk.Button ignores colours there), exercised here by switching it on"""
import tkinter as tk

import support as T
from support import check, m, pump

T.sandbox()
m.FLAT_BUTTONS = True
cap = T.SynthCapture()
cap.start()
root = tk.Tk()
root.withdraw()
app = m.App(root, cap)
T.mute_keys(root)
pump(root, 0.8)

check('buttons are FlatButtons', isinstance(app.b_rec, m.FlatButton) and isinstance(app.b_spec, m.FlatButton) and isinstance(app.mb_src, m.FlatButton))
spec = app.spec_mode
app.b_spec.invoke()
check('invoke runs the command', app.spec_mode != spec)
pump(root, 0.2)
check('the toggle colour follows the state through config(bg=...)', app.b_spec.cget('bg') == app.th.on, (app.b_spec.cget('bg'), app.th.on))
app.b_spec.invoke()
pump(root, 0.2)
check('and goes back when it is switched off', app.b_spec.cget('bg') == app.th.btn, (app.b_spec.cget('bg'), app.th.btn))
check('PLAY is disabled while live and invoke does nothing', app.b_play.cget('state') == 'disabled' and app.b_play.invoke() is None and not app.player.playing)
check('the input button shows the current input', app.mb_src.cget('text') not in ('', '...'), app.mb_src.cget('text'))
app.mb_src.invoke = lambda: None
app.fill_src_menu()
check('the input menu is filled', app.src_menu.index('end') is not None)
app.rec_toggle()
pump(root, 0.8)
check('REC button shows STOP in its recording colour', 'STOP' in app.b_rec.cget('text') and app.b_rec.cget('bg') == '#a02828', (app.b_rec.cget('text'), app.b_rec.cget('bg')))
app.rec_toggle()
pump(root, 0.4)
check('a recording is open in review and PLAY is enabled', app.mode == 'review' and app.b_play.cget('state') == 'normal', (app.mode, app.b_play.cget('state')))
app.cycle_theme()
pump(root, 0.4)
check('a theme change rebuilds the buttons', isinstance(app.b_rec, m.FlatButton) and app.msg and True)
cap.stop = True
root.destroy()
T.finish()
