import ctypes, cProfile, pstats, sys, time, tkinter as tk
import support as T
from support import m
m.App.THREADED = True
ctypes.windll.winmm.timeBeginPeriod(1)
T.sandbox()
cap = T.SynthCapture(); cap.start()
root = tk.Tk(); root.attributes('-alpha', 0.0); root.geometry('1916x1200+0+0')
app = m.App(root, cap)
T.mute_keys(root)
root.after(1200, root.quit); root.mainloop()
app.k = 1.55; app.build_ui(); root.geometry('1916x1200+0+0')
root.after(1500, root.quit); root.mainloop()
pr = cProfile.Profile()
root.after(6000, root.quit)
pr.enable(); root.mainloop(); pr.disable()
st = pstats.Stats(pr)
import io
buf = io.StringIO()
st2 = pstats.Stats(pr, stream=buf); st2.sort_stats('cumulative').print_stats(40)
lines = [l for l in buf.getvalue().splitlines() if 'pc_audio_scope' in l or 'tkinter' in l or 'ImageTk' in l or 'PIL' in l]
for l in lines[:30]: print(l[:60].strip() + ' ... ' + l.split(chr(92))[-1][:70])
cap.stop = True; root.destroy()
