"""helpers shared by the test scripts: loads the app, a stand-in for the sound card, synthetic clips, a tiny check() reporter"""
import os
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pc_audio_scope as m                  # noqa: E402
from pc_audio_scope import SR, BLOCK        # noqa: E402
m.App.THREADED = False                      # the graphs are drawn on the calling thread, so a test sees the picture at once (window_fit.py and beam.py test the threads)



def _menu_index(self, what):
    return len(self.entries) - 1 if what == 'end' else int(what)


def _menu_type(self, i):
    return self.entries[i]['kind']


def _menu_entrycget(self, i, opt):
    e = self.entries[i]
    th = self.app.th
    got = {'label': e.get('label', ''), 'image': str(e['image']) if e.get('image') is not None else '', 'compound': 'left', 'state': 'normal',
           'foreground': th.accent_hi if e.get('heading') else th.fg, 'font': '{Segoe UI} 9 bold' if e.get('heading') else '{Segoe UI} 9'}
    return got[opt]


m.PanelMenu.index, m.PanelMenu.type, m.PanelMenu.entrycget = _menu_index, _menu_type, _menu_entrycget  # the calls of a tk.Menu that the tests make on a menu of ours

fails = []


def check(name, cond, extra=''):
    line = ('PASS ' if cond else 'FAIL ') + name + ((' - ' + str(extra)) if extra else '')
    print(line.encode('ascii', 'replace').decode())
    if not cond:
        fails.append(name)


def finish():
    print('\nFAILED: %s' % fails if fails else '\nALL PASSED')
    sys.exit(1 if fails else 0)


def sandbox():
    """point the app's settings and recordings at a temporary folder; returns it"""
    tmp = tempfile.mkdtemp(prefix='scope_test_')
    m.SETTINGS = os.path.join(tmp, 'settings.json')
    m.REC_DIR = os.path.join(tmp, 'rec')
    # the tests check the layout logic with everything on and the first theme; the shipped starting choices are kept in m.SHIPPED and checked (and tried) in functional.py
    m.SHIPPED = {'panels': {k: dict(v) for k, v in m.PANEL_DEFAULTS.items()}, 'theme': m.DEFAULT_THEME}
    m.PANEL_DEFAULTS.clear()
    m.DEFAULT_THEME = m.THEMES[0].name
    return tmp


def mute_keys(root):
    """the tests drive the app by method calls; unbind the keys so that typing on the keyboard while they run cannot change what they are testing"""
    for seq in root.bind():
        if 'Configure' not in seq:
            root.unbind(seq)


def pump(root, sec):
    """run the Tk event loop (and so the app's own timers) for sec seconds"""
    t0 = time.time()
    while time.time() - t0 < sec:
        root.update()
        time.sleep(0.02)


class SynthCapture(m.Capture):
    """stands in for the sound card: left 440 Hz quiet, right 660 Hz louder, a clipped burst every 3 s;
    or, when `src` = (array, start frame) is set, that recording played back in real time"""
    def __init__(self):
        super().__init__()
        self.src = None

    def run(self):
        self.device = 'synthetic test signal'
        t = 0
        t0 = time.time()
        while not self.stop:
            n = BLOCK
            if self.src is not None:
                data, start = self.src
                blk = data[start + t:start + t + n]
                if len(blk) < n:
                    blk = np.pad(blk, ((0, n - len(blk)), (0, 0)))
                self.push(blk.astype(np.float32))
            else:
                x = np.arange(t, t + n) / SR
                burst = (time.time() - t0) % 3 > 2.5
                left = 0.05 * np.sin(2 * np.pi * 440 * x) + 0.01 * np.random.randn(n)
                right = (0.35 if burst else 0.15) * np.sin(2 * np.pi * 660 * x)
                if burst:
                    right = np.clip(right * 4, -0.9, 0.9)
                self.push(np.stack([left, right], axis=1).astype(np.float32))
            t += n
            time.sleep(BLOCK / SR)


def make_synthetic_clips():
    """two recordings: a chime that lines up, then game sound that starts 1.9 s later in B (quieter, with a corrupted stretch)"""
    def band(x, lo, hi):
        spec = np.fft.rfft(x)
        f = np.fft.rfftfreq(len(x), 1.0 / SR)
        spec[(f < lo) | (f > hi)] = 0
        return np.fft.irfft(spec, len(x))

    def burst(sec, seed):
        r = np.random.default_rng(seed)
        x = band(r.standard_normal(int(sec * SR)), 200, 6000)
        env = np.abs(band(r.standard_normal(len(x)), 0, 3)) + 0.2
        y = x * env
        return y / np.abs(y).max()

    chime, game = burst(5, 1), burst(14, 2)
    bad = game.copy()
    bad[int(6 * SR):int(8 * SR)] = burst(2, 99)
    a = np.concatenate([chime, np.zeros(4 * SR), game]) * 0.5
    b = np.concatenate([chime, np.zeros(int(4 * SR + 1.9 * SR)), bad]) * 0.25
    n = max(len(a), len(b))
    a, b = np.pad(a, (0, n - len(a))), np.pad(b, (0, n - len(b)))
    clip_a = m.Clip(np.stack([a, a * 0.9], axis=1) * 10 ** (-19 / 20), -19.0, name='original.wav')
    clip_b = m.Clip(np.stack([b, b * 0.9], axis=1) * 10 ** (-25 / 20), -25.0, name='v7.wav')
    return clip_a, clip_b


def band(x, lo, hi):
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / SR)
    spec[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(spec, len(x))


def demo_audio(seed=1, sec=24.0):
    """a short stereo piece that gives every panel something to show: pads detuned between the channels (a rotating figure on the vectorscope) that pump with the kick,
    plucks and hats panned about, kick and bass in the centre, a drop at 12 s, and a riser of independent noise in each channel (a round cloud on the vectorscope)"""
    r = np.random.default_rng(seed)
    n = int(sec * SR)
    t = np.arange(n) / SR

    def gate(a, b):
        return np.clip(np.minimum((t - a) / 0.08, (b - t) / 0.08), 0.0, 1.0)

    full = np.maximum(gate(6.0, 12.0), gate(13.2, sec))
    drums = full
    plucks = np.maximum(gate(3.0, 12.0), gate(13.2, sec))
    hats = np.maximum(gate(9.0, 12.0), gate(13.2, sec))
    beat = 0.6
    left, right = np.zeros(n), np.zeros(n)
    chords = [(220.00, 261.63, 329.63), (174.61, 220.00, 261.63), (196.00, 246.94, 293.66), (164.81, 207.65, 246.94)]
    seg = int(6 * SR)
    for i, notes in enumerate(chords):
        a, b = i * seg, min(n, (i + 1) * seg)
        k = np.arange(b - a)
        env = np.minimum(1.0, np.minimum(k / (0.6 * SR), (b - a - k) / (0.9 * SR)))
        tt = t[a:b]
        for j, f in enumerate(notes):
            left[a:b] += 0.11 * env * (np.sin(2 * np.pi * f * 0.997 * tt) + 0.4 * np.sin(2 * np.pi * 2 * f * 0.997 * tt + j))
            right[a:b] += 0.11 * env * (np.sin(2 * np.pi * f * 1.003 * tt + 1.3) + 0.4 * np.sin(2 * np.pi * 2 * f * 1.003 * tt + 2 * j))
    duck = 1.0 - 0.6 * np.exp(-(t % beat) / 0.14) * drums  # the pads pump with the kick
    fade = np.clip(t / 2.5, 0.0, 1.0)
    left, right = left * duck * fade, right * duck * fade
    for k in range(int(sec / beat)):  # kick, centre
        a = int(k * beat * SR)
        m_ = min(int(0.35 * SR), n - a)
        if m_ <= 0:
            break
        tk = np.arange(m_) / SR
        kick = 0.6 * drums[a] * np.sin(2 * np.pi * (50 + 90 * np.exp(-tk * 30)) * tk) * np.exp(-tk * 9)
        left[a:a + m_] += kick
        right[a:a + m_] += kick
    for i, f in enumerate((55.0, 43.65, 49.0, 41.2)):  # bass, centre
        a, b = i * seg, min(n, (i + 1) * seg)
        bass = 0.17 * np.sin(2 * np.pi * f * t[a:b]) * (0.6 + 0.4 * np.sin(2 * np.pi * 1.6667 * t[a:b])) * drums[a:b]
        left[a:b] += bass
        right[a:b] += bass
    for k in range(int(sec / (beat / 2))):  # plucks and hats, panned about
        a = int(k * beat / 2 * SR)
        m_ = min(int(0.45 * SR), n - a)
        if m_ <= 0:
            break
        f = chords[min(len(chords) - 1, a // seg)][k % 3] * 2 * (2 if k % 4 == 3 else 1)
        tp = np.arange(m_) / SR
        pluck = 0.4 * plucks[a] * (np.sin(2 * np.pi * f * tp) + 0.3 * np.sin(2 * np.pi * 3 * f * tp)) * np.exp(-tp * 7)
        pan = 0.5 + 0.45 * np.sin(k * 1.1)
        left[a:a + m_] += pluck * (1 - pan)
        right[a:a + m_] += pluck * pan
        if k % 2:
            mh = min(int(0.05 * SR), n - a)
            hat = np.diff(r.standard_normal(mh + 1)) * np.exp(-np.arange(mh) / (0.012 * SR)) * 0.22 * hats[a]
            gl = 1.0 if (k // 2) % 2 == 0 else 0.35
            left[a:a + mh] += hat * gl
            right[a:a + mh] += hat * (1.35 - gl)
    a = int(18 * SR)  # the riser: independent noise in each channel, softly band-limited
    f = np.fft.rfftfreq(n - a, 1.0 / SR)
    soft = np.where((f > 300) & (f < 12000), 1.0 / (1.0 + (f / 3500.0) ** 2), 0.0)
    ramp = (np.arange(n - a) / float(n - a)) ** 2.5 * 0.5
    left[a:] += np.fft.irfft(np.fft.rfft(r.standard_normal(n - a)) * soft, n - a) * ramp * 9
    right[a:] += np.fft.irfft(np.fft.rfft(r.standard_normal(n - a)) * soft, n - a) * ramp * 9
    out = np.stack([left, right], axis=1)
    return out / np.abs(out).max() * 0.7


def faulty_demo():
    """the demo piece with one fault of every kind, each in one channel only: [(time s, channel, kind)] says where
    the right channel blasts (5 s) and runs away in DC (8 to 12 s), the left channel steps in DC (14 s), both drop out (16 s), the right stays on one value (17.5 s),
    the left has a click (18.5 s) and clips (20 s)"""
    x = demo_audio(1).copy()
    r = np.random.default_rng(11)
    s5 = int(5 * SR)
    x[s5:s5 + int(3.0 * SR), 1] = np.clip(r.standard_normal(int(3.0 * SR)) * 0.5, -0.95, 0.95)  # blast in the right channel
    x[int(8 * SR):int(12 * SR), 1] += 0.25  # right DC offset
    x[int(14 * SR):int(19 * SR), 0] += 0.18  # left DC step and offset
    x[int(16 * SR):int(16.8 * SR)] = 0.0  # both channels drop out
    x[int(17.5 * SR):int(17.5 * SR) + 300, 1] = 0.3  # the right channel stuck
    x[int(18.5 * SR), 0] += 0.8  # a click
    x[int(20 * SR):int(20.4 * SR), 0] = np.clip(x[int(20 * SR):int(20.4 * SR), 0], -0.05, 0.05)  # the left clips (flat tops)
    return x, [(5.0, 'R', 'blast'), (8.0, 'R', 'dc_step'), (14.0, 'L', 'dc_step'), (16.0, 'both', 'silence'), (17.5, 'R', 'frozen'), (18.5, 'L', 'click'), (20.0, 'L', 'clipping')]
