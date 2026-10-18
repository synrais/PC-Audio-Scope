"""recordings on disk: saving, the JSON sidecar, and loading WAVs in other formats"""
import json
import os
import wave

import numpy as np

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
def write_pcm(path, sr, raw, width, channels=1):
    with wave.open(path, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(sr)
        w.writeframes(raw)


p16 = os.path.join(tmp, 'int16_mono_44k.wav')
n44 = int(44100 * 2)
write_pcm(p16, 44100, (0.5 * np.sin(2 * np.pi * 440 * np.arange(n44) / 44100) * 32767).astype('<i2').tobytes(), 2)
x = m.Clip.load(p16)
check('mono 44.1 kHz int16 loads as 48 kHz stereo', x.data.shape == (SR * 2, 2) and abs(x.peak - 0.5) < 0.01 and np.allclose(x.data[:, 0], x.data[:, 1]), (x.data.shape, x.peak))
f_out = np.fft.rfftfreq(len(x.data), 1.0 / SR)
check('and the 440 Hz tone is still at 440 Hz', abs(f_out[int(np.argmax(np.abs(np.fft.rfft(x.data[:, 0]))))] - 440.0) < 1.0)
p8 = os.path.join(tmp, 'uint8.wav')
write_pcm(p8, SR, (128 + 100 * np.sin(2 * np.pi * 440 * t)).astype(np.uint8).tobytes(), 1)
check('uint8 loads', abs(m.Clip.load(p8).peak - 100 / 128.0) < 0.02)
p24 = os.path.join(tmp, 'int24.wav')
v24 = (0.4 * np.sin(2 * np.pi * 440 * t) * 8388607).astype(np.int32)
raw24 = np.stack([v24 & 255, (v24 >> 8) & 255, (v24 >> 16) & 255], axis=1).astype(np.uint8).tobytes()
write_pcm(p24, SR, raw24, 3)
check('24-bit loads', abs(m.Clip.load(p24).peak - 0.4) < 0.01, m.Clip.load(p24).peak)
p32 = os.path.join(tmp, 'int32_stereo.wav')
v32 = np.stack([0.3 * np.sin(2 * np.pi * 440 * t), 0.6 * np.sin(2 * np.pi * 440 * t)], axis=1)
write_pcm(p32, SR, (v32 * 2147483647).astype('<i4').tobytes(), 4, 2)
y = m.Clip.load(p32)
check('32-bit stereo loads with both channels', abs(float(np.abs(y.data[:, 0]).max()) - 0.3) < 0.01 and abs(float(np.abs(y.data[:, 1]).max()) - 0.6) < 0.01)
pf = os.path.join(tmp, 'float.wav')
m.write_wav(pf, SR, np.stack([tone, tone], axis=1).astype(np.float32))
check('float32 loads', abs(m.Clip.load(pf).peak - 0.25) < 1e-4)
pm = os.path.join(tmp, 'float_mono.wav')
m.write_wav(pm, SR, tone.astype(np.float32))
check('mono float32 loads as stereo', m.Clip.load(pm).data.shape == (SR * 2, 2))
rate, back_raw = m.read_wav(pf)
check('write_wav / read_wav round trip is exact', rate == SR and back_raw.dtype == np.float32 and np.array_equal(back_raw[:, 0], tone.astype(np.float32)))
open(os.path.join(tmp, 'junk.wav'), 'wb').write(b'not a wav file at all')
try:
    m.read_wav(os.path.join(tmp, 'junk.wav'))
    check('a file that is not a WAV is refused', False)
except ValueError:
    check('a file that is not a WAV is refused', True)

# slice and statistics
part = clip.slice(0.5, 1.0)
check('slice is the requested length', abs(part.duration - 0.5) < 1e-3, part.duration)
check('integrated loudness is cached per offset', clip.integrated(0.0) == clip.integrated(0.0) and clip.integrated(6.0) > clip.integrated(0.0))
T.finish()
