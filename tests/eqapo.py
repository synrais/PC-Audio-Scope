"""undoing a system equaliser (Equalizer APO): reading its configuration for one output, the exact inverse, and the stream filter"""
import os
import tempfile

import numpy as np

import support as T
from support import check, m

SR = m.SR
FIIO = ('{0.0.0.00000000}.{5ed2568b-d772-4072-b578-de7a5752371b}', 'Speakers (2- FiiO Q series)')
OTHER = ('{0.0.0.00000000}.{a04a2195-048c-406b-a2d4-d458275dc5b4}', 'Odyssey G93SC (NVIDIA High Definition Audio)')

# ---- which output a Device: line selects
check('Device: all selects every output', m.eq_device_match('all', *FIIO) and m.eq_device_match('all', *OTHER))
check('Device: a name with the {guid} selects by the guid, not by the words', m.eq_device_match('Speakers FiiO Q series {5ed2568b-d772-4072-b578-de7a5752371b}', *FIIO)
      and not m.eq_device_match('Speakers FiiO Q series {5ed2568b-d772-4072-b578-de7a5752371b}', *OTHER))
check('Device: a part of the name selects by its words', m.eq_device_match('FiiO Q', *FIIO) and not m.eq_device_match('FiiO Q', *OTHER))

# ---- reading the configuration (with an include, a device that does not match, an OFF filter, and something that cannot be undone)
tmp = tempfile.mkdtemp()
NL = chr(10)
open(os.path.join(tmp, 'sub.txt'), 'w').write('Filter 1: ON LSC Fc 105.0 Hz Gain 16.6 dB Q 0.70' + NL + 'Filter 2: ON PK Fc 53.8 Hz Gain -11.9 dB Q 0.41' + NL)
open(os.path.join(tmp, 'config.txt'), 'w').write(NL.join([
    '# a comment',
    'Device: Speakers FiiO Q series {5ed2568b-d772-4072-b578-de7a5752371b}',
    'Preamp: -10.39 dB',
    'Include: sub.txt',
    'Device: Microphone Yeti {f03bbdb9-4fe3-4c25-b220-8c8c07a283f4}',
    'Filter 1: ON PK Fc 1000 Hz Gain 5 dB Q 1',
    'VSTPlugin: Library "x.dll"',
    'Device: all',
    'Filter: OFF PK Fc 2000 Hz Gain 3 dB Q 1', '']))
out = dict(preamp=0.0, filters=[], unsupported=[], files=[])
m.eqapo_read(os.path.join(tmp, 'config.txt'), FIIO[0], FIIO[1], out)
check('the config for the FiiO output: its preamp, the two filters of the included file, nothing else',
      out['preamp'] == -10.39 and out['filters'] == [('LSC', 105.0, 16.6, 0.7), ('PK', 53.8, -11.9, 0.41)] and not out['unsupported'] and len(out['files']) == 2, out)
out = dict(preamp=0.0, filters=[], unsupported=[], files=[])
m.eqapo_read(os.path.join(tmp, 'config.txt'), OTHER[0], OTHER[1], out)
check('the config for another output: nothing (the microphone plugin is not counted, an OFF filter is not a filter)', out['preamp'] == 0.0 and not out['filters'] and not out['unsupported'], out)
fir, note, files = m.eq_undo_for(*FIIO, config_dir=tmp, mix_rate=96000)
check('eq_undo_for the FiiO output gives a filter and says so', fir is not None and note == 'Equalizer APO undone' and len(fir.fir.taps) == 4096, note)
fir_o, note_o, _ = m.eq_undo_for(*OTHER, config_dir=tmp, mix_rate=48000)
check('eq_undo_for another output does nothing', fir_o is None and note_o == '', note_o)
open(os.path.join(tmp, 'config.txt'), 'a').write('Device: all' + NL + 'Filter: ON LP Fc 1000 Hz Q 0.7' + NL)
fir_u, note_u, _ = m.eq_undo_for(*FIIO, config_dir=tmp, mix_rate=96000)
check('an effect that cannot be undone (a low-pass) means nothing is undone, and the note says so', fir_u is None and 'not undone' in note_u and 'LP' in note_u, note_u)
check('no Equalizer APO folder: nothing', m.eq_undo_for(*FIIO, config_dir=os.path.join(tmp, 'nowhere'))[0] is None)

# ---- the filters themselves
PRESET = [('LSC', 105.0, 16.6, 0.70), ('PK', 53.8, -11.9, 0.41), ('PK', 153.6, -0.2, 0.97), ('PK', 593.6, 0.7, 0.94), ('PK', 1816.4, -1.2, 0.98), ('PK', 3671.7, -3.6, 3.48),
          ('PK', 4381.6, 1.8, 5.28), ('PK', 4535.3, 4.1, 1.05), ('PK', 9816.9, 3.5, 1.70), ('HSC', 10000.0, -3.2, 0.70)]
h_pk = m.eq_response([('PK', 1000.0, 6.0, 1.0)], 0.0, 48000.0, np.array([1000.0]))
check('a peaking filter has its gain at its frequency', abs(20 * np.log10(abs(h_pk[0])) - 6.0) < 0.01, 20 * np.log10(abs(h_pk[0])))
h_ls = m.eq_response([('LSC', 105.0, 16.6, 0.7)], 0.0, 96000.0, np.array([5.0, 20000.0]))
h_hs = m.eq_response([('HSC', 10000.0, -3.2, 0.7)], 0.0, 96000.0, np.array([50.0, 24000.0]))
check('a low shelf has its gain far below its corner and none far above; a high shelf the other way round',
      abs(20 * np.log10(abs(h_ls[0])) - 16.6) < 0.1 and abs(20 * np.log10(abs(h_ls[1]))) < 0.1 and abs(20 * np.log10(abs(h_hs[0]))) < 0.1 and abs(20 * np.log10(abs(h_hs[1])) + 3.2) < 0.7)
for mix in (96000, 48000):
    taps = m.eq_inverse_fir(-10.39, PRESET, mix)
    f = np.linspace(30, 20000, 400)
    inv = np.fft.rfft(taps, 1 << 16)[np.round(f * (1 << 16) / SR).astype(int)]
    both = inv * m.eq_response(PRESET, -10.39, float(mix), np.round(f * (1 << 16) / SR) * SR / (1 << 16))
    dev_db, dev_deg = np.abs(20 * np.log10(np.abs(both))), np.abs(np.degrees(np.angle(both)))
    limit_deg = 0.5 if mix == 48000 else 10.0  # an engine at 96 kHz has a little phase at the top that only its own (hidden) upper half explains
    check('the inverse filter times the equaliser is flat (to 0.01 dB) and in phase (to %.1f deg) from 30 Hz to 20 kHz (engine mixing at %d Hz)' % (limit_deg, mix),
          dev_db.max() < 0.01 and dev_deg.max() < limit_deg and dev_deg[f < 8000].max() < 4.0, (float(dev_db.max()), float(dev_deg.max())))

# ---- the stream filter gives the same as filtering everything in one go
rng = np.random.default_rng(7)
x = rng.standard_normal((5000, 2)).astype(np.float32)
taps = m.eq_inverse_fir(-10.39, PRESET, 48000)
sf = m.StreamFir(taps)
streamed = np.concatenate([sf.process(x[i:i + 480]) for i in range(0, 5000, 480)])
whole = np.stack([np.convolve(x[:, c].astype(np.float64), taps)[:5000] for c in (0, 1)], axis=1)
check('StreamFir: blocks of 480 samples come out as the whole stream filtered at once', float(np.abs(streamed[:4800] - whole[:4800]).max()) < 1e-4 * float(np.abs(whole).max()), float(np.abs(streamed[:4800] - whole[:4800]).max()))


# ---- the whole chain at 48 kHz: the equaliser run sample by sample, then undone by the stream filter
def run_equaliser(sig, filters, preamp_db, fs):
    y = sig * 10 ** (preamp_db / 20.0)
    for kind, fc, g, q in filters:
        b, a = m.eq_biquad(kind, fs, fc, g, q)
        z1 = z2 = 0.0
        res = np.empty_like(y)
        for i, v in enumerate(y):  # transposed direct form II
            o = b[0] * v + z1
            z1 = b[1] * v - a[1] * o + z2
            z2 = b[2] * v - a[2] * o
            res[i] = o
        y = res
    return y


noise = rng.standard_normal(SR) * 0.2
eqd = run_equaliser(noise, PRESET, -10.39, 48000.0)
sf1 = m.StreamFir(taps, 1)
undone = np.concatenate([sf1.process(eqd[i:i + 480, None])[:, 0] for i in range(0, len(eqd) - 479, 480)])
a_, b_ = undone[8000:], noise[8000:len(undone)]
err = 20 * np.log10(np.sqrt(((a_ - b_) ** 2).mean()) / np.sqrt((b_ ** 2).mean()))
check('noise sent through the equaliser (run sample by sample) and then through the undoing filter comes back: error %.1f dB' % err, err < -50, err)

# ---- the sample rate of an output
blob = bytes.fromhex('41000000' '01000000' 'feff0200' '00770100' '00b80b00' '08002000' '16002000')
check('the mix rate is read from the device format blob in the registry', m.mix_rate_from_blob(blob) == 96000 and m.mix_rate_from_blob(b'') == 48000)
T.finish()
