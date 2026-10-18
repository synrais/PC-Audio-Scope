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
    from scipy.signal import butter, lfilter

    def burst(sec, seed):
        r = np.random.default_rng(seed)
        x = r.standard_normal(int(sec * SR))
        b, a = butter(2, [200 / (SR / 2), 6000 / (SR / 2)], 'band')
        x = lfilter(b, a, x)
        env = np.abs(lfilter(*butter(1, 3 / (SR / 2)), r.standard_normal(len(x)))) + 0.2
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
