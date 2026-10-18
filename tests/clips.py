"""recordings on disk: saving, the JSON sidecar, and loading WAVs in other formats"""
import json
import os

import numpy as np
from scipy.io import wavfile

import support as T
from support import check, m, SR

tmp = T.sandbox()
t = np.arange(SR * 2) / SR
tone = 0.25 * np.sin(2 * np.pi * 440 * t)

# save and load round trip, with markers, selection and the Windows volume it was recorded at
clip = m.Clip(np.stack([tone, tone * 0.5], axis=1), -17.5, markers=[{'t': 0.5, 'name': 'M1'}], sel=(0.2, 0.9))
path = os.path.join(tmp, 'clip.wav')
clip.save(path)
check('sidecar written next to the wav', os.path.exists(os.path.join(tmp, 'clip.json')))
back = m.Clip.load(path)
check('samples survive a round trip', np.allclose(back.data, clip.data, atol=1e-6))
check('volume, markers and selection come back', back.vol_db == -17.5 and back.markers == [{'t': 0.5, 'name': 'M1'}] and back.sel == (0.2, 0.9), (back.vol_db, back.markers, back.sel))
check('peak and duration', abs(back.peak - 0.25) < 1e-3 and abs(back.duration - 2.0) < 1e-6, (back.peak, back.duration))

# a missing or damaged sidecar is not an error
os.remove(os.path.join(tmp, 'clip.json'))
check('no sidecar: loads with no volume', m.Clip.load(path).vol_db is None)
open(os.path.join(tmp, 'clip.json'), 'w').write('{not json')
check('damaged sidecar: loads with no volume', m.Clip.load(path).vol_db is None)

# other WAV formats
p16 = os.path.join(tmp, 'int16_mono_44k.wav')
n44 = int(44100 * 2)
wavfile.write(p16, 44100, (0.5 * np.sin(2 * np.pi * 440 * np.arange(n44) / 44100) * 32767).astype(np.int16))
x = m.Clip.load(p16)
check('mono 44.1 kHz int16 loads as 48 kHz stereo', x.data.shape == (SR * 2, 2) and abs(x.peak - 0.5) < 0.01 and np.allclose(x.data[:, 0], x.data[:, 1]), (x.data.shape, x.peak))
p8 = os.path.join(tmp, 'uint8.wav')
wavfile.write(p8, SR, (128 + 100 * np.sin(2 * np.pi * 440 * t)).astype(np.uint8))
check('uint8 loads', abs(m.Clip.load(p8).peak - 100 / 128.0) < 0.02)
pf = os.path.join(tmp, 'float.wav')
wavfile.write(pf, SR, np.stack([tone, tone], axis=1).astype(np.float32))
check('float32 loads', abs(m.Clip.load(pf).peak - 0.25) < 1e-4)

# slice and statistics
part = clip.slice(0.5, 1.0)
check('slice is the requested length', abs(part.duration - 0.5) < 1e-3, part.duration)
check('integrated loudness is cached per offset', clip.integrated(0.0) == clip.integrated(0.0) and clip.integrated(6.0) > clip.integrated(0.0))
T.finish()
