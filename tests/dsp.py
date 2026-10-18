"""checks of the signal analysis functions in pc_audio_scope against known signals"""
import numpy as np

from support import SR, BLOCK, check, finish, make_synthetic_clips, m as dsp


def sine(freq, amp_db, sec=10.0, left=True, right=True):
    x = np.arange(int(sec * SR)) / SR
    y = (10 ** (amp_db / 20)) * np.sin(2 * np.pi * freq * x)
    return np.stack([y if left else 0 * y, y if right else 0 * y], axis=1).astype(np.float32)


# loudness: BS.1770 reference points
st = sine(997, -20)
li = dsp.integrated(dsp.kweight_blocks(st))
check('stereo 997 Hz sine at -20 dBFS reads -20.0 LUFS', abs(li - (-20.0)) < 0.05, li)
li = dsp.integrated(dsp.kweight_blocks(sine(997, -20, right=False)))
check('the same sine in the left channel only reads -23.0 LUFS', abs(li - (-23.01)) < 0.05, li)
check('offset_db is added to the reading', abs(dsp.integrated(dsp.kweight_blocks(st), 6.0) - (-14.0)) < 0.05)
check('short-term loudness agrees on a steady tone', abs(dsp.short_term(dsp.kweight_blocks(st)) - (-20.0)) < 0.05)
check('silence has no integrated loudness', dsp.integrated(dsp.kweight_blocks(np.zeros((SR * 5, 2), np.float32))) is None)
check('less than 400 ms has no integrated loudness', dsp.integrated(dsp.kweight_blocks(sine(997, -20, sec=0.3))) is None)

# the streaming meter and the whole-clip analysis give the same numbers
kw = dsp.KWeight()
stream = np.array([kw.energy(st[i * BLOCK:(i + 1) * BLOCK]) for i in range(300)])
batch = dsp.kweight_blocks(st[:300 * BLOCK])
check('streaming K-weighting equals the whole-clip K-weighting', np.allclose(stream, batch, rtol=1e-6, atol=1e-12), float(np.abs(stream - batch).max()))

# gating: a quiet passage under the relative gate must not pull the reading down
loud, quiet = sine(997, -20, sec=10), sine(997, -50, sec=10)
mixed = dsp.integrated(dsp.kweight_blocks(np.concatenate([loud, quiet])))
check('quiet passage below the relative gate is ignored', abs(mixed - (-20.0)) < 0.1, mixed)

# stereo correlation
rng = np.random.default_rng(0)
a, b = rng.standard_normal(48000), rng.standard_normal(48000)
check('correlation +1 for identical channels', abs(dsp.correlation(a, a) - 1.0) < 1e-9)
check('correlation -1 for opposite phase', abs(dsp.correlation(a, -a) + 1.0) < 1e-9)
check('correlation about 0 for unrelated channels', abs(dsp.correlation(a, b)) < 0.03, dsp.correlation(a, b))
check('correlation is None for silence', dsp.correlation(np.zeros(100), np.zeros(100)) is None)

# clipping detection
clean = sine(440, -6, sec=0.5)
clipped = np.clip(sine(440, 0, sec=0.5) * 3, -0.8, 0.8)
check('a clean sine has no flat tops', not any(dsp.block_flags(clean[:BLOCK])) and not dsp.analyze(clean)[1].any())
check('a clipped sine is flagged in both views', all(dsp.block_flags(clipped[:BLOCK])) and dsp.analyze(clipped)[1].all())
peaks, flat = dsp.analyze(sine(1000, -12, sec=1.0))
check('peaks are one value per 10 ms block', peaks.shape == (100, 2) and abs(dsp.db(float(peaks.max())) - (-12.0)) < 0.2, peaks.shape)

# spectrogram: a 1 kHz tone at -20 dBFS lands in the band that covers 1 kHz
col = dsp.sg_column(sine(1000, -20, sec=0.2)[:, 0].astype(np.float64))
band = int(np.argmax(col))
lo = np.logspace(np.log10(30), np.log10(20000), dsp.SG_BANDS + 1)
check('spectrogram column has one value per band', len(col) == dsp.SG_BANDS)
check('1 kHz peaks in the band that contains 1 kHz', lo[band] <= 1000 <= lo[band + 1] * 1.03, (lo[band], lo[band + 1]))
check('and reads about -20 dBFS', -21.5 < col[band] < -19.5, col[band])
full = dsp.sg_full(sine(1000, -20, sec=2.0)[:, 0].astype(np.float64))
check('whole-clip spectrogram matches the single column', full.shape[1] == dsp.SG_BANDS and int(np.argmax(full[5])) == band, full.shape)

# volume compensation and placement helpers
check('comp undoes the recorded Windows volume', abs(float(dsp.comp(np.ones((1, 2)), -20.0)[0, 0]) - 10.0) < 1e-9)
check('comp leaves unknown volume alone', float(dsp.comp(np.ones((1, 2)), None)[0, 0]) == 1.0)
placed = dsp.place(np.ones((10, 2), np.float32), 5, 20)
check('place puts a clip at its start frame', placed[:5].sum() == 0 and placed[5:15].min() == 1 and placed[15:].sum() == 0)
placed = dsp.place(np.arange(20, dtype=np.float32).reshape(10, 2), -2, 6)
check('place cuts a clip that starts before the axis', placed.shape == (6, 2) and placed[0, 0] == 4.0)

# alignment of two recordings
ca, cb = make_synthetic_clips()
lag, score = dsp.auto_align(ca.data, cb.data, ca.vol_db, cb.vol_db)
check('auto-align finds the 1.9 s offset', abs(lag - 1.9) < 0.001 and score > 0.9, (lag, score))
lag, score = dsp.auto_align(ca.data, cb.data, ca.vol_db, cb.vol_db, a_range=(0.5, 4.5))
check('auto-align on the chime alone finds zero offset', abs(lag) < 0.001, (lag, score))
lag, score = dsp.auto_align(ca.data, np.zeros_like(cb.data))
check('auto-align against silence gives a zero score', score < 0.05, score)

# window statistics on the aligned pair
total = len(ca.data)
pb = dsp.place(cb.data, int(round(-1.9 * SR)), total)
st = dsp.window_stats(dsp.comp(ca.data, ca.vol_db), dsp.comp(pb, cb.vol_db))
t = st['win_t']
good = (t > 11) & (t < 14)
bad = (t > 14.4) & (t < 16.4)
check('aligned game sound matches', float(np.nanmean(st['sim'][good])) > 0.95, float(np.nanmean(st['sim'][good])))
check('the corrupted stretch is found', float(np.nanmin(st['sim'][bad])) < 0.5, float(np.nanmin(st['sim'][bad])))
check('level difference B-A is about -6 dB', abs(st['level_db'] - (-6.0)) < 1.0, st['level_db'])
check('identical recordings null to nothing', dsp.window_stats(ca.data, ca.data)['null_db'] < -100)

finish()
