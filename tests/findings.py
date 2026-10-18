"""the findings scan: every kind of fault is found in the right channel at the right place, clean music gives no alarms, and the comparison says what differs"""
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

import support as T
from support import check, finish, m, SR

# ---- clean music: nothing above "worth knowing"
clean = T.demo_audio(1)
t0 = time.time()
found = m.find_problems(clean)
took = time.time() - t0
alarms = [(f['t'], f['channel'], f['kind']) for f in found if f['severity'] >= 2]
check('clean stereo music (kicks, plucks, hats, a riser, hard-panned notes) raises no alarm', not alarms, alarms[:6])
check('a 24 s clip is scanned in about a second', took < 6.0, round(took, 2))
bass = np.stack([0.5 * np.sin(2 * np.pi * 50 * np.arange(SR * 8) / SR)] * 2, axis=1)
check('a loud 50 Hz bass note is not mistaken for DC', not [f for f in m.find_problems(bass) if f['kind'].startswith('dc')])

# ---- one fault of every kind, each in one channel
x, expected = T.faulty_demo()
found = m.find_problems(x)
summary = [(f['t'], f['channel'], f['kind']) for f in found]


def has(kind, ch, t, tol=0.5):
    return any(f['kind'] == kind and f['channel'] == ch and abs(f['t'] - t) <= tol for f in found)


for t, ch, kind in expected:
    check('found: %s in the %s channel at %.1f s' % (kind, ch, t), has(kind, ch, t), summary)
check('the right channel blast is not blamed on the left', not has('blast', 'L', 5.0, 1.0))
check('the right DC run is a finding of its own (8 s to 12 s)', any(f['kind'] == 'dc_offset' and f['channel'] == 'R' and 7.5 < f['t'] < 8.5 and f['dur'] >= 3.5 for f in found), summary)
check('the left DC offset after its step is a finding too', any(f['kind'] == 'dc_offset' and f['channel'] == 'L' and 13.5 < f['t'] < 14.5 for f in found), summary)
check('findings come in time order', [f['t'] for f in found] == sorted(f['t'] for f in found))
check('every finding has a kind, a channel, a time and a severity of 1 to 3', all(set(f) >= {'kind', 'channel', 't', 'dur', 'size', 'text', 'severity'} and f['severity'] in (1, 2, 3) for f in found))

# ---- the Windows volume it was recorded at is added back first
quiet = (x * 10 ** (-26 / 20.0)).astype(np.float32)
again = m.find_problems(quiet, -26.0)
check('a recording made at a low Windows volume gives the same findings', [(f['t'], f['channel'], f['kind']) for f in again] == summary, len(again))

# ---- how they are shown
lines = m.format_findings(found)
check('the report names the channel and the fault', any('RIGHT' in l and 'blast' in l for l in lines) and any('LEFT' in l and 'DC' in l for l in lines), lines[:3])
check('a long list is cut with a count', m.format_findings(found, 3)[-1].startswith('... and '))
check('timeline marker names start with ! and say which channel', m.marker_name(dict(kind='blast', channel='R', size=17.0)) == '!R blast' and m.marker_name(dict(kind='dc_step', channel='L', size=13.4)) == '!L DC+13%')
img = m.findings_image(x, None, found, 'test')
arr = np.asarray(img)
check('the overview picture has all its panels', img.size[0] == 1600 and img.size[1] >= 760 and float(arr.std()) > 10, img.size)
check('and marks the findings in the channel colours', bool(((arr[:, :, 0] > 240) & (arr[:, :, 1] > 120) & (arr[:, :, 1] < 150) & (arr[:, :, 2] < 60)).any()) and bool(((arr[:, :, 2] > 240) & (arr[:, :, 0] < 60)).any()))

# ---- comparing two clips, segment by segment
A = m.Clip(clean * 0.5, None, name='A')


def verdicts(clip_b):
    rows = m.compare_clips(A, clip_b)
    return rows, {r['verdict'].split(' (')[0] for r in rows}


rows, v = verdicts(m.Clip(clean * 0.5, None, name='same'))
check('the same recording: every segment is the same', v == {'same'} and len(rows) >= 4, v)
rows, v = verdicts(m.Clip(clean * 0.25, None, name='quieter'))
check('6 dB quieter: "level differs" by about -6 dB in both channels', v == {'level differs'} and all(abs(r['level_l'] + 6.0) < 0.5 and abs(r['level_r'] + 6.0) < 0.5 for r in rows), rows[0])
dcb = clean * 0.5
dcb[:, 1] += 0.2
rows, v = verdicts(m.Clip(dcb, None, name='dc'))
check('a DC offset in the right channel only is named, and only for the right channel', v == {'DC offset differs'} and all('right' in r['verdict'] and 'left' not in r['verdict'] for r in rows), rows[0])
lb = clean * 0.5
lb[:, 0] *= 0.2
rows, v = verdicts(m.Clip(lb, None, name='left quiet'))
check('one channel much quieter is named', v == {'one channel differs'} and all('left' in r['verdict'] for r in rows), rows[0])
noise = np.random.default_rng(3).standard_normal(clean.shape) * 0.1
rows, v = verdicts(m.Clip(noise, None, name='noise'))
check('a different sound is called different', 'different sound' in v and 'same' not in v, v)
later = np.concatenate([np.zeros((int(1.9 * SR), 2)), clean * 0.5])
rows, v = verdicts(m.Clip(later, None, name='later'))
check('the same recording starting later is found where it is (offset 1.9 s) and is still "same"', v == {'same'} and all(abs(r['offset'] - 1.9) < 0.01 for r in rows), rows[0])
check('the comparison prints a table', len(m.format_comparison(rows)) == len(rows) + 2)

# ---- the --analyze command (no window), run the way a user or an AI would run it
tmp = tempfile.mkdtemp(prefix='scope_findings_')
wav = os.path.join(tmp, 'faulty.wav')
m.write_wav(wav, SR, x.astype(np.float32))
other = os.path.join(tmp, 'other.wav')
m.write_wav(other, SR, (clean * 0.5).astype(np.float32))
r = subprocess.run([sys.executable, os.path.join(T.ROOT, 'pc_audio_scope.py'), '--analyze', wav, other], capture_output=True, text=True, timeout=300)
check('--analyze exits cleanly', r.returncode == 0, r.stderr[-300:])
check('and prints the findings', 'RIGHT' in r.stdout and 'blast' in r.stdout and 'DC' in r.stdout, r.stdout[:200])
check('and writes a report, JSON and picture next to the clip', all(os.path.exists(os.path.join(tmp, 'faulty.analysis.' + e)) for e in ('txt', 'json', 'png')))
data = json.load(open(os.path.join(tmp, 'faulty.analysis.json')))
check('the JSON holds the findings', data['file'] == 'faulty.wav' and any(f['kind'] == 'blast' and f['channel'] == 'R' for f in data['findings']))
check('two files also give the segment comparison', os.path.exists(os.path.join(tmp, 'faulty.vs.other.txt')) and 'verdict' in open(os.path.join(tmp, 'faulty.vs.other.txt')).read())
bad = subprocess.run([sys.executable, os.path.join(T.ROOT, 'pc_audio_scope.py'), '--analyze'], capture_output=True, text=True, timeout=60)
check('--analyze with no file says how to use it', bad.returncode != 0 and 'usage' in (bad.stderr + bad.stdout))
finish()
