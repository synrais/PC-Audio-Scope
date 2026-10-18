"""PC Audio Scope: a scope, recorder, timeline player and clip comparer for the sound a PC plays (WASAPI loopback on Windows) or for a microphone.

Run it with `python pc_audio_scope.py`; README.md lists the features and the keys.
`--check [file]` starts it hidden for a few seconds on the real sound card and reports (used to test builds).
`--analyze CLIP.wav [OTHER.wav]` looks for faults in each channel and writes a report, a JSON file and an overview picture next to the clip (no window).
"""
import ctypes
import json
import math
import os
import queue
import re
import struct
import sys
import threading
import time
import tkinter as tk
import traceback
import warnings
from collections import deque
from tkinter import filedialog
from tkinter import font as tkfont



def _stop(message):
    """report a start-up problem where it can be seen (a windowed launcher has no console), then quit"""
    try:
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('PC Audio Scope', message)
        root.destroy()
    except Exception:
        pass
    sys.exit(message)


try:
    import numpy as np
    from PIL import Image, ImageTk
except ImportError as e:
    _stop('A Python package this program needs is missing (%s).\n\nInstall them with:\n\n    "%s" -m pip install -r requirements.txt' % (e.name, sys.executable.replace('pythonw', 'python')))


try:
    import comtypes  # imported on the main thread: its COM start-up must not run inside the capture thread
except Exception:
    comtypes = None

# ---------------------------------------------------------------- signal analysis (no GUI, no audio device)
# block statistics, ITU-R BS.1770 loudness (LUFS), stereo correlation, a log-frequency spectrogram and the comparison of two recordings
# (alignment, per-window similarity, null test).  All audio is float32 stereo at 48 kHz.
SR = 48000
BLOCK = SR // 100  # 10 ms
FLOOR = -120.0


def db(v):
    return FLOOR if v <= 1e-6 else max(FLOOR, 20.0 * math.log10(v))


def db_array(v):
    return np.maximum(FLOOR, 20.0 * np.log10(np.maximum(v, 1e-6)))


# ---- numerical helpers and WAV files, NumPy only (SciPy would add 30 MB to the program)
def fft_correlate_valid(sig, ref):
    """sum over j of sig[k + j] * ref[j], for every k at which ref fits inside sig"""
    nfft = 1 << (len(sig) + len(ref) - 2).bit_length()
    spec = np.fft.rfft(sig, nfft) * np.conj(np.fft.rfft(ref, nfft))
    return np.fft.irfft(spec, nfft)[:len(sig) - len(ref) + 1]


class _Fir:
    """a fixed FIR filter applied in FFT blocks (overlap-save): valid(x) equals np.convolve(x, taps, 'valid')"""
    def __init__(self, taps):
        self.taps = np.asarray(taps, dtype=np.float64)
        self._spec = {}

    def valid(self, x):
        n_taps = len(self.taps)
        n_out = len(x) - n_taps + 1
        if n_out <= 0:
            return np.zeros(0)
        nfft = min(1 << 16, 1 << (len(x) - 1).bit_length())
        if nfft not in self._spec:
            self._spec[nfft] = np.fft.rfft(self.taps, nfft)
        spec, step = self._spec[nfft], nfft - (n_taps - 1)
        out = np.empty(n_out)
        for i in range(0, n_out, step):
            y = np.fft.irfft(np.fft.rfft(x[i:i + nfft], nfft) * spec, nfft)
            m = min(step, n_out - i)
            out[i:i + m] = y[n_taps - 1:n_taps - 1 + m]
        return out


def _kaiser_sinc(tau, cutoff, half):
    """low-pass kernel at distances tau (input samples): sinc cut at `cutoff` x Nyquist under a Kaiser window (beta 5) of half-width `half`"""
    u = np.clip(tau / half, -1.0, 1.0)
    return cutoff * np.sinc(cutoff * tau) * np.i0(5.0 * np.sqrt(1.0 - u * u)) / np.i0(5.0)


def resample_poly(x, up, down, axis=0):
    """resample along the first axis by up / down with a windowed-sinc low-pass (the design of scipy's resample_poly); zero outside the signal"""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 2:
        return np.stack([resample_poly(x[:, c], up, down) for c in range(x.shape[1])], axis=1)
    g = math.gcd(int(up), int(down))
    up, down = int(up) // g, int(down) // g
    if up == down:
        return x.copy()
    cutoff = min(1.0, up / float(down))
    half = 10.0 * max(1.0, down / float(up))
    h_len = int(math.ceil(half))
    n_out = int(math.ceil(len(x) * up / float(down)))
    if up == 1:  # whole-number decimation: filter, keep every down-th sample
        taps = _kaiser_sinc(np.arange(-h_len, h_len + 1, dtype=np.float64), cutoff, half)
        y = _Fir(taps).valid(np.concatenate([np.zeros(h_len), x, np.zeros(h_len)]))
        return y[::down][:n_out]
    ks = np.arange(-h_len + 1, h_len + 1)
    table = _kaiser_sinc(np.arange(up)[:, None] / float(up) - ks[None, :], cutoff, half)  # one row of taps per output phase
    xp = np.concatenate([np.zeros(h_len), x, np.zeros(h_len + 1)])
    out = np.empty(n_out)
    for s0 in range(0, n_out, 1 << 17):
        n = np.arange(s0, min(n_out, s0 + (1 << 17)))
        pos, phase = (n * down) // up, (n * down) % up
        out[s0:s0 + len(n)] = (xp[(pos + h_len)[:, None] + ks[None, :]] * table[phase]).sum(axis=1)
    return out


def read_wav(path):
    """-> (sample rate, samples shaped (n,) or (n, channels)).  8-bit PCM comes back as uint8, 16-bit as int16, 24- and 32-bit as int32, float as float32 / float64"""
    with open(path, 'rb') as f:
        raw = f.read()
    if raw[:4] not in (b'RIFF', b'RF64') or raw[8:12] != b'WAVE':
        raise ValueError('not a WAV file')
    pos, fmt, body = 12, None, None
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack('<I', raw[pos + 4:pos + 8])[0]
        start = pos + 8
        if cid == b'fmt ':
            tag, ch, sr, _, _, bits = struct.unpack('<HHIIHH', raw[start:start + 16])
            if tag == 0xFFFE and size >= 26:
                tag = struct.unpack('<H', raw[start + 24:start + 26])[0]
            fmt = (tag, ch, sr, bits)
        elif cid == b'data':
            end = len(raw) if size in (0, 0xFFFFFFFF) else min(len(raw), start + size)
            body = raw[start:end]
            break
        pos = start + size + (size & 1)
    if fmt is None or body is None:
        raise ValueError('not a usable WAV file')
    tag, ch, sr, bits = fmt
    if tag == 1 and bits == 8:
        x = np.frombuffer(body, np.uint8)
    elif tag == 1 and bits == 16:
        x = np.frombuffer(body[:len(body) // 2 * 2], '<i2')
    elif tag == 1 and bits == 24:
        b3 = np.frombuffer(body[:len(body) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
        x = (b3[:, 0] << 8) | (b3[:, 1] << 16) | (b3[:, 2] << 24)
    elif tag == 1 and bits == 32:
        x = np.frombuffer(body[:len(body) // 4 * 4], '<i4')
    elif tag == 3 and bits == 32:
        x = np.frombuffer(body[:len(body) // 4 * 4], '<f4')
    elif tag == 3 and bits == 64:
        x = np.frombuffer(body[:len(body) // 8 * 8], '<f8')
    else:
        raise ValueError('unsupported WAV format (type %d, %d bit)' % (tag, bits))
    x = x[:len(x) // ch * ch]
    return sr, (x.reshape(-1, ch) if ch > 1 else x)


def write_wav(path, sr, data):
    """32-bit float WAV: nothing is lost however quiet the Windows volume is"""
    data = np.ascontiguousarray(data, dtype='<f4')
    ch = 1 if data.ndim == 1 else data.shape[1]
    payload = data.tobytes()
    fmt = struct.pack('<HHIIHH', 3, ch, sr, sr * ch * 4, ch * 4, 32)
    head = b'RIFF' + struct.pack('<I', 4 + 8 + 16 + 12 + 8 + len(payload)) + b'WAVE'
    head += b'fmt ' + struct.pack('<I', 16) + fmt + b'fact' + struct.pack('<II', 4, len(data)) + b'data' + struct.pack('<I', len(payload))
    with open(path, 'wb') as f:
        f.write(head + payload)


def block_flags(blk):
    """per channel: does this block have a flat top (>= 4 identical samples at its peak)?"""
    out = []
    for c in (0, 1):
        a = np.abs(blk[:, c])
        pk = float(a.max())
        f = False
        if pk > 0.005:
            m = a >= pk * 0.9999
            f = bool((m[:-3] & m[1:-2] & m[2:-1] & m[3:]).any())
        out.append(f)
    return out


def analyze(data):
    """per 10 ms block: peaks (nb, 2) and flat-top flags (nb, 2)"""
    nb = len(data) // BLOCK
    if nb == 0:
        return np.zeros((1, 2), np.float32), np.zeros((1, 2), bool)
    b = np.abs(data[:nb * BLOCK]).reshape(nb, BLOCK, 2)
    peaks = b.max(axis=1)
    flat = np.zeros((nb, 2), bool)
    for c in (0, 1):
        a = b[:, :, c]
        pk = peaks[:, c:c + 1]
        m = a >= pk * 0.9999
        flat[:, c] = (m[:, :-3] & m[:, 1:-2] & m[:, 2:-1] & m[:, 3:]).any(axis=1) & (pk[:, 0] > 0.005)
    return peaks.astype(np.float32), flat


def correlation(L, R):
    """Pearson correlation of the two channels: +1 identical (mono), 0 unrelated (wide), -1 opposite phase.  None when both are silent."""
    L = np.asarray(L, dtype=np.float64)
    R = np.asarray(R, dtype=np.float64)
    el, er = float(np.dot(L, L)), float(np.dot(R, R))
    if el < 1e-12 or er < 1e-12:
        return None
    return float(np.dot(L, R) / math.sqrt(el * er))


# K-weighting at 48 kHz: a high-shelf pre-filter followed by the RLB high-pass
_K1B = [1.53512485958697, -2.69169618940638, 1.19839281085285]
_K1A = [1.0, -1.69065929318241, 0.73248077421585]
_K2B = [1.0, -2.0, 1.0]
_K2A = [1.0, -1.99004745483398, 0.99007225036621]


def _biquad_impulse(b, a, n):
    """the first n samples of the impulse response of a second-order filter"""
    h = np.zeros(n)
    x1 = x2 = y1 = y2 = 0.0
    for i in range(n):
        x0 = 1.0 if i == 0 else 0.0
        y0 = b[0] * x0 + b[1] * x1 + b[2] * x2 - a[1] * y1 - a[2] * y2
        h[i] = y0
        x2, x1, y2, y1 = x1, x0, y1, y0
    return h


_KN = 4096  # taps of the FIR that stands in for the two K-weighting filters (error below 1e-8)
_KFILTER = _Fir(np.convolve(_biquad_impulse(_K1B, _K1A, _KN), _biquad_impulse(_K2B, _K2A, _KN))[:_KN])


class KWeight:
    """streaming K-weighting; energy(blk) -> sum over channels of the mean square of the weighted signal"""
    def __init__(self):
        self.hist = [np.zeros(_KN - 1), np.zeros(_KN - 1)]

    def energy(self, blk):
        e = 0.0
        for c in (0, 1):
            x = np.concatenate([self.hist[c], blk[:, c]])
            y = _KFILTER.valid(x)
            self.hist[c] = x[len(blk):]
            e += float(np.mean(y * y))
        return e


def kweight_blocks(data):
    """per 10 ms block loudness energy of a whole recording (same numbers the streaming meter would give)"""
    nb = len(data) // BLOCK
    if nb == 0:
        return np.zeros(1)
    e = np.zeros(nb)
    for c in (0, 1):
        y = _KFILTER.valid(np.concatenate([np.zeros(_KN - 1), data[:nb * BLOCK, c]]))
        e += (y * y).reshape(nb, BLOCK).mean(axis=1)
    return e


def lufs(energy):
    """loudness of a mean energy (BS.1770: -0.691 + 10 log10 of the summed channel mean squares)"""
    return FLOOR if energy <= 1e-12 else max(FLOOR, -0.691 + 10.0 * math.log10(energy))


def integrated(ms, offset_db=0.0):
    """gated integrated loudness (absolute gate -70 LUFS, relative gate -10 LU), None if nothing is loud enough.  offset_db is added to every level (volume compensation)."""
    ms = np.asarray(ms, dtype=np.float64)
    if len(ms) < 40:
        return None
    cs = np.concatenate([[0.0], np.cumsum(ms)])
    starts = np.arange(0, len(ms) - 39, 10)  # 400 ms blocks, 100 ms hop
    z = (cs[starts + 40] - cs[starts]) / 40.0
    k = 10.0 ** (offset_db / 10.0)
    z = z * k
    l = np.where(z > 1e-12, -0.691 + 10.0 * np.log10(np.maximum(z, 1e-12)), FLOOR)
    keep = l > -70.0
    if not keep.any():
        return None
    thr = lufs(float(z[keep].mean())) - 10.0
    keep &= l > thr
    if not keep.any():
        return None
    return lufs(float(z[keep].mean()))


SG_NFFT = 4096
SG_HOP = 1536  # 32 ms
SG_BANDS = 160  # log-spaced from 30 Hz to 20 kHz
_SG_WIN = np.hanning(SG_NFFT)
# the ranges an equaliser talks about: (from Hz, to Hz, names from long to short, the range as text)
EQ_BANDS = (
    (20, 60, ('Sub-bass', 'Sub'), '20-60'),
    (60, 250, ('Bass',), '60-250'),
    (250, 500, ('Low mids', 'Low mid', 'Low'), '250-500'),
    (500, 2000, ('Mids',), '500-2k'),
    (2000, 4000, ('Upper mids', 'Hi mids', 'Hi mid'), '2k-4k'),
    (4000, 6000, ('Presence', 'Pres.'), '4k-6k'),
    (6000, 20000, ('Brilliance', 'Air'), '6k-20k'),
)
# the spectrum and the level history sit side by side and share one dB scale: the same range, the same lines on the same rows
DB_RANGE = 80.0  # 0 dB at the top of the graph, -80 dB at the bottom; anything quieter, and silence, is drawn on the bottom line in both
DB_LINES = (0, -10, -20, -30, -40, -50, -60, -70, -80)


def _band_starts():
    """first FFT bin of every spectrogram band"""
    e = np.logspace(math.log10(30), math.log10(20000), SG_BANDS + 1) / (SR / SG_NFFT)
    return np.clip(np.floor(e[:-1]).astype(int), 1, SG_NFFT // 2 - 1)


_SG_STARTS = _band_starts()


def sg_column(x):
    """one spectrogram column (dBFS per log-frequency band) from the last SG_NFFT samples of x (mono)"""
    if len(x) < SG_NFFT:
        x = np.concatenate([np.zeros(SG_NFFT - len(x)), x])
    mag = np.abs(np.fft.rfft(x[-SG_NFFT:] * _SG_WIN)) * 2.0 / _SG_WIN.sum()
    band = np.maximum.reduceat(mag[1:], _SG_STARTS - 1)
    return db_array(band)


def sg_full(mono):
    """spectrogram of a whole recording: (n_columns, 160) dBFS, one column per SG_HOP samples (column i ends at sample i*SG_HOP + SG_NFFT)"""
    n = (len(mono) - SG_NFFT) // SG_HOP + 1
    if n <= 0:
        return np.full((1, len(_SG_STARTS)), FLOOR, np.float32)
    idx = np.arange(n)[:, None] * SG_HOP + np.arange(SG_NFFT)[None, :]
    out = np.empty((n, len(_SG_STARTS)), np.float32)
    for i0 in range(0, n, 512):
        seg = mono[idx[i0:i0 + 512]] * _SG_WIN
        mag = np.abs(np.fft.rfft(seg, axis=1)) * 2.0 / _SG_WIN.sum()
        out[i0:i0 + 512] = db_array(np.maximum.reduceat(mag[:, 1:], _SG_STARTS - 1, axis=1))
    return out


def palette(n=256, base=None):
    """colour table of the spectrogram: 'magma'-like (black - blue - purple - red - orange - yellow - white), or black - base colour - near white when a base colour is given"""
    if base is None:
        stops = [(0.0, (0, 0, 4)), (0.15, (28, 16, 68)), (0.35, (101, 21, 110)), (0.55, (187, 55, 84)), (0.75, (249, 142, 8)), (0.9, (252, 235, 90)), (1.0, (252, 253, 191))]
    else:
        r, g, b = (int(base[i:i + 2], 16) for i in (1, 3, 5))
        lift = tuple(round(v + (255 - v) * 0.85) for v in (r, g, b))
        stops = [(0.0, (0, 0, 0)), (0.4, (r * 4 // 10, g * 4 // 10, b * 4 // 10)), (0.75, (r, g, b)), (1.0, lift)]
    xs = np.linspace(0, 1, n)
    lut = np.zeros((n, 3), np.uint8)
    for ch in range(3):
        lut[:, ch] = np.interp(xs, [s[0] for s in stops], [s[1][ch] for s in stops]).astype(np.uint8)
    return lut


_D = 12  # decimation for the searches: 48 kHz -> 4 kHz


def comp(data, vol_db):
    """back to source level: undo the Windows volume the recording was made at (None = unknown, leave as it is)"""
    return data * (10.0 ** (-vol_db / 20.0)) if vol_db is not None else data


def place(data, start_frames, total_frames):
    """put a recording on a common time axis: it starts at start_frames (>= 0) of an axis total_frames long"""
    out = np.zeros((total_frames, 2), np.float32)
    s = max(0, start_frames)
    e = min(total_frames, start_frames + len(data))
    if e > s:
        out[s:e] = data[s - start_frames:e - start_frames]
    return out


def _remove_dc(x, n):
    """subtract the average over the n samples around each sample: a constant or slowly drifting offset is not part of the sound"""
    c = np.concatenate([[0.0], np.cumsum(x)])
    i = np.arange(len(x))
    lo, hi = np.clip(i - n // 2, 0, len(x)), np.clip(i + n // 2 + 1, 0, len(x))
    return x - (c[hi] - c[lo]) / (hi - lo)


def auto_align(a, b, a_vol=None, b_vol=None, a_range=None, cache=None):
    """Where does b have to start so that it lines up with a?  Searches the whole of b for the part of a given by a_range = (t0, t1) seconds of a (default: the loudest 6 s of a).
    Returns (lag, score): lag in seconds such that a[t] ~ b[t + lag] (b has to be placed `lag` EARLIER than a to line up: start_b = start_a - lag); score = normalised correlation 0..1."""
    D = _D
    fs = SR // D
    key = (id(a), id(b), a_vol, b_vol)
    if cache is not None and key in cache:
        ma, mb, da, dbb = cache[key]
    else:
        ma = _remove_dc(comp(a, a_vol).astype(np.float64).mean(axis=1), SR // 2)
        mb = _remove_dc(comp(b, b_vol).astype(np.float64).mean(axis=1), SR // 2)
        da, dbb = resample_poly(ma, 1, D), resample_poly(mb, 1, D)
        if cache is not None:
            cache[key] = (ma, mb, da, dbb)
    if a_range is not None:
        i0 = int(max(0, a_range[0]) * fs)
        i1 = int(min(len(da) / fs, a_range[1]) * fs)
    else:
        w = min(len(da), 6 * fs)
        if len(da) >= w:
            cs0 = np.concatenate([[0.0], np.cumsum(da * da)])
            e = cs0[w:] - cs0[:-w]
        else:
            e = np.array([float(np.dot(da, da))])
        i0 = int(np.argmax(e))
        i1 = i0 + w
    ref = da[i0:i1]
    P = len(ref)
    eref = float(np.dot(ref, ref))
    if P < 8 or eref < 1e-12:
        return 0.0, 0.0
    bp = np.pad(dbb, (P, P))
    cc = fft_correlate_valid(bp, ref)
    csum = np.concatenate([[0.0], np.cumsum(bp * bp)])
    e = csum[np.arange(len(cc)) + P] - csum[np.arange(len(cc))]
    ncc = cc / np.sqrt(eref * np.maximum(e, 0.1 * eref))
    j = int(np.argmax(ncc))
    score = max(0.0, float(ncc[j]))
    lag_dec = (j - P) - i0
    # refine at the full rate: +- 2 decimated samples around the coarse answer, on the loudest 3 s of the reference
    n48 = min(3 * SR, (i1 - i0) * D)
    r0 = i0 * D
    if (i1 - i0) * D >= n48:
        cs1 = np.concatenate([[0.0], np.cumsum(ma[r0:r0 + (i1 - i0) * D] ** 2)])
        seg_e = cs1[n48:] - cs1[:-n48]
        if len(seg_e):
            r0 += int(np.argmax(seg_e))
    ref48 = ma[r0:r0 + n48]
    base = r0 + lag_dec * D
    lo = base - 2 * D
    seg = mb[lo:lo + len(ref48) + 4 * D] if lo >= 0 else np.concatenate([np.zeros(-lo), mb])[:len(ref48) + 4 * D]
    if len(seg) >= len(ref48) + 4 * D and len(ref48) > 64:
        cc2 = fft_correlate_valid(seg, ref48)
        lag48 = (lo + int(np.argmax(cc2))) - r0
    else:
        lag48 = lag_dec * D
    return lag48 / SR, score


def window_stats(ca, cb, win_s=1.0, hop_s=0.5, search_s=1.0):
    """How alike are two recordings that are already placed on the same time axis (source level, equal length)?  Per window (win_s long, every hop_s):
    sim = correlation at the current alignment (0..1), lvl = b relative to a in dB, resid = what is left of a after subtracting the level-matched b (dB, lower = more alike),
    lag = where b would line up best within +- search_s of the current alignment (s; b later = positive).  Also the overall level difference and the null depth, and the difference signal itself."""
    D = _D
    fs = SR // D
    ma = resample_poly(ca.astype(np.float64).mean(axis=1), 1, D)
    mb = resample_poly(cb.astype(np.float64).mean(axis=1), 1, D)
    n = min(len(ma), len(mb))
    ma, mb = ma[:n], mb[:n]
    W, H, SL = int(win_s * fs), int(hop_s * fs), int(search_s * fs)
    starts = list(range(0, max(1, n - W + 1), H))
    nw = len(starts)
    ea = np.array([float(np.dot(ma[s:s + W], ma[s:s + W])) for s in starts])
    eb = np.array([float(np.dot(mb[s:s + W], mb[s:s + W])) for s in starts])
    thr = max(1e-4 * max(float(ea.max()), float(eb.max()), 1e-12), 1e-9)
    act_a, act_b = ea >= thr, eb >= thr
    both = act_a & act_b
    g = math.sqrt(float(ea[both].sum()) / float(eb[both].sum())) if both.any() else 1.0
    level_db = 10.0 * math.log10(float(eb[both].sum()) / float(ea[both].sum())) if both.any() else 0.0
    sim = np.full(nw, np.nan)
    lvl = np.full(nw, np.nan)
    resid = np.full(nw, np.nan)
    lag = np.full(nw, np.nan)
    bp = np.pad(mb, (SL, SL + W))
    csum = np.concatenate([[0.0], np.cumsum(bp * bp)])
    for i, s in enumerate(starts):
        if not act_a[i] and not act_b[i]:
            continue
        if act_a[i] != act_b[i]:  # only one of them makes sound here
            sim[i], resid[i] = 0.0, 0.0
            lvl[i] = 30.0 if act_b[i] else -30.0
            continue
        aw, bw = ma[s:s + W], mb[s:s + W]
        sim[i] = max(0.0, float(np.dot(aw, bw)) / math.sqrt(ea[i] * eb[i]))
        lvl[i] = 10.0 * math.log10(eb[i] / ea[i])
        resid[i] = 10.0 * math.log10(max(float(np.sum((aw - g * bw) ** 2)), 1e-20) / ea[i])
        seg = bp[s:s + W + 2 * SL]
        cc = fft_correlate_valid(seg, aw)
        idx = np.arange(len(cc))
        e = csum[s + idx + W] - csum[s + idx]
        ncc = cc / np.sqrt(ea[i] * np.maximum(e, 1e-12))
        lag[i] = (int(np.argmax(ncc)) - SL) / fs
    diff = (ca.astype(np.float64) - g * cb.astype(np.float64))
    ref = float(np.sum(ca.astype(np.float64) ** 2))
    null_db = 10.0 * math.log10(max(float(np.sum(diff * diff)), 1e-20) / ref) if ref > 1e-12 else 0.0
    return dict(win_t=np.array(starts) / fs, sim=sim, lvl=lvl, resid=resid, lag=lag, level_db=level_db, null_db=null_db, diff=diff.astype(np.float32), hop_s=hop_s)


# ---------------------------------------------------------------- finding problems in a recording
# Everything here looks at each channel on its own: a fault in one channel is hidden in a stereo (mono) mix, and loudness (LUFS) ignores DC.
_NL = chr(10)
CHANNELS = ('L', 'R')
CHANNEL_NAMES = {'L': 'LEFT', 'R': 'RIGHT', 'both': 'both'}


def channel_features(data, win_s=0.1):
    """per window and channel: dc (the average sample), rms (the level with the DC taken out) and peak"""
    w = int(round(win_s * SR))
    n = len(data) // w
    if n == 0:
        z = np.zeros((1, 2))
        return dict(win=win_s, dc=z, rms=z.copy(), peak=z.copy())
    dc, rms, peak = np.zeros((n, 2)), np.zeros((n, 2)), np.zeros((n, 2))
    step = max(1, int(60 / win_s))  # 60 s at a time keeps the float64 copy small
    for i in range(0, n, step):
        j = min(n, i + step)
        x = np.asarray(data[i * w:j * w], dtype=np.float64).reshape(j - i, w, 2)
        d = x.mean(axis=1)
        dc[i:j], peak[i:j] = d, np.abs(x).max(axis=1)
        rms[i:j] = np.sqrt(((x - d[:, None, :]) ** 2).mean(axis=1))
    return dict(win=win_s, dc=dc, rms=rms, peak=peak)


def _runs(mask, min_len=1, gap=0):
    """[(start, end)] of the runs of True in mask that are at least min_len long; runs closer together than gap are joined"""
    d = np.diff(np.concatenate(([0], np.asarray(mask, dtype=np.int8), [0])))
    out = []
    for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
        if out and a - out[-1][1] <= gap:
            out[-1] = (out[-1][0], int(b))
        else:
            out.append((int(a), int(b)))
    return [(a, b) for a, b in out if b - a >= min_len]


def _running_median(v, n):
    """median of the n values before each position (the first n positions use what there is, at least 5)"""
    out = np.full(len(v), np.nan)
    for i in range(5, len(v)):
        out[i] = np.median(v[max(0, i - n):i])
    return out


def find_problems(data, vol_db=None):
    """look for faults in each channel: a channel that blasts on its own, DC offset and DC steps, dropouts, frozen samples, clicks, clipping, out-of-phase passages.
    -> [dict(kind, channel, t, dur, size, text, severity)] in time order (severity 3 = surely a fault, 2 = probably, 1 = worth knowing)"""
    x = comp(data, vol_db) if vol_db is not None else np.asarray(data)
    found = []

    def add(kind, ch, t, dur, size, text, severity):
        found.append(dict(kind=kind, channel=ch, t=round(float(t), 2), dur=round(float(dur), 2), size=round(float(size), 2), text=text, severity=severity))

    f = channel_features(x, 0.1)
    n = len(f['rms'])
    lv = 20 * np.log10(np.maximum(f['rms'], 1e-6))
    pk = 20 * np.log10(np.maximum(f['peak'], 1e-6))
    # a channel that jumps far above its own recent level while the other one does not
    base = np.stack([_running_median(lv[:, c], 30) for c in (0, 1)], axis=1)
    rise = lv - base
    for c, o in ((0, 1), (1, 0)):
        flag = (rise[:, c] > 12) & ((rise[:, c] - np.nan_to_num(rise[:, o])) > 14) & (lv[:, c] > -40) & (pk[:, c] > -6)
        for a, b in _runs(flag, 1, 3):
            peak = float(pk[a:b, c].max())
            size = float((rise[a:b, c] - np.nan_to_num(rise[a:b, o])).max())
            add('blast', CHANNELS[c], a * 0.1, (b - a) * 0.1, size,
                'blast: %.0f dB above its own level for %.1f s, the other channel normal (peak %.1f dBFS)' % (size, (b - a) * 0.1, peak), 3)
    # DC offset: steps and long stretches (0.25 s windows, so that bass notes do not count)
    fd = channel_features(x, 0.25)
    dc = fd['dc']
    m = len(dc)
    for c in (0, 1):
        steps = [(i, float(np.median(dc[i:i + 4, c]) - np.median(dc[i - 4:i, c]))) for i in range(4, m - 4)]
        taken = []
        for i, step in sorted(steps, key=lambda q: -abs(q[1])):
            if abs(step) < 0.04:
                break
            if all(abs(i - j) > 4 for j in taken):
                taken.append(i)
                add('dc_step', CHANNELS[c], i * 0.25, 0.0, step * 100, 'DC offset jumps by %+.1f%% (to %+.1f%%)' % (step * 100, 100 * float(np.median(dc[i:i + 4, c]))), 3 if abs(step) >= 0.08 else 2)
        for a, b in _runs(np.abs(dc[:, c]) > 0.04, 8, 2):
            lvl = 100 * float(np.median(dc[a:b, c]))
            add('dc_offset', CHANNELS[c], a * 0.25, (b - a) * 0.25, lvl, 'DC offset held near %+.1f%% for %.0f s (headroom lost)' % (lvl, (b - a) * 0.25), 3 if abs(lvl) >= 10 else 2)
    # silence after the first sound
    lin = f['peak']
    quiet = lin < 1e-4
    first = int(np.argmax(~(quiet[:, 0] & quiet[:, 1]))) if (~(quiet[:, 0] & quiet[:, 1])).any() else n
    for a, b in _runs(quiet[:, 0] & quiet[:, 1], 3):
        if a <= first:
            continue
        to_end = b >= n
        long = (b - a) * 0.1 > 3.0
        add('silence', 'both', a * 0.1, (b - a) * 0.1, (b - a) * 0.1, ('silent to the end of the clip (%.1f s)' if to_end else 'digital silence for %.1f s') % ((b - a) * 0.1), 1 if (long or to_end) else 2)
    for c, o in ((0, 1), (1, 0)):
        for a, b in _runs(quiet[:, c] & ~quiet[:, o] & (lv[:, o] > -50), 5):
            add('channel_silent', CHANNELS[c], a * 0.1, (b - a) * 0.1, (b - a) * 0.1, 'silent for %.1f s while the other channel plays' % ((b - a) * 0.1), 3)
    # samples that stay on one value, and single-sample clicks
    for c in (0, 1):
        ch = np.asarray(x[:, c], dtype=np.float64)
        same = (ch[1:] == ch[:-1]) & (np.abs(ch[1:]) > 0.002) & (np.abs(ch[1:]) < 0.98)
        groups = []
        for a, b in _runs(same, 48):
            if groups and a - groups[-1][1] <= int(0.5 * SR):
                groups[-1][1], groups[-1][2] = b, max(groups[-1][2], b - a)
            else:
                groups.append([a, b, b - a])
        for a, b, longest in groups[:10]:
            add('frozen', CHANNELS[c], a / float(SR), (b - a) / float(SR), longest / float(SR) * 1000, 'stuck on one sample value for %.1f ms' % (longest / float(SR) * 1000), 2)
        blk = 4800
        nb = (len(ch) - 2) // blk
        if nb > 0:
            d2 = np.abs(ch[2:2 + nb * blk] - 2 * ch[1:1 + nb * blk] + ch[:nb * blk]).reshape(nb, blk)
            med, mx = np.median(d2, axis=1), d2.max(axis=1)
            d2f = d2.reshape(-1)
            for i in np.flatnonzero((mx > 0.2) & (mx > 60 * np.maximum(med, 1e-6))):
                g = i * blk + int(np.argmax(d2[i]))
                around = np.concatenate([d2f[max(0, g - 64):max(0, g - 3)], d2f[g + 4:g + 64]])
                if len(around) and float(around.max()) > 0.2 * mx[i]:
                    continue  # the neighbours are busy too: a burst of sound (a hi-hat, noise), not a single click
                add('click', CHANNELS[c], g / float(SR), 0.0, mx[i], 'click or pop (a jump of %.2f between neighbouring samples)' % mx[i], 2)
    # clipping, out of phase, one channel far quieter
    peaks, flat = analyze(x)
    for c in (0, 1):
        for a, b in _runs(flat[:, c], 1, 50):
            if int(flat[a:b, c].sum()) >= 3:
                add('clipping', CHANNELS[c], a * 0.01, (b - a) * 0.01, int(flat[a:b, c].sum()), 'clips (%d flat-topped blocks)' % int(flat[a:b, c].sum()), 2)
    sec = len(x) // SR
    if sec >= 2:
        w = np.asarray(x[:sec * SR], dtype=np.float64).reshape(sec, SR, 2)
        cl = np.array([correlation(w[i, :, 0], w[i, :, 1]) if w[i].std() > 3e-3 else None for i in range(sec)], dtype=object)
        out = np.array([(v is not None and v < -0.5) for v in cl])
        for a, b in _runs(out, 2):
            add('out_of_phase', 'both', a, b - a, float(np.mean([v for v in cl[a:b]])), 'out of phase for %d s (cancels in mono)' % (b - a), 1)
    ok = (lv[:, 0] > -60) & (lv[:, 1] > -60)
    if n >= 50:
        diff = np.convolve(np.where(ok, lv[:, 1] - lv[:, 0], 0.0), np.ones(50) / 50.0, mode='same')
        for c, sgn in (('L', -1), ('R', 1)):
            for a, b in _runs((sgn * diff > 15) & ok, 50):
                add('imbalance', c, a * 0.1, (b - a) * 0.1, float(abs(diff[a:b]).mean()), 'about %.0f dB louder than the other channel for %.0f s' % (float(abs(diff[a:b]).mean()), (b - a) * 0.1), 1)
    found.sort(key=lambda d: (d['t'], -d['severity']))
    return found


def format_findings(findings, limit=None):
    """one line per finding: time, channel, what"""
    lines = ['%s  %-5s %s' % (fmt_time(d['t'], True), CHANNEL_NAMES[d['channel']], d['text']) for d in findings[:limit]]
    if limit is not None and len(findings) > limit:
        lines.append('... and %d more' % (len(findings) - limit))
    return lines


def marker_name(d):
    """a short label for the timeline"""
    c = d['channel'] if d['channel'] != 'both' else ''
    return '!' + {'blast': c + ' blast', 'dc_step': c + ' DC%+.0f%%' % d['size'], 'dc_offset': c + ' DC', 'silence': 'silence', 'channel_silent': c + ' mute', 'frozen': c + ' stuck',
                  'click': c + ' click', 'clipping': c + ' clip', 'out_of_phase': 'phase', 'imbalance': c + ' loud'}.get(d['kind'], d['kind']).strip()


def findings_image(data, vol_db, findings, title='', width=1600, left='#ff8a1f', right='#2fb5ff'):
    """a picture of the whole recording: level per channel, DC offset per channel, a spectrogram, the findings marked on it and listed underneath"""
    from PIL import ImageDraw, ImageFont
    x = comp(data, vol_db) if vol_db is not None else np.asarray(data)
    dur = len(x) / float(SR)
    f = channel_features(x, 0.1)
    n = len(f['rms'])
    lv = 20 * np.log10(np.maximum(f['rms'], 1e-6))
    mx, rx = 70, width - 20
    pw = rx - mx
    lines = format_findings(findings, 16)
    h = 760 + 13 * max(2, len(lines))
    img = Image.new('RGB', (width, h), '#0b0e11')
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    def xt(t):
        return mx + t / max(dur, 1e-9) * pw

    def ytrace(v, lo, hi, y0, y1):
        return y1 - (np.clip(v, lo, hi) - lo) / float(hi - lo) * (y1 - y0)

    def trace(vals, color, lo, hi, y0, y1):
        k = max(1, int(np.ceil(len(vals) / float(pw))))
        m = len(vals) // k * k
        if m == 0:
            return
        g = vals[:m].reshape(-1, k)
        if len(g) < 2:
            return
        up, dn = g.max(axis=1), g.min(axis=1)
        xs = mx + (np.arange(len(g)) + 0.5) / len(g) * pw
        d.line(list(zip(xs, ytrace(up, lo, hi, y0, y1))), fill=color, width=1)
        if k > 1:
            d.line(list(zip(xs, ytrace(dn, lo, hi, y0, y1))), fill=color, width=1)

    d.text((10, 8), title or 'recording', fill='#e6edf2', font=font)
    d.text((10, 20), 'every panel shows the LEFT channel (%s) and the RIGHT channel (%s) on their own; coloured lines mark the findings' % ('orange', 'blue'), fill='#8fa3b0', font=font)
    panels = [('LEVEL per channel, dBFS (DC taken out)', 40, 260), ('DC OFFSET per channel, % of full scale', 290, 430), ('SPECTROGRAM (left + right)', 460, 700)]
    for name, y0, y1 in panels:
        d.rectangle((mx, y0, rx, y1), outline='#2a323a')
        d.text((mx + 4, y0 + 2), name, fill='#8fa3b0', font=font)
    for db_ in (-60, -40, -20, 0):
        yy = ytrace(db_, -80, 0, 40, 260)
        d.line((mx, yy, rx, yy), fill='#1d252c')
        d.text((10, yy - 5), '%d' % db_, fill='#5b6b76', font=font)
    trace(lv[:, 0], left, -80, 0, 40, 260)
    trace(lv[:, 1], right, -80, 0, 40, 260)
    dcv = channel_features(x, 0.25)['dc'] * 100
    span = max(10.0, float(np.ceil(np.abs(dcv).max() / 10.0) * 10.0))
    for v in (-span, 0, span):
        yy = ytrace(v, -span, span, 290, 430)
        d.line((mx, yy, rx, yy), fill='#2a323a' if v == 0 else '#1d252c')
        d.text((10, yy - 5), '%+d%%' % v, fill='#5b6b76', font=font)
    trace(dcv[:, 0], left, -span, span, 290, 430)
    trace(dcv[:, 1], right, -span, span, 290, 430)
    mono = np.asarray(x[:, :2], dtype=np.float64).mean(axis=1)
    sg = sg_full(mono)
    idx = (np.clip((sg + 90.0) / 90.0, 0.0, 1.0) * 255).astype(np.uint8)
    pic = np.ascontiguousarray(np.transpose(palette()[idx], (1, 0, 2))[::-1])
    img.paste(Image.fromarray(pic).resize((pw - 2, 238), Image.Resampling.BILINEAR), (mx + 1, 461))
    step = next((s for s in (1, 2, 5, 10, 15, 30, 60, 120, 300) if dur / s <= 24), 600)
    for k in range(int(dur // step) + 1):
        xx = xt(k * step)
        d.line((xx, 700, xx, 705), fill='#8fa3b0')
        d.text((xx - 12, 707), fmt_time(k * step), fill='#8fa3b0', font=font)
    colors = {'L': left, 'R': right, 'both': '#e6edf2'}
    shown = [q for q in findings if q['severity'] >= 3][:24]
    for i, q in enumerate(shown):
        xx = xt(q['t'])
        d.line((xx, 40, xx, 700), fill=colors[q['channel']], width=1)
        d.text((xx + 2, 42 + 11 * (i % 8)), marker_name(q)[1:], fill=colors[q['channel']], font=font)
    d.text((10, 725), 'FINDINGS (%d)' % len(findings), fill='#e6edf2', font=font)
    for i, line in enumerate(lines or ['nothing found']):
        d.text((10, 742 + 13 * i), line, fill='#b8c4cc', font=font)
    return img


def compare_clips(a, b, seg_s=8.0, hop_s=4.0):
    """segment by segment, for two Clips: where does each stretch of a sit in b (the offset can change along the clip), how alike are the two there, and what differs
    -> [dict(t, offset, score, level_l, level_r, dc_l, dc_r, null, verdict)]"""
    ca, cb = comp(a.data, a.vol_db).astype(np.float64), comp(b.data, b.vol_db).astype(np.float64)
    cache = {}
    rows = []
    for t0 in np.arange(0.0, a.duration - 2.0 + 1e-9, hop_s):
        t1 = min(a.duration, t0 + seg_s)
        seg = ca[int(t0 * SR):int(t1 * SR)]
        if len(seg) < SR or float(np.abs(seg).max()) < 1e-4:
            continue
        lag, score = auto_align(a.data, b.data, a.vol_db, b.vol_db, a_range=(t0, t1), cache=cache)
        ib = int(round((t0 + lag) * SR))
        row = dict(t=round(float(t0), 2), offset=round(lag, 3), score=round(score, 2))
        if ib < 0 or ib + len(seg) > len(cb):
            row.update(level_l=None, level_r=None, dc_l=None, dc_r=None, null=None, verdict='no match inside the other clip')
            rows.append(row)
            continue
        other = cb[ib:ib + len(seg)]
        lvl = [10 * math.log10(max(float(np.mean((other[:, c] - other[:, c].mean()) ** 2)), 1e-20) / max(float(np.mean((seg[:, c] - seg[:, c].mean()) ** 2)), 1e-20)) for c in (0, 1)]
        dcd = [100 * float(other[:, c].mean() - seg[:, c].mean()) for c in (0, 1)]
        sa, sb = seg - seg.mean(axis=0), other - other.mean(axis=0)  # the null test is about the sound: the DC offsets are reported on their own
        ea = float(np.sum(sa ** 2))
        g = math.sqrt(ea / max(float(np.sum(sb ** 2)), 1e-20))
        null = 10 * math.log10(max(float(np.sum((sa - g * sb) ** 2)), 1e-20) / max(ea, 1e-20))
        if score < 0.6:
            verdict = 'different sound'
        elif max(abs(dcd[0]), abs(dcd[1])) > 4:
            verdict = 'DC offset differs (%s)' % ' and '.join(CHANNEL_NAMES[CHANNELS[c]].lower() for c in (0, 1) if abs(dcd[c]) > 4)
        elif abs(lvl[0] - lvl[1]) > 6:
            verdict = 'one channel differs (%s %+.0f dB)' % ('left' if abs(lvl[0]) > abs(lvl[1]) else 'right', lvl[0] if abs(lvl[0]) > abs(lvl[1]) else lvl[1])
        elif score >= 0.9 and abs(lvl[0]) <= 1.5 and abs(lvl[1]) <= 1.5 and null <= -20:
            verdict = 'same'
        elif score >= 0.9 and (abs(lvl[0]) > 1.5 or abs(lvl[1]) > 1.5):
            verdict = 'level differs (%+.1f dB)' % ((lvl[0] + lvl[1]) / 2)
        else:
            verdict = 'similar but changed'
        row.update(level_l=round(lvl[0], 1), level_r=round(lvl[1], 1), dc_l=round(dcd[0], 1), dc_r=round(dcd[1], 1), null=round(null, 1), verdict=verdict)
        rows.append(row)
    return rows


def format_comparison(rows, name_a='A', name_b='B'):
    lines = ['%s against %s, segment by segment (%s level and DC are measured per channel, where the segment of A was found in B)' % (name_a, name_b, name_b),
             '%-8s %9s %6s  %-12s %-12s %7s  %s' % ('at (A)', 'found at', 'match', 'level L / R', 'DC L / R', 'null', 'verdict')]
    for r in rows:
        if r['level_l'] is None:
            lines.append('%-8s %+8.2fs %6.2f  %-12s %-12s %7s  %s' % (fmt_time(r['t']), r['offset'], r['score'], '--', '--', '--', r['verdict']))
        else:
            lines.append('%-8s %+8.2fs %6.2f  %+5.1f/%+5.1f  %+5.1f/%+5.1f %6.1f   %s' % (fmt_time(r['t']), r['offset'], r['score'], r['level_l'], r['level_r'], r['dc_l'], r['dc_r'], r['null'], r['verdict']))
    return lines


def analyze_files(paths, out=None):
    """the --analyze command: for every WAV a text report, a JSON file and an overview picture next to it; for two WAVs also the segment comparison.  -> the text"""
    clips = [Clip.load(p) for p in paths]
    text = []
    for p, c in zip(paths, clips):
        found = find_problems(c.data, c.vol_db)
        base = os.path.splitext(p)[0] + '.analysis'
        lines = ['%s  (%s long, recorded at Windows volume %s dB)' % (os.path.basename(p), fmt_time(c.duration, True), ('%.1f' % c.vol_db) if c.vol_db is not None else 'unknown')] + (format_findings(found) or ['no problems found'])
        text += lines + ['']
        open(base + '.txt', 'w', encoding='utf-8').write(_NL.join(lines) + _NL)
        json.dump(dict(file=os.path.basename(p), duration=c.duration, vol_db=c.vol_db, findings=found), open(base + '.json', 'w'), indent=1)
        findings_image(c.data, c.vol_db, found, os.path.basename(p)).save(base + '.png')
    if len(clips) >= 2:
        rows = compare_clips(clips[0], clips[1])
        lines = format_comparison(rows, os.path.basename(paths[0]), os.path.basename(paths[1]))
        text += lines
        base = os.path.splitext(paths[0])[0] + '.vs.' + os.path.splitext(os.path.basename(paths[1]))[0]
        open(base + '.txt', 'w', encoding='utf-8').write(_NL.join(lines) + _NL)
        json.dump(rows, open(base + '.json', 'w'), indent=1)
    return _NL.join(text)


# ---------------------------------------------------------------- the application
WINDOWS = sys.platform == 'win32'
MACOS = sys.platform == 'darwin'
FLAT_BUTTONS = MACOS  # macOS draws tk.Button in the system colours, so buttons are drawn by FlatButton there
FROZEN = bool(getattr(sys, 'frozen', False))  # running as a packaged program
HERE = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
if FROZEN and MACOS:
    REC_DIR = os.path.expanduser('~/Documents/PC Audio Scope/recordings')  # not inside the .app bundle
else:
    REC_DIR = os.path.join(HERE, 'recordings')
if WINDOWS:
    _CONFIG = os.environ.get('APPDATA') or HERE
elif MACOS:
    _CONFIG = os.path.expanduser('~/Library/Application Support')
else:
    _CONFIG = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
SETTINGS = os.path.join(_CONFIG, 'PC Audio Scope', 'settings.json')
MAX_REC = SR * 600  # longest recording / live comparison: 10 minutes
HIST_BLOCKS = 3000  # the level history shows 30 s of 10 ms blocks
FONTS = {'Segoe UI': 'Segoe UI', 'Consolas': 'Consolas'}  # the two faces the window asks for, as this system calls them
if MACOS:
    FONTS = {'Segoe UI': 'Helvetica Neue', 'Consolas': 'Menlo'}
elif not WINDOWS:
    FONTS = {'Segoe UI': 'DejaVu Sans', 'Consolas': 'DejaVu Sans Mono'}


def mix(a, b, t):
    """blend two '#rrggbb' colours: t = 0 gives a, t = 1 gives b"""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * t) for x, y in zip(pa, pb))


def draw_icon(n=256):
    """the application icon as an n x n RGBA picture: a dark rounded square with a graticule and two glowing traces.  The window and taskbar icon and the icon of the program file
    (packaging/make_icon.py writes icon.ico and icon.icns from this) are the same picture"""
    from PIL import ImageDraw, ImageFilter
    k = n / 1024.0
    px = lambda v: max(1, int(round(v * k)))

    def trace(color, phase, amp, freq):
        pts = []
        for i in range(0, 725, 4):
            t = i / 724.0
            pts.append(((150 + i) * k, n / 2.0 + amp * k * math.sin(2 * math.pi * freq * t + phase) * (0.55 + 0.45 * math.sin(math.pi * t))))
        glow = Image.new('RGBA', (n, n), (0, 0, 0, 0))
        ImageDraw.Draw(glow).line(pts, fill=color + (255,), width=px(70), joint='curve')
        glow = glow.filter(ImageFilter.GaussianBlur(34 * k))
        core = Image.new('RGBA', (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(core)
        d.line(pts, fill=color + (255,), width=px(26), joint='curve')
        light = tuple(min(255, c + 120) for c in color)
        d.line(pts, fill=light + (255,), width=px(9), joint='curve')
        return glow, core
    tile = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.rounded_rectangle((28 * k, 28 * k, n - 28 * k, n - 28 * k), radius=210 * k, fill=(7, 11, 17, 255), outline=(52, 64, 78, 255), width=px(10))
    for i in range(1, 8):  # graticule
        p = (28 + i * (1024 - 56) / 8.0) * k
        d.line([(p, 90 * k), (p, n - 90 * k)], fill=(26, 34, 44, 255), width=px(4))
        d.line([(90 * k, p), (n - 90 * k, p)], fill=(26, 34, 44, 255), width=px(4))
    d.line([(90 * k, n / 2.0), (n - 90 * k, n / 2.0)], fill=(40, 52, 66, 255), width=px(6))
    layers = [trace((255, 138, 31), 0.0, 230, 1.5), trace((47, 181, 255), 1.9, 190, 2.5)]
    for glow, _ in layers:
        tile = Image.alpha_composite(tile, glow)
    for _, core in layers:
        tile = Image.alpha_composite(tile, core)
    mask = Image.new('L', (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle((28 * k, 28 * k, n - 28 * k, n - 28 * k), radius=210 * k, fill=255)
    tile.putalpha(Image.composite(tile.getchannel('A'), Image.new('L', (n, n), 0), mask))
    return tile


def beam_points(xy, step=0.8, limit=120000, power=1.0, max_bits=64):
    """xy: (m, 2) pixel positions of consecutive samples.  Cuts every straight piece between two samples into bits of at most `step` pixels and gives each bit its share of that
    sample's energy (1 / number of bits): a slow beam puts all of it on a few pixels, a fast one spreads it thin, so slow is bright and fast is dim, like the beam of a CRT.
    `power` below 1 keeps fast pieces brighter than the physical 1 (the weight of a bit is n ** -power); useful for graphs that have to stay readable.
    Returns (points (k, 2), weights (k,))"""
    a, b = xy[:-1], xy[1:]
    d = np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])
    n = np.clip(np.ceil(d / step), 1, max_bits).astype(np.int64)
    if n.sum() > limit:  # a noisy signal: fewer bits, never more than the drawing can afford
        n = np.maximum(1, (n * (limit / float(n.sum()))).astype(np.int64))
    seg = np.repeat(np.arange(len(n)), n)
    first = np.cumsum(n) - n
    t = (np.arange(int(n.sum())) - np.repeat(first, n) + 0.5) / n[seg]
    pts = a[seg] + (b - a)[seg] * t[:, None]
    return pts, n[seg] ** -power


def beam_splat(buf, pts, w):
    """adds the weights w into the pixels around the points (each point is shared between its four neighbours), in place; points off the picture are dropped"""
    h, wd = buf.shape
    x, y = pts[:, 0], pts[:, 1]
    keep = (x >= 0) & (x < wd - 1) & (y >= 0) & (y < h - 1)
    x, y, w = x[keep], y[keep], w[keep]
    if not len(x):
        return
    x0, y0 = x.astype(np.int64), y.astype(np.int64)
    fx, fy = x - x0, y - y0
    idx = y0 * wd + x0
    flat = buf.reshape(-1)
    lo, hi = int(idx.min()), int(idx.max()) + wd + 2  # only the stretch of the picture the points can touch is summed
    part = np.bincount(np.concatenate([idx, idx + 1, idx + wd, idx + wd + 1]) - lo,
                       weights=np.concatenate([w * (1 - fx) * (1 - fy), w * fx * (1 - fy), w * (1 - fx) * fy, w * fx * fy]), minlength=hi - lo)
    flat[lo:hi] += part[:hi - lo]


def rgbtuple(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def beam_palette(bg, color, light=False):
    """brightness 0..255 -> colour: the background, the colour, and white-hot at the brightest.  With light=True the colours are only what the beam adds to the background (0 for no
    brightness), to be added over a picture of the background"""
    b = np.array([int(bg[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    c = np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
    t = np.linspace(0.0, 1.0, 256, dtype=np.float32)[:, None]
    body = b + (c - b) * np.minimum(1.0, t * 1.15)
    hot = np.clip((t - 0.55) / 0.45, 0.0, 1.0) * 0.75
    rgb = np.clip(body + (255.0 - body) * hot, 0, 255)
    return np.clip(rgb - b, 0, 255).astype(np.uint8) if light else rgb.astype(np.uint8)


class BeamScreen:
    """a simulated phosphor screen of w x h pixels (square when h is left out, like the vectorscope's).  The samples are a path (see beam_points); their energy is added into a buffer
    that fades by itself (persistence), and drawing it adds a soft glow around everything that is bright"""
    TAU = 0.05  # seconds for the phosphor to fade to 1/e
    EXPOSURE = 1.3

    def __init__(self, w, h=None, tau=None, exposure=None):
        self.w, self.h = int(w), int(h or w)
        self.size = self.w
        self.tau = self.TAU if tau is None else tau
        self.exposure = self.EXPOSURE if exposure is None else exposure
        self.buf = np.zeros((self.h, self.w), np.float32)

    def clear(self):
        self.buf[:] = 0.0

    def add_path(self, xs, ys, dt, power=1.0, max_bits=64):
        """the beam draws the path through the points (pixel positions, in time order) during dt seconds; the screen has faded for that long first"""
        self.buf *= math.exp(-dt / self.tau)
        if len(xs) < 2:
            return
        pts, w = beam_points(np.stack([np.asarray(xs, np.float64), np.asarray(ys, np.float64)], axis=1), power=power, max_bits=max_bits)
        beam_splat(self.buf, pts, w)

    def add(self, u, v, dt):
        """u, v: consecutive samples of the left and right channel (-1 .. 1 is the whole screen), dt: the seconds they cover"""
        hx, hy = (self.w - 1) / 2.0, (self.h - 1) / 2.0
        self.add_path(hx * (1.0 + 0.96 * np.asarray(u, np.float64)), hy * (1.0 - 0.96 * np.asarray(v, np.float64)), dt)

    def render(self, lut, glow=1.0):
        """the screen as an RGB picture (glow: how strong the halo is, 0 for none).  Everything after the brightness is done on 8-bit pictures in the imaging library"""
        from PIL import ImageChops, ImageFilter
        x = self.buf * self.exposure
        im = Image.fromarray(((x / (1.0 + x)) * 255.0).astype(np.uint8), 'L')  # brightness 0..255: grows quickly at first, then levels off
        k = min(self.w, self.h) / 276.0
        g1 = im.filter(ImageFilter.GaussianBlur(max(0.8, 1.4 * k))).point(_gain_table(0.8 * glow))
        small = im.resize((max(8, self.w // 4), max(8, self.h // 4)), Image.Resampling.BOX).filter(ImageFilter.GaussianBlur(max(0.6, 1.5 * k)))
        g2 = small.resize((self.w, self.h), Image.Resampling.BILINEAR).point(_gain_table(0.6 * glow))  # the wide glow is soft, so a quarter of the pixels do
        out = ImageChops.add(ImageChops.add(im, g1), g2)
        out.putpalette(lut.reshape(-1).tolist())
        return out.convert('RGB')


_GAIN_TABLES = {}


def _gain_table(gain):
    """a 256-entry table that multiplies a brightness by `gain`, stopping at 255"""
    key = round(gain, 3)
    if key not in _GAIN_TABLES:
        _GAIN_TABLES[key] = [min(255, int(i * key)) for i in range(256)]
    return _GAIN_TABLES[key]


def plot_base(w, h, bg, grid, peak=None, rows=(), cols=(), bands=(), tint=None, middle=False, frame=True):
    """the background picture of a graph (h, w, 3): the colour bg, tinted bands (pairs of x), vertical lines `cols`, a frame, a centre line and horizontal lines `rows`
    (the first one in the colour `peak` when that is given)"""
    def rgb(c):
        return np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)], np.uint8)
    a = np.empty((h, w, 3), np.uint8)
    a[:] = rgb(bg)
    for x_a, x_b in bands:
        a[:, max(0, x_a):max(0, x_b)] = rgb(tint)
    g = rgb(grid)
    if frame:
        a[0, :] = g
        a[-1, :] = g
        a[:, 0] = g
        a[:, -1] = g
    for x in cols:
        a[:, min(w - 1, max(0, x))] = g
    if middle:
        a[h // 2, :] = g
    for i, y in enumerate(rows):
        a[min(h - 1, max(0, y)), :] = rgb(peak) if (peak and i == 0) else g
    return a


class BeamPlot:
    """a graph drawn like the vectorscope: a phosphor screen for each channel, added over a background picture (the grid) and shown as one picture.  Graphs wider than MAX_W are
    drawn smaller and enlarged, which keeps a big graph fast"""
    MAX_W = 700

    def __init__(self, base, bg, colors, tau, exposure, power=1.0, max_bits=64, glow=1.0, blend='add'):
        self.h, self.w = base.shape[:2]
        self.f = min(1.0, self.MAX_W / float(self.w))
        rw, rh = max(8, int(round(self.w * self.f))), max(8, int(round(self.h * self.f)))
        self.screens = [BeamScreen(rw, rh, tau, exposure) for _ in range(2)]
        self.luts = [beam_palette(bg, c, light=True) for c in colors]
        self.base = Image.fromarray(base, 'RGB')
        self.power, self.max_bits, self.glow, self.blend = power, max_bits, glow, blend  # blend: where the two channels overlap, 'add' their light (white-hot) or keep the 'max' of the two (each keeps its colour)

    def clear(self):
        for sc in self.screens:
            sc.clear()

    def add(self, ch, xs, ys, dt):
        """channel ch draws the path through the points (pixel positions in the graph) during dt seconds"""
        self.screens[ch].add_path(np.asarray(xs, np.float64) * self.f, np.asarray(ys, np.float64) * self.f, dt, self.power, self.max_bits)

    def image(self):
        from PIL import ImageChops
        light = None
        for sc, lut in zip(self.screens, self.luts):
            im = sc.render(lut, self.glow)
            light = im if light is None else (ImageChops.lighter(light, im) if self.blend == 'max' else ImageChops.add(light, im))
        if self.f != 1.0:
            light = light.resize((self.w, self.h), Image.Resampling.BILINEAR)  # one enlargement for both channels
        return ImageChops.add(self.base, light)  # light added to the background, never past white


class BeamVector:
    """the vectorscope's screen with its palette: the new samples go in, a picture `side` pixels wide comes out"""

    def __init__(self, size, side, lut):
        self.screen = BeamScreen(size)
        self.side, self.lut = side, lut

    def image(self):
        img = self.screen.render(self.lut)
        return img if img.size[0] == self.side else img.resize((self.side, self.side), Image.Resampling.BILINEAR)


class BeamWorker:
    """draws one graph on a thread of its own, so the window never waits for it.  The owner hands it jobs (functions that put new data into the graph; they are run in order, and
    everything that has piled up is drawn as one picture) and takes the newest finished picture.  Only the worker touches the graph.  Without a thread (threaded=False, for the
    tests) a job is run and the picture made at once"""

    def __init__(self, plot, threaded=True):
        self.plot, self.threaded = plot, threaded
        self.image, self.seq, self.taken, self.error = None, 0, 0, None
        self.lock = threading.Lock()
        self.jobs = queue.Queue()
        self.thread = None
        if threaded:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def add(self, job):
        if self.threaded:
            self.jobs.put(job)
        else:
            job(self.plot)
            self._draw()

    def _draw(self):
        img = self.plot.image()
        with self.lock:
            self.image, self.seq = img, self.seq + 1

    def _run(self):
        try:  # below the window's own thread, so the window is served first when every core is busy
            ctypes.windll.kernel32.SetThreadPriority(ctypes.windll.kernel32.GetCurrentThread(), -1)
        except Exception:
            pass
        while True:
            job = self.jobs.get()
            if job is None:
                return
            batch = [job]
            try:
                while True:
                    batch.append(self.jobs.get_nowait())
            except queue.Empty:
                pass
            if None in batch:
                return
            try:
                for j in batch:
                    j(self.plot)
                self._draw()
            except Exception:
                self.error = traceback.format_exc()

    def take(self):
        """the picture made since the last call, or None"""
        with self.lock:
            if self.seq == self.taken:
                return None
            self.taken = self.seq
            return self.image

    def stop(self):
        if self.threaded:
            self.jobs.put(None)


class Theme:
    """the colours of the window: a background, one colour for each channel and a tint for the text; the rest is blended from those"""
    def __init__(self, name, bg, left, right, lname, rname, tint='#b8c4cc', accent='#4a90d9', vec=None, a=None, b=None, mark=None, on=None, spec=None, glow=True, good=None, live=None, peak=None):
        self.name, self.bg, self.left, self.right, self.lname, self.rname = name, bg, left, right, lname, rname
        self.txt = tint
        self.fg = mix(tint, '#ffffff', 0.65)
        self.grid = mix(bg, tint, 0.17)
        self.panel = mix(bg, tint, 0.045)
        self.btn = mix(bg, tint, 0.13)
        self.btn_hi = mix(bg, tint, 0.25)
        self.sel = mix(bg, tint, 0.22)
        self.dim = mix(bg, tint, 0.8)
        self.faint = mix(bg, tint, 0.5)
        self.dash = mix(bg, tint, 0.28)
        self.tl_bg = mix(bg, '#000000', 0.3)
        self.lane = bg
        self.lane_edge = mix(bg, tint, 0.1)
        self.tick = mix(bg, tint, 0.08)
        self.accent = accent
        self.accent_hi = mix(accent, '#ffffff', 0.45)
        self.on = on or mix(bg, accent, 0.6)
        self.vec = vec or left
        self.good = good or self.vec
        self.live = live or self.good
        self.peak = peak or mix(left, '#ffffff', 0.45)  # the 0 dBFS lines and the clipped-block marks
        self.a, self.b = a or left, b or right  # clip A and clip B when comparing
        self.mark_a, self.mark_b = mark or (self.a, self.b)
        self.env_l, self.env_r = mix(bg, left, 0.55), mix(bg, right, 0.55)
        self.env_a, self.env_b = mix(bg, self.a, 0.5), mix(bg, self.b, 0.45)
        self.spec = spec  # base colour of the spectrogram palette (None: the multi-colour one)
        self.glow = glow  # draw the traces with a soft halo, like a phosphor screen


THEMES = [
    Theme('Classic', '#101418', '#ff5a4d', '#ffd23f', 'red', 'yellow', vec='#57e0a8', a='#ff8a7d', b='#7fd0ff', mark=('#ffb347', '#7fd0ff'), on='#2a6a8f', glow=False, good='#57e0a8', live='#7bd88f', peak='#ff4040'),
    Theme('Green phosphor', '#030b06', '#2bff70', '#c4ffd6', 'green', 'pale green', tint='#8fe8ad', accent='#27c45f', spec='#2bff70'),
    Theme('Amber phosphor', '#0c0702', '#ffa31a', '#ffe6a8', 'amber', 'pale amber', tint='#f0c070', accent='#d98a14', spec='#ffa31a'),
    Theme('Blue phosphor', '#030812', '#3aa8ff', '#c4e6ff', 'blue', 'ice', tint='#8fc4f0', accent='#2f86e0', spec='#3aa8ff'),
    Theme('Red phosphor', '#0d0405', '#ff3b30', '#ffc2bd', 'red', 'pink', tint='#f09890', accent='#d6332b', spec='#ff3b30'),
    Theme('Orange + blue', '#07090d', '#ff8a1f', '#2fb5ff', 'orange', 'blue', spec='#ff8a1f'),
    Theme('Green + magenta', '#06080b', '#39ff6a', '#ff3df0', 'green', 'magenta', spec='#39ff6a'),
    Theme('Red + cyan', '#08090c', '#ff4a3d', '#2ff0e8', 'red', 'cyan', spec='#ff4a3d'),
]


# ---------------------------------------------------------------- undoing a system equaliser (Equalizer APO)
# Windows loopback records the sound after the audio engine's stream effects, so an equaliser such as Equalizer APO is IN what the scope hears.  A headphone correction curve is full of
# phase shifts, and the pictures of oscilloscope music (which depend on every frequency arriving on time) come out bent.  The parametric filters in the Equalizer APO configuration
# of the output are read here and undone with their exact inverse (every peaking and shelf filter is minimum phase, so the inverse is stable).
EQ_UNDOABLE = ('PK', 'PEQ', 'LSC', 'HSC')


def eq_biquad(kind, fs, fc, gain_db, q):
    """the coefficients (b, a with a[0] = 1) of an Equalizer APO peaking or shelving filter (the RBJ cookbook forms with a Q)"""
    w0 = 2 * math.pi * fc / fs
    A = 10 ** (gain_db / 40.0)
    alpha = math.sin(w0) / (2.0 * q)
    cw = math.cos(w0)
    if kind in ('PK', 'PEQ'):
        b, a = (1 + alpha * A, -2 * cw, 1 - alpha * A), (1 + alpha / A, -2 * cw, 1 - alpha / A)
    else:
        sq = 2 * math.sqrt(A) * alpha
        if kind == 'LSC':
            b = (A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq))
            a = ((A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq)
        else:  # HSC
            b = (A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq))
            a = ((A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq)
    return np.array(b) / a[0], np.array(a) / a[0]


def eq_response(filters, preamp_db, fs, f):
    """the complex response of the equaliser (a preamp and a cascade of filters) at the frequencies f, for an audio engine running at fs"""
    z = np.exp(-1j * 2 * np.pi * np.asarray(f, dtype=np.float64) / fs)
    h = np.full(len(z), 10 ** (preamp_db / 20.0), dtype=np.complex128)
    for kind, fc, gain, q in filters:
        b, a = eq_biquad(kind, fs, fc, gain, q)
        h *= (b[0] + b[1] * z + b[2] * z ** 2) / (1 + a[1] * z + a[2] * z ** 2)
    return h


def eq_inverse_fir(preamp_db, filters, mix_rate, out_rate=SR, taps=4096):
    """the FIR filter (at out_rate, the rate of the capture) that undoes the equaliser the audio engine ran at mix_rate.  Its magnitude is the exact inverse of the equaliser's and it is
    built minimum phase (from the cepstrum), which is what the inverse of a cascade of peaking and shelf filters is"""
    n = 65536
    f = np.arange(n // 2 + 1) * float(out_rate) / n
    mag = np.ones(len(f))
    ok = f < mix_rate / 2.0  # above the engine's own Nyquist frequency there is nothing to undo
    mag[ok] = 1.0 / np.abs(eq_response(filters, preamp_db, float(mix_rate), f[ok]))
    c = np.fft.irfft(np.log(mag), n)  # the cepstrum of the magnitude; folding it makes the filter causal
    folded = np.zeros(n)
    folded[0] = c[0]
    folded[1:n // 2] = 2 * c[1:n // 2]
    folded[n // 2] = c[n // 2]
    h = np.fft.ifft(np.exp(np.fft.fft(folded))).real[:taps]
    fade = taps // 4
    h[-fade:] *= 0.5 * (1 + np.cos(np.pi * np.arange(fade) / fade))  # the last quarter fades out; the rest is untouched
    return h


class StreamFir:
    """a FIR filter for a stream of blocks (each channel on its own): the answer to a block is the same as if the whole stream had been filtered in one go"""

    def __init__(self, taps, channels=2):
        self.fir = _Fir(taps)
        self.keep = len(taps) - 1
        self.hist = np.zeros((self.keep, channels))

    def process(self, blk):
        x = np.concatenate([self.hist, np.asarray(blk, dtype=np.float64)], axis=0)
        self.hist = x[len(x) - self.keep:]
        return np.stack([self.fir.valid(x[:, c]) for c in range(x.shape[1])], axis=1).astype(np.float32)


def eq_device_match(selector, endpoint_id, endpoint_name):
    """does a `Device:` selector of Equalizer APO (all, a part of the name, or a name with the {guid} of the endpoint) select this output?"""
    sel = selector.strip()
    if sel.lower() == 'all':
        return True
    guid = re.search(r'[{]([0-9a-fA-F-]{36})[}]', sel)
    if guid:
        return guid.group(1).lower() in endpoint_id.lower()
    words = [w for w in re.split(r'[^a-z0-9]+', sel.lower()) if w]
    name = endpoint_name.lower()
    return bool(words) and all(w in name for w in words)


def eqapo_read(path, endpoint_id, endpoint_name, out, active=True, depth=0):
    """reads an Equalizer APO configuration file (and what it includes) for one output: out gets the preamp, the filters, the things it cannot undo and the files it read"""
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
        out['files'].append((path, os.path.getmtime(path)))
    except OSError:
        return active
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        key, _, val = line.partition(':')
        k = re.sub(r'[ 0-9]+$', '', key.strip().lower())  # 'Filter 3' is a Filter
        if k == 'device':
            active = any(eq_device_match(sel, endpoint_id, endpoint_name) for sel in val.split(';'))
        elif not active:
            continue
        elif k == 'include' and depth < 8:
            target = val.strip()
            target = target if os.path.isabs(target) else os.path.join(os.path.dirname(path), target)
            active = eqapo_read(target, endpoint_id, endpoint_name, out, active, depth + 1)
        elif k in ('preamp', 'gain'):
            g = re.search(r'-?[0-9.]+', val)
            if g:
                out['preamp'] += float(g.group(0))
        elif k == 'filter':
            m_ = re.match(r'\s*(ON|OFF)\s+([A-Za-z]+)(.*)', val, re.I)
            if not m_:
                out['unsupported'].append(line[:40])
            elif m_.group(1).upper() == 'ON':
                kind, rest = m_.group(2).upper(), m_.group(3)
                fc, gn, q = (re.search(r'\b%s\s+(-?[0-9.]+)' % tag, rest, re.I) for tag in ('Fc', 'Gain', 'Q'))
                if kind in EQ_UNDOABLE and fc and gn and q:
                    out['filters'].append(('PK' if kind == 'PEQ' else kind, float(fc.group(1)), float(gn.group(1)), float(q.group(1))))
                else:
                    out['unsupported'].append('Filter ' + kind)
        else:
            out['unsupported'].append(k)
    return active


def eqapo_config_dir():
    """where Equalizer APO keeps its configuration, or None"""
    if not WINDOWS:
        return None
    try:
        import winreg
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE' + chr(92) + 'EqualizerAPO', 0, winreg.KEY_READ | view) as key:
                    path = winreg.QueryValueEx(key, 'InstallPath')[0]
                    if os.path.isdir(os.path.join(path, 'config')):
                        return os.path.join(path, 'config')
            except OSError:
                continue
    except Exception:
        pass
    for base in (os.environ.get('ProgramFiles', 'C:' + chr(92) + 'Program Files'), os.environ.get('ProgramFiles(x86)', '')):
        if base and os.path.isdir(os.path.join(base, 'EqualizerAPO', 'config')):
            return os.path.join(base, 'EqualizerAPO', 'config')
    return None


def mix_rate_from_blob(blob):
    """the sample rate in an endpoint's device format (a PROPVARIANT blob in the registry: 8 bytes of header, then a WAVEFORMATEX); 48000 when it cannot be read"""
    try:
        return int(struct.unpack_from('<I', blob, 12)[0]) or 48000
    except Exception:
        return 48000


def endpoint_mix_rate(endpoint_id):
    """the sample rate the Windows audio engine mixes this output at"""
    guid = re.search(r'[{]([0-9a-fA-F-]{36})[}]', endpoint_id or '')
    if not (WINDOWS and guid):
        return 48000
    try:
        import winreg
        path = 'SOFTWARE' + chr(92) + 'Microsoft' + chr(92) + 'Windows' + chr(92) + 'CurrentVersion' + chr(92) + 'MMDevices' + chr(92) + 'Audio' + chr(92) + 'Render' + chr(92) + '{%s}' % guid.group(1) + chr(92) + 'Properties'
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return mix_rate_from_blob(winreg.QueryValueEx(key, '{f19f064d-082c-4e27-bc73-6882a1bb8e4c},0')[0])
    except Exception:
        return 48000


def eq_undo_for(endpoint_id, endpoint_name, config_dir=None, mix_rate=None):
    """-> (StreamFir or None, what to say, [(file, modification time)]): the filter that undoes the Equalizer APO equaliser on this output.  Nothing is undone when the equaliser uses
    anything that is not a peaking or shelf filter (the sound would only be half corrected)"""
    cdir = config_dir or eqapo_config_dir()
    if not cdir:
        return None, '', []
    out = dict(preamp=0.0, filters=[], unsupported=[], files=[])
    eqapo_read(os.path.join(cdir, 'config.txt'), endpoint_id or '', endpoint_name or '', out)
    if not out['filters'] and not out['unsupported'] and out['preamp'] == 0.0:
        return None, '', out['files']
    if out['unsupported']:
        return None, 'Equalizer APO is in the sound (%s: not undone)' % ', '.join(sorted(set(out['unsupported']))[:3]), out['files']
    rate = mix_rate or endpoint_mix_rate(endpoint_id)
    return StreamFir(eq_inverse_fir(out['preamp'], out['filters'], rate)), 'Equalizer APO undone', out['files']


def fmt_time(t, fine=False):
    sign = '-' if t < 0 else ''
    m, s = divmod(abs(t), 60.0)
    return '%s%d:%04.1f' % (sign, m, s) if fine else '%s%d:%02d' % (sign, m, int(s))


class EndpointVolume:
    """read-only view of an output's Windows master volume (the default output when device_id is None)"""
    def __init__(self, device_id=None):
        from comtypes import GUID, IUnknown, COMMETHOD, CLSCTX_ALL
        from ctypes import POINTER, c_float, c_int, c_uint, c_void_p, c_wchar_p, byref, HRESULT

        class IAudioEndpointVolume(IUnknown):
            _iid_ = GUID('{5CDF2C82-841E-4546-9722-0CF74078229A}')
            _methods_ = [COMMETHOD([], HRESULT, 'RegisterControlChangeNotify', (['in'], c_void_p, 'n')),
                         COMMETHOD([], HRESULT, 'UnregisterControlChangeNotify', (['in'], c_void_p, 'n')),
                         COMMETHOD([], HRESULT, 'GetChannelCount', (['out'], POINTER(c_uint), 'c')),
                         COMMETHOD([], HRESULT, 'SetMasterVolumeLevel', (['in'], c_float, 'l'), (['in'], POINTER(GUID), 'c')),
                         COMMETHOD([], HRESULT, 'SetMasterVolumeLevelScalar', (['in'], c_float, 'l'), (['in'], POINTER(GUID), 'c')),
                         COMMETHOD([], HRESULT, 'GetMasterVolumeLevel', (['out'], POINTER(c_float), 'l')),
                         COMMETHOD([], HRESULT, 'GetMasterVolumeLevelScalar', (['out'], POINTER(c_float), 'l')),
                         COMMETHOD([], HRESULT, 'SetChannelVolumeLevel', (['in'], c_uint, 'n'), (['in'], c_float, 'l'), (['in'], POINTER(GUID), 'c')),
                         COMMETHOD([], HRESULT, 'SetChannelVolumeLevelScalar', (['in'], c_uint, 'n'), (['in'], c_float, 'l'), (['in'], POINTER(GUID), 'c')),
                         COMMETHOD([], HRESULT, 'GetChannelVolumeLevel', (['in'], c_uint, 'n'), (['out'], POINTER(c_float), 'l')),
                         COMMETHOD([], HRESULT, 'GetChannelVolumeLevelScalar', (['in'], c_uint, 'n'), (['out'], POINTER(c_float), 'l')),
                         COMMETHOD([], HRESULT, 'SetMute', (['in'], c_int, 'm'), (['in'], POINTER(GUID), 'c')),
                         COMMETHOD([], HRESULT, 'GetMute', (['out'], POINTER(c_int), 'm'))]

        class IMMDevice(IUnknown):
            _iid_ = GUID('{D666063F-1587-4E43-81F1-B948E807363F}')
            _methods_ = [COMMETHOD([], HRESULT, 'Activate', (['in'], POINTER(GUID), 'iid'), (['in'], c_uint, 'ctx'), (['in'], c_void_p, 'p'), (['out'], POINTER(c_void_p), 'o'))]

        class IMMDeviceEnumerator(IUnknown):
            _iid_ = GUID('{A95664D2-9614-4F35-A746-DE8DB63617E6}')
            _methods_ = [COMMETHOD([], HRESULT, 'EnumAudioEndpoints', (['in'], c_int, 'f'), (['in'], c_uint, 'm'), (['out'], POINTER(c_void_p), 'd')),
                         COMMETHOD([], HRESULT, 'GetDefaultAudioEndpoint', (['in'], c_int, 'f'), (['in'], c_int, 'r'), (['out'], POINTER(POINTER(IMMDevice)), 'd')),
                         COMMETHOD([], HRESULT, 'GetDevice', (['in'], c_wchar_p, 'id'), (['out'], POINTER(POINTER(IMMDevice)), 'd'))]
        enum = comtypes.CoCreateInstance(GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}'), IMMDeviceEnumerator, CLSCTX_ALL)
        dev = enum.GetDevice(device_id) if device_id else enum.GetDefaultAudioEndpoint(0, 1)
        p = dev.Activate(byref(IAudioEndpointVolume._iid_), CLSCTX_ALL, None)
        self.ev = ctypes.cast(p, POINTER(IAudioEndpointVolume))

    def read(self):
        """(dB, scalar 0..1, muted)"""
        return float(self.ev.GetMasterVolumeLevel()), float(self.ev.GetMasterVolumeLevelScalar()), bool(self.ev.GetMute())


class Clip:
    """a recording: float32 stereo at 48 kHz, the Windows volume (dB) it was recorded at, markers and an A-B selection"""
    def __init__(self, data, vol_db=None, path=None, markers=None, sel=None, name=None):
        self.data = np.ascontiguousarray(data, dtype=np.float32)
        self.vol_db = vol_db
        self.path = path
        self.markers = markers if markers is not None else []  # [{'t': seconds, 'name': 'M1'}]
        self.sel = sel
        self.name = name or (os.path.basename(path) if path else 'clip')
        self.peaks, self.flat = analyze(self.data)
        self.peak = float(np.abs(self.data).max()) if len(self.data) else 0.0
        self._ms = None
        self._sg = None
        self._int = {}
        self.findings = None  # set by find_problems

    @property
    def duration(self):
        return len(self.data) / SR

    @property
    def ms(self):
        if self._ms is None:
            self._ms = kweight_blocks(self.data)
        return self._ms

    @property
    def sg(self):
        if self._sg is None:
            self._sg = sg_full(self.data.astype(np.float64).mean(axis=1))
        return self._sg

    def integrated(self, offset_db=0.0):
        k = round(offset_db, 2)
        if k not in self._int:
            self._int[k] = integrated(self.ms, offset_db)
        return self._int[k]

    def meta(self):
        return {'vol_db': self.vol_db, 'markers': self.markers, 'sel': self.sel, 'saved': time.strftime('%Y-%m-%d %H:%M:%S')}

    def save_meta(self):
        if self.path:
            try:
                with open(os.path.splitext(self.path)[0] + '.json', 'w') as f:
                    json.dump(self.meta(), f)
            except Exception:
                pass

    def save(self, path):
        write_wav(path, SR, self.data)
        self.path = path
        self.name = os.path.basename(path)
        self.save_meta()

    def slice(self, t0, t1):
        i0, i1 = int(max(0.0, t0) * SR), int(min(self.duration, t1) * SR)
        return Clip(self.data[i0:i1], self.vol_db, name=self.name)

    @classmethod
    def load(cls, path):
        sr, x = read_wav(path)
        if x.dtype.kind == 'i':
            x = x.astype(np.float32) / float(np.iinfo(x.dtype).max)
        elif x.dtype.kind == 'u':
            x = (x.astype(np.float32) - 128.0) / 128.0
        else:
            x = x.astype(np.float32)
        if x.ndim == 1:
            x = np.stack([x, x], axis=1)
        if sr != SR:
            x = resample_poly(x, SR, sr, axis=0).astype(np.float32)
        meta = {}
        side = os.path.splitext(path)[0] + '.json'
        if os.path.exists(side):
            try:
                meta = json.load(open(side))
            except Exception:
                pass
        sel = meta.get('sel')
        return cls(x[:, :2], meta.get('vol_db'), path, meta.get('markers') or [], tuple(sel) if sel else None)


class Capture(threading.Thread):
    """reads the sound card on its own thread: a 2 s ring for the scopes, per-10 ms peak and loudness history, and the recording in progress"""
    def __init__(self):
        super().__init__(daemon=True)
        self.ring = np.zeros((SR * 2, 2), np.float32)
        self.pos = 0
        self.lock = threading.Lock()
        self.hist = deque(maxlen=HIST_BLOCKS + 100)  # (peak L, peak R) per 10 ms block: the 30 s that are shown and a little more
        self.ms = []  # K-weighted energy per 10 ms block since the last reset (for LUFS)
        self.kw = KWeight()
        self.sess = [0.0, 0.0]
        self.flat = [0, 0]
        self.device = '?'
        self.vol = None  # (dB, scalar, muted)
        self.error = None
        self.stop = False
        self.rec = None
        self.rec_pk = []
        self.rec_fl = []
        self.rec_frames = 0
        self.rec_vol = None
        self.devices = [dict(kind='default', id=None, label='Default output (what you hear)')]
        self.want = ('default', None)  # what the window asked for: ('default', None) | ('loopback', id) | ('mic', id)
        self.now = None  # what is open
        self.warn = ''
        self.refresh_req = True
        self.undo_eq = True  # undo a system equaliser (Equalizer APO) in the output's audio path
        self.eq_note = ''  # what to tell about it

    def push(self, blk):
        n = len(blk)
        pk = np.abs(blk).max(axis=0)
        fl = block_flags(blk)
        e = self.kw.energy(blk)
        with self.lock:
            i = self.pos % len(self.ring)
            if i + n <= len(self.ring):
                self.ring[i:i + n] = blk
            else:
                k = len(self.ring) - i
                self.ring[i:] = blk[:k]
                self.ring[:n - k] = blk[k:]
            self.pos += n
            self.hist.append((float(pk[0]), float(pk[1])))
            self.ms.append(e)
            for c in (0, 1):
                self.sess[c] = max(self.sess[c], float(pk[c]))
                if fl[c]:
                    self.flat[c] += 1
            if self.rec is not None:
                self.rec.append(blk.copy())
                self.rec_pk.append((float(pk[0]), float(pk[1])))
                self.rec_fl.append(tuple(fl))
                self.rec_frames += n

    def last(self, n):
        return self.window(self.pos, n)

    def window(self, end, n):
        """the n samples ending at absolute position `end` (must still be inside the 2 s ring)"""
        with self.lock:
            idx = (np.arange(end - n, end) % len(self.ring))
            return self.ring[idx].copy()

    def reset(self):
        with self.lock:
            self.sess = [0.0, 0.0]
            self.flat = [0, 0]
            self.ms = []

    def start_rec(self):
        with self.lock:
            self.rec, self.rec_pk, self.rec_fl, self.rec_frames = [], [], [], 0
            self.rec_vol = self.vol[0] if (self.vol and not self.vol[2]) else None

    def stop_rec(self):
        with self.lock:
            r, self.rec = self.rec, None
            vol = self.rec_vol
        if not r:
            return None, vol
        return np.concatenate(r), vol

    def rec_tail(self, n):
        """the last n frames of the recording in progress (a copy) and the time (s) of its first frame since the recording started"""
        with self.lock:
            if not self.rec:
                return np.zeros((0, 2), np.float32), 0.0
            k = max(1, n // BLOCK + 1)
            tail = np.concatenate(self.rec[-k:])
            total = self.rec_frames
        return tail, (total - len(tail)) / SR

    def list_devices(self, sc):
        devs = []
        if WINDOWS:
            try:
                devs.append(dict(kind='default', id=None, label='Default output (what you hear): ' + sc.default_speaker().name))
            except Exception:
                devs.append(dict(kind='default', id=None, label='Default output (what you hear)'))
            for sp in sc.all_speakers():
                devs.append(dict(kind='loopback', id=sp.id, label='Output: ' + sp.name))
        else:
            try:
                devs.append(dict(kind='default', id=None, label='Default input: ' + sc.default_microphone().name))
            except Exception:
                devs.append(dict(kind='default', id=None, label='Default input'))
        for mc in sc.all_microphones(include_loopback=False):
            devs.append(dict(kind='mic', id=mc.id, label='Microphone: ' + mc.name))
        self.devices = devs

    def set_source(self, kind, ident):
        self.want = (kind, ident)

    def open_source(self, sc, want):
        """-> (recorder source, label, endpoint id for the volume, is it a loopback, id that was opened)"""
        kind, ident = want
        if kind == 'default' and not WINDOWS:
            mic = sc.default_microphone()
            return mic, 'Input: ' + mic.name, None, False, mic.id
        if kind == 'mic':
            mic = sc.get_microphone(ident)
            return mic, 'Microphone: ' + mic.name, None, False, ident
        sp = sc.default_speaker() if kind == 'default' else sc.get_speaker(ident)
        mic = sc.get_microphone(sp.id, include_loopback=True)
        return mic, sp.name + ('' if kind == 'default' else '  (output)'), (None if kind == 'default' else sp.id), True, sp.id

    def run(self):
        try:
            warnings.filterwarnings('ignore')
            import soundcard as sc  # initialises COM itself, so it has to come before CoInitializeEx
            if WINDOWS:
                ctypes.windll.ole32.CoInitializeEx(None, 0)
            while not self.stop:
                if self.refresh_req:
                    self.refresh_req = False
                    self.list_devices(sc)
                want = self.want
                try:
                    mic, label, vol_dev, loop, opened = self.open_source(sc, want)
                except Exception as e:
                    self.warn = 'input not available (%s): using the default %s' % (str(e)[:50], 'output' if WINDOWS else 'input')
                    self.want = ('default', None)
                    time.sleep(0.5)
                    continue
                self.warn = ''
                self.device = label
                self.now = want
                ev = None
                if loop:
                    try:
                        ev = EndpointVolume(vol_dev)
                    except Exception:
                        ev = None
                else:
                    self.vol = None  # a microphone has no Windows output volume to add back
                eq_fir, eq_note, eq_key = None, '', None
                self.eq_note = ''
                try:
                    ch = 2 if getattr(mic, 'channels', 2) >= 2 else 1
                    with mic.recorder(samplerate=SR, channels=ch, blocksize=BLOCK) as rec:
                        k = 0
                        while not self.stop and self.want == want:
                            blk = np.asarray(rec.record(numframes=BLOCK), dtype=np.float32)
                            if blk.ndim == 1:
                                blk = blk[:, None]
                            if blk.shape[1] == 1:
                                blk = np.repeat(blk, 2, axis=1)
                            blk = blk[:, :2]
                            if loop and (eq_key is None or (k % 100 == 0 and eq_key[1] != [os.path.getmtime(f_) if os.path.exists(f_) else 0 for f_, _ in eq_key[2]]) or eq_key[0] != self.undo_eq):
                                eq_fir, eq_note, eq_files = eq_undo_for(opened, label)  # (again when the equaliser's files have changed, or the switch has been used)
                                eq_key = (self.undo_eq, [t_ for _, t_ in eq_files], eq_files)
                                if not self.undo_eq:
                                    eq_fir, eq_note = None, ('Equalizer APO is in the sound (U undoes it)' if eq_note else '')
                                self.eq_note = eq_note
                            if eq_fir is not None:
                                blk = eq_fir.process(blk)
                            self.push(blk)
                            k += 1
                            if ev is not None and k % 50 == 1:
                                try:
                                    self.vol = ev.read()
                                except Exception:
                                    pass
                            if k % 100 == 0:
                                if self.refresh_req:
                                    self.refresh_req = False
                                    self.list_devices(sc)
                                if want[0] == 'default' and (sc.default_speaker() if WINDOWS else sc.default_microphone()).id != opened:  # the system default changed: follow it
                                    break
                except Exception as e:
                    self.warn = 'input error: %s' % str(e)[:60]
                    time.sleep(1.0)
        except Exception:
            self.error = traceback.format_exc()


class LiveClip:
    """the live session seen as clip B of a live comparison: it reads the recording in progress"""
    name = 'live'

    def __init__(self, cap):
        self.cap = cap
        self.markers = []
        self._n = -1
        self._pk = np.zeros((1, 2), np.float32)

    @property
    def peaks(self):
        with self.cap.lock:
            n = len(self.cap.rec_pk)
            if n != self._n:
                self._pk = np.array(self.cap.rec_pk, dtype=np.float32).reshape(-1, 2) if n else np.zeros((1, 2), np.float32)
                self._n = n
        return self._pk

    @property
    def duration(self):
        return self.cap.rec_frames / SR

    @property
    def vol_db(self):
        return self.cap.rec_vol

    def save_meta(self):
        pass


class Player:
    """plays a clip through the default output; `pos` (frames) follows what has been played; optional loop over a region"""
    def __init__(self):
        self.clip = None
        self.pos = 0
        self.playing = False
        self.stream = None
        self.gain = 1.0
        self.loop = False
        self.region = None  # (first, last) frame of the loop
        self.error = None

    def load(self, clip, pos=0):
        self.stop()
        self.clip, self.pos = clip, pos

    def swap(self, clip, pos):
        """change the clip under a running stream (same time axis)"""
        self.pos = int(max(0, min(len(clip.data), pos)))
        self.clip = clip

    def set_gain(self, vol_now_db):
        c = self.clip
        if c is None:
            return
        g = 1.0
        if c.vol_db is not None and vol_now_db is not None:
            g = 10.0 ** (-vol_now_db / 20.0)  # Windows applies its volume again on playback: undo it, so the clip plays as loud as it was heard
        self.gain = min(g, 1.0 / max(c.peak, 1e-9))  # never past full scale

    def _cb(self, outdata, frames, time_info, status):
        c = self.clip
        data = c.data
        N = len(data)
        out = np.zeros((frames, 2), np.float32)
        filled = 0
        while filled < frames:
            lo, hi = (self.region if (self.loop and self.region and self.region[1] - self.region[0] > 64) else (0, N))
            hi = min(hi, N)
            if self.pos >= hi or self.pos < 0:
                if self.loop:
                    self.pos = lo
                else:
                    break
            end = min(hi, self.pos + frames - filled)
            if end <= self.pos:
                break
            n = end - self.pos
            out[filled:filled + n] = np.clip(data[self.pos:end] * self.gain, -1.0, 1.0)
            filled += n
            self.pos = end
            if self.pos >= hi and self.loop:
                self.pos = lo
            elif self.pos >= N:
                break
        outdata[:] = out
        if not self.loop and self.pos >= N:
            self.playing = False
            import sounddevice as sd
            raise sd.CallbackStop

    def play(self, vol_now_db):
        if self.clip is None:
            return
        if self.pos >= len(self.clip.data) - SR // 20:
            self.pos = 0
        self.set_gain(vol_now_db)
        try:
            import sounddevice as sd
            self.stop_stream()
            self.stream = sd.OutputStream(samplerate=SR, channels=2, dtype='float32', callback=self._cb, blocksize=1024)
            self.playing = True
            self.stream.start()
            self.error = None
        except Exception as e:
            self.playing = False
            self.error = 'audio output: %s' % e

    def stop_stream(self):
        s, self.stream = self.stream, None
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass

    def pause(self):
        self.playing = False
        self.stop_stream()

    def stop(self):
        self.pause()


class FlatButton(tk.Label):
    """a button that keeps the colours it is given, for macOS where tk.Button draws the system look and ignores them"""
    def __init__(self, master, command=None, **kw):
        self._command = command
        self._hover = kw.pop('activebackground', None)
        kw.pop('activeforeground', None)
        super().__init__(master, **kw)
        self._base = self.cget('bg')
        self._fg = self.cget('fg')
        self.bind('<Button-1>', lambda e: self.invoke())
        self.bind('<Enter>', lambda e: self._paint(self._hover) if self._hover and self.cget('state') != 'disabled' else None)
        self.bind('<Leave>', lambda e: self._paint(self._base))

    def _paint(self, color):
        tk.Label.configure(self, bg=color)

    def configure(self, cnf=None, **kw):
        for key in ('bg', 'background'):
            if key in kw:
                self._base = kw[key]
        if 'state' in kw:
            kw['fg'] = '#6b7780' if kw['state'] == 'disabled' else self._fg
        if 'fg' in kw:
            self._fg = kw['fg']
        return tk.Label.configure(self, cnf, **kw)

    config = configure

    def invoke(self):
        if self.cget('state') != 'disabled' and self._command:
            self._command()


def Button(master, **kw):
    return (FlatButton if FLAT_BUTTONS else tk.Button)(master, **kw)


class App:
    """the main window: a scope canvas, button rows and a timeline canvas; modes live | rec | review | compare; everything scales with self.k"""
    BASE_W, BASE_H, BASE_TH = 1240, 672, 188
    THREADED = True  # the graphs are drawn on threads of their own (the tests switch it off)
    HIST_OFFSETS = (-0.6, 0.0, 0.6)  # vertical offsets (pixels) the level history's line is drawn at: three passes a fraction of a pixel apart make a more solid line
    NUDGES = [('-1s', -1.0), ('-100ms', -0.1), ('-10ms', -0.01), ('-1ms', -0.001), ('+1ms', 0.001), ('+10ms', 0.01), ('+100ms', 0.1), ('+1s', 1.0)]

    def __init__(self, root, cap):
        self.root, self.cap = root, cap
        s = self.load_settings()
        self.paused = False
        self.gain = 1.0  # the scope's gain follows the sound by itself
        self.comp = False  # levels are shown as measured; the C key ignores the Windows volume until the program is closed
        self.spec_mode = s.get('spec_mode', 'spectrum')
        self.hold = [FLOOR, FLOOR]
        self.hold_t = [0.0, 0.0]
        self.bal_lv = [FLOOR, FLOOR]  # the levels the balance bars show (dB)
        self.beam, self.vec_last, self.vec_lut = None, None, None  # the vectorscope's screen, where it has drawn up to and its palette
        self.work_ms = 0.0  # how long a frame takes to draw, smoothed: a slow computer draws the oscilloscope every other frame instead of falling behind
        self.plots, self.photos, self.plot_pos, self.plot_time = {}, {}, {}, {}  # the other graphs' phosphor screens (made when first drawn), their pictures, where they have drawn up to and when
        self.osc_pts = self.spec_pts = self.hist_pts = None  # what the graphs drew last, as canvas coordinates (one (xs, ys) per channel)
        self.mode = 'live'  # live | rec | review | compare
        self.clip = None
        self.cmp = None
        self.sel = None  # (a, b) on the timeline's time axis
        self.rec_markers = []
        self.player = Player()
        self.player.loop = bool(s.get('loop', False))
        self.empty = Clip(np.zeros((BLOCK * 10, 2), np.float32), None, name='(computing)')
        self.view = [0.0, 10.0]
        self.tl_key = None
        self.drag = None
        self.sg_cols = deque(maxlen=2000)
        self.sg_pos = 0
        self.sg_photo = None
        self.theme_i = next((i for i, t in enumerate(THEMES) if t.name == s.get('theme')), 0)
        self.use_theme()
        self.frame = 0
        self.cmp_result = None
        self.live_result = None
        self.view_user = False
        self.cmp_busy = False
        self.findings_on = False  # the findings list replaces the level history
        self.zoom = None  # the scope panel that fills the whole scope area (click a scope), or None
        self.dc_now = [0.0, 0.0]
        self.last_dir = s.get('last_dir') or REC_DIR
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.title('PC Audio Scope')
        try:  # the same picture as the icon of the program file, instead of Tk's feather
            self.icons = [ImageTk.PhotoImage(draw_icon(n)) for n in (256, 64, 32, 16)]
            root.iconphoto(True, *self.icons)
        except Exception:
            self.icons = []
        root.minsize(640, 420)
        w, h = s.get('w'), s.get('h')
        self._rows = None
        self._rz = None
        if w and h and 400 < int(w) <= sw + 50 and 300 < int(h) <= sh + 50:
            x, y = int(s.get('x', 20)), int(s.get('y', 20))
            if not (-200 < x < sw - 200 and -50 < y < sh - 100):
                x, y = 20, 20
            root.geometry('+%d+%d' % (x, y))  # the size follows the content: it grows and shrinks with the timeline
            k = s.get('k')
            self.k = max(0.5, min(2.0, round(float(k) * 20) / 20.0)) if isinstance(k, (int, float)) else self.fit_k(int(w), int(h), True)
        else:
            k = min(1.0, (sh - 140) / float(self.BASE_H + 84 + self.BASE_TH), (sw - 40) / float(self.BASE_W))
            self.k = max(0.5, min(2.0, round(k * 20) / 20.0))
        self.build_ui()
        self.bind_keys()
        src = s.get('source')
        if src:
            cap.set_source(src[0], src[1])
        root.protocol('WM_DELETE_WINDOW', self.quit)
        root.bind('<Configure>', self.on_configure)
        self.fit_window()  # the scope's width and the height of what shows
        self.style_titlebar()
        root.after(300, self.style_titlebar)  # again once the window is on screen
        self.tick()
        self.history_loop()

    # --- settings ---
    def load_settings(self):
        try:
            return json.load(open(SETTINGS))
        except Exception:
            return {}

    def save_settings(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
            self.root.update_idletasks()
            json.dump({'w': self.root.winfo_width(), 'h': self.root.winfo_height(), 'x': self.root.winfo_x(), 'y': self.root.winfo_y(), 'k': self.k,
                       'spec_mode': self.spec_mode, 'theme': self.th.name, 'loop': self.player.loop, 'last_dir': self.last_dir, 'source': list(self.cap.want)}, open(SETTINGS, 'w'))
        except Exception:
            pass

    def use_theme(self):
        th = self.th = THEMES[self.theme_i]
        self.BG, self.GRID, self.TXT, self.CL, self.CR = th.bg, th.grid, th.txt, th.left, th.right
        self.lut = palette(base=th.spec)
        self.root.configure(bg=th.bg)

    def style_titlebar(self):
        """a dark title bar in the colours of the theme instead of the white one (Windows 10 and 11; where the system cannot do it, nothing changes)"""
        if not WINDOWS:
            return
        try:
            from ctypes import wintypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            colorref = lambda h: int(h[5:7], 16) << 16 | int(h[3:5], 16) << 8 | int(h[1:3], 16)  # 0x00BBGGRR

            def put(attr, v):
                val = ctypes.c_int(v)
                return dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4)
            if put(20, 1) != 0:  # use the dark title bar (19 on the first builds that had it)
                put(19, 1)
            put(35, colorref(self.th.bg))  # title bar colour (Windows 11)
            put(36, colorref(self.th.fg))  # title text
            put(34, colorref(self.th.grid))  # window border
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x37)  # redraw the frame
        except Exception:
            pass

    def cycle_theme(self, step=1):
        self.theme_i = (self.theme_i + step) % len(THEMES)
        self.use_theme()
        self.build_ui()
        self.style_titlebar()

    def quit(self):
        self.save_settings()
        self.player.stop()
        self.stop_plots()
        self.root.destroy()

    # --- building the window (everything scales with self.k) ---
    def S(self, v):
        return int(round(v * self.k))

    def F(self, size, fam='Consolas', bold=False):
        return (FONTS.get(fam, fam), max(6, int(round(size * self.k)))) + (('bold',) if bold else ())

    def build_ui(self):
        for w in self.root.winfo_children():
            w.destroy()
        S = self.S
        self.CW, self.CH, self.TH = S(self.BASE_W), S(self.BASE_H), S(self.BASE_TH)
        self.c = tk.Canvas(self.root, width=self.CW, height=self.CH, bg=self.BG, highlightthickness=0)
        self.c.pack()
        self.c.bind('<Double-Button-1>', self.scope_click)  # a single click does nothing: it takes two to enlarge a scope or to go back
        self.c.bind('<Motion>', self.scope_motion)
        self.build_scope()
        self.build_controls()
        self.build_transport()
        self.build_cmp_row()
        self.build_clip_row()
        self.build_timeline()
        self.tl_key = None
        self.hist_key = None
        self.sg_photo = None
        self.stop_plots()
        self._rows = None
        self.set_spec_mode(self.spec_mode)
        if self.mode == 'compare' and self.cmp:
            self.cmp_bounds()
        self.refresh_rows()

    def build_scope(self):
        S, c = self.S, self.c
        base = dict(osc=(10, 44, 610, 320), vec=(625, 44, 901, 320), met=(916, 44, 1230, 320), spec=(10, 352, 610, 630), hist=(625, 352, 1230, 630))
        zoom = self.zoom
        zoomed = dict(osc=(10, 44, 1230, 662), vec=(311, 44, 929, 662), spec=(10, 44, 1230, 630), hist=(10, 44, 1230, 662))
        away = self.CW + S(100)  # panels that are not shown are built this far to the right, out of sight
        hid = lambda n: zoom is not None and n != zoom
        self.P = {}
        for n, r in base.items():
            r = tuple(S(v) for v in (zoomed[n] if n == zoom else r))
            self.P[n] = (r[0] + away, r[1], r[2] + away, r[3]) if hid(n) else r
        for x0, y0, x1, y1 in self.P.values():
            c.create_rectangle(x0, y0, x1, y1, outline=self.GRID)
        # the spectrum and the level history keep their dB numbers in a column at the left of the frame; the graphs start after it, so no trace runs through a number.
        # Both frames end on the lowest dB line, so a silent channel is a line at the same height in both.  self.P then holds the graph itself
        self.gutter = S(46)
        self.panel_frame = {n: self.P[n] for n in ('spec', 'hist')}
        for n, (x0, y0, x1, y1) in self.panel_frame.items():
            self.P[n] = (x0 + self.gutter, y0, x1, y1)
            c.create_line(x0 + self.gutter, y0, x0 + self.gutter, y1, fill=self.GRID, tags=n)

        def t(x, y, s, out=False, **k):
            return c.create_text(S(x) + (away if out else 0), S(y), text=s, fill=k.pop('fill', self.TXT), font=self.F(k.pop('size', 9)), anchor=k.pop('anchor', 'nw'), **k)
        self.status = t(10, 8, '', size=10)
        self.dc_txt = t(985, 28, '', zoom is not None)
        t(10, 28, 'OSCILLOSCOPE   left = %s, right = %s' % (self.th.lname, self.th.rname), hid('osc'))
        t(311 if zoom == 'vec' else 625, 28, 'VECTORSCOPE', hid('vec'))
        t(916, 28, 'LEVELS', zoom is not None)
        self.spec_title = t(10, 28 if zoom == 'spec' else 336, 'SPECTRUM', hid('spec'))
        self.hist_title = t(10 if zoom == 'hist' else 625, 28 if zoom == 'hist' else 336, 'LEVEL HISTORY', hid('hist'))
        # oscilloscope
        x0, y0, x1, y1 = self.P['osc']
        self.osc_item = c.create_image(x0, y0, anchor='nw')  # the graph is a picture (see BeamPlot) with its grid baked in
        # vectorscope: the beam is a picture (see BeamScreen) under the graticule
        x0, y0, x1, y1 = self.P['vec']
        self.vec_item = c.create_image(x0 + 1, y0 + 1, anchor='nw')
        self.vec_lut = beam_palette(self.BG, self.th.vec)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        c.create_line(x0, cy, x1, cy, fill=self.GRID)
        c.create_line(cx, y0, cx, y1, fill=self.GRID)
        c.create_line(x0, y1, x1, y0, fill=self.th.dash, dash=(3, 4))
        c.create_text(x1 - S(4), cy + S(3), text='L', fill=self.CL, font=self.F(9), anchor='ne')
        c.create_text(cx + S(4), y0 + S(3), text='R', fill=self.CR, font=self.F(9), anchor='nw')
        # meters (absolute positions; out of sight while a scope fills the area)
        x0, y0, x1, y1 = self.P['met']
        mx = away if zoom is not None else 0
        self.bal_x = S(1073) + mx
        self.bar_h = S(90)
        self.bar_top = y0 + S(20)
        self.bar_xs = (S(993) + mx, S(1103) + mx)  # the two level bars are centred on the balance bar (S(1073)), with the dB scale between them
        self.met_item = c.create_image(x0 + 1, y0 + 1, anchor='nw')  # the bars are a picture (see beam_plot): glowing, like the graphs
        self.met_geom = None
        nfont = tkfont.Font(root=self.root, font=self.F(8))
        wm, w2 = nfont.measure('-'), nfont.measure('48')
        col_x = self.bal_x - (wm + w2) / 2.0 + wm  # the first digit of every number of the dB scale starts here (the 0, the 6 of -6, the 1 of -12 ...), the minus signs hang to its left
        for dd in (0, -6, -12, -24, -48):  # each number sits on its line, which runs out to the bars on both sides of it
            yy = y0 + S(20) + (-dd) / 60.0 * self.bar_h
            col = self.th.peak if dd == 0 else self.GRID
            digits = str(abs(dd))
            c.create_line(self.bar_xs[0] + S(54), yy, col_x - S(3) - (wm if dd < 0 else 0), yy, fill=col)  # the 0 has no minus sign, so its line runs on to the digit
            c.create_line(col_x + nfont.measure(digits) + S(3), yy, self.bar_xs[1] - S(4), yy, fill=col)
            c.create_text(col_x, yy, text=digits, fill=(self.th.peak if dd == 0 else self.TXT), font=self.F(8), anchor='w')
            if dd < 0:
                c.create_text(col_x, yy, text='-', fill=self.TXT, font=self.F(8), anchor='e')
        # the text is one block at the bottom of the panel, the balance figure its last line; the balance bar hangs on the level of the vectorscope's centre line, between the level bars and the text
        lh = tkfont.Font(root=self.root, font=self.F(9)).metrics('linespace')
        txt_top = y1 - S(8) - 5 * lh - S(4)
        self.m_txt = c.create_text(S(924) + mx, txt_top, text='', fill=self.TXT, font=self.F(9), anchor='nw')
        self.bal_y = int(round((y0 + y1) / 2.0))  # level of the vectorscope's centre line (it has the same top and bottom as this panel)
        self.bal_lbl = c.create_text(S(924) + mx, txt_top + 4 * lh + S(4), text='', fill=self.TXT, font=self.F(9), anchor='nw')
        # spectrum (tag 'spec') and spectrogram (tag 'sg')
        x0, y0, x1, y1 = self.P['spec']
        sfont = tkfont.Font(root=self.root, font=self.F(8))
        for i, (lo, hi, names, rng) in enumerate(EQ_BANDS):  # the ranges an equaliser uses: tinted bands through the graph, their names under it
            a, b_ = self.fx(max(lo, 30)), self.fx(hi)
            if lo > 30:  # the bands and their dividers inside the graph are in its picture; the dividers go on under it, between the names
                c.create_line(a, y1, a, y1 + S(30), fill=self.GRID, tags='spec')
            name = next((n for n in names if sfont.measure(n) <= b_ - a - S(4)), names[-1])
            c.create_text((a + b_) / 2, y1 + S(4), text=name, fill=self.th.fg, font=self.F(8), anchor='n', tags='spec')
            c.create_text((a + b_) / 2, y1 + S(17), text=rng, fill=self.TXT, font=self.F(8), anchor='n', tags='spec')
        for dd in DB_LINES:
            yy = y0 + (-dd) / DB_RANGE * (y1 - y0)
            c.create_text(x0 - S(5), yy + S(1) if dd == 0 else yy, text='%d dB' % dd, fill=(self.th.peak if dd == 0 else self.TXT), font=self.F(8), anchor='ne' if dd == 0 else 'e', tags='spec')
        self.spec_item = c.create_image(x0, y0, anchor='nw', tags='spec')
        self.sg_item = c.create_image(x0 + 1, y0 + 1, anchor='nw', tags='sg')
        self.sg_head = c.create_line(-10, y0, -10, y1, fill='white', tags='sg')
        for f in (100, 1000, 10000):
            yy = y0 + (1.0 - (math.log10(f) - math.log10(30)) / (math.log10(20000) - math.log10(30))) * (y1 - y0)
            c.create_text(x0 - S(5), yy, text='%g Hz' % f if f < 1000 else '%g kHz' % (f / 1000), fill=self.TXT, font=self.F(8), anchor='e', tags='sg')
        # history / compare report
        x0, y0, x1, y1 = self.P['hist']
        for dd in DB_LINES:
            yy = y0 + (-dd) / DB_RANGE * (y1 - y0)
            c.create_text(x0 - S(5), yy + S(1) if dd == 0 else yy, text='%d dB' % dd, fill=(self.th.peak if dd == 0 else self.TXT), font=self.F(8), anchor='ne' if dd == 0 else 'e', tags='hist')
        self.hist_item = c.create_image(x0, y0, anchor='nw', tags='hist')
        self.cmp_txt = c.create_text(self.panel_frame['hist'][0] + S(10), y0 + S(8), text='', fill=self.th.fg, font=self.F(10), anchor='nw', tags='cmp')

    def scope_hit(self, x, y):
        """the scope panel under the mouse (the levels cannot be enlarged), or None"""
        for n in ('osc', 'vec', 'spec', 'hist'):
            x0, y0, x1, y1 = self.panel_frame.get(n) or self.P[n]
            if n == 'spec':
                y1 += self.S(32)  # the names of the equaliser ranges under the graph belong to it
            if x0 <= x <= x1 and y0 <= y <= y1:
                return n
        return None

    def scope_click(self, e):
        if self.zoom:
            self.zoom_panel(None)
            return
        n = self.scope_hit(e.x, e.y)
        if n:
            self.zoom_panel(n)

    def scope_motion(self, e):
        self.c.config(cursor='hand2' if (self.zoom or self.scope_hit(e.x, e.y)) else '')

    def zoom_panel(self, name):
        """name fills the whole scope area; None shows all the panels again"""
        self.zoom = name
        self.c.delete('all')
        self.build_scope()
        self.hist_key = None
        self.sg_photo = None
        self.stop_plots()
        self.set_spec_mode(self.spec_mode)
        self.draw()

    def build_controls(self):
        f = tk.Frame(self.root, bg=self.th.panel)
        f.pack(fill='x')
        st = dict(bg=self.th.btn, fg=self.th.fg, activebackground=self.th.btn_hi, activeforeground='white', relief='flat', bd=0, padx=self.S(9), pady=self.S(3), takefocus=0, font=self.F(9, 'Segoe UI', True))
        lab = dict(bg=self.th.panel, fg=self.TXT, font=self.F(9, 'Segoe UI'))

        def mk(text, cmd):
            b = Button(f, text=text, command=cmd, **st)
            b.pack(side='left', padx=(self.S(6), 0), pady=self.S(3))
            return b
        tk.Label(f, text='Input', **lab).pack(side='left', padx=(self.S(8), 0))
        if FLAT_BUTTONS:
            self.mb_src = FlatButton(f, text='...', command=self.pop_src_menu, **st)
        else:
            self.mb_src = tk.Menubutton(f, text='...', direction='below', indicatoron=1, **st)
        self.mb_src.pack(side='left', padx=(self.S(6), 0), pady=self.S(3))
        self.src_menu = tk.Menu(self.mb_src, tearoff=0, bg=self.th.btn, fg=self.th.fg, activebackground=self.th.btn_hi, activeforeground='white', font=self.F(9, 'Segoe UI'), postcommand=self.fill_src_menu)
        if not FLAT_BUTTONS:
            self.mb_src.config(menu=self.src_menu)
        self.b_spec = mk('Spectrogram  (G)', lambda: self.set_spec_mode('spectrogram' if self.spec_mode == 'spectrum' else 'spectrum'))
        mk('Theme  (T)', self.cycle_theme)
        self.b_reset = mk('Reset peaks  (R)', self.reset_peaks)
        self.controls = f

    def pop_src_menu(self):
        self.fill_src_menu()
        b = self.mb_src
        self.src_menu.tk_popup(b.winfo_rootx(), b.winfo_rooty() + b.winfo_height())

    def fill_src_menu(self):
        self.cap.refresh_req = True  # the list is refreshed in the background for the next time
        m = self.src_menu
        m.delete(0, 'end')
        cur = self.cap.now
        for d in self.cap.devices:
            on = cur is not None and cur == (d['kind'], d['id'])
            m.add_command(label=(chr(9679) + ' ' if on else '    ') + d['label'], command=lambda d=d: self.pick_source(d))

    def pick_source(self, d):
        if self.mode == 'rec' or (self.mode == 'compare' and self.cmp and self.cmp.get('live')):
            self.msg('stop the recording / live comparison before changing the input')
            return
        self.cap.set_source(d['kind'], d['id'])
        self.reset_peaks()
        self.msg('input: ' + d['label'])

    def update_source_button(self):
        lab = self.cap.device or '?'
        txt = lab if len(lab) <= 36 else lab[:35] + '...'
        if self.mb_src.cget('text') != txt:
            self.mb_src.config(text=txt)

    def reset_peaks(self):
        self.cap.reset()
        self.hold[:] = [FLOOR, FLOOR]

    def build_clip_row(self):
        f = tk.Frame(self.root, bg=self.th.panel)
        self.clip_row = f
        st = dict(bg=self.th.btn, fg=self.th.fg, activebackground=self.th.btn_hi, activeforeground='white', relief='flat', bd=0, padx=self.S(9), pady=self.S(3), takefocus=0, font=self.F(9, 'Segoe UI', True))
        lab = dict(bg=self.th.panel, fg=self.TXT, font=self.F(9, 'Segoe UI'))

        def mk(text, cmd):
            b = Button(f, text=text, command=cmd, **st)
            b.pack(side='left', padx=(self.S(6), 0), pady=self.S(3))
        tk.Label(f, text='Markers', **lab).pack(side='left', padx=(self.S(8), 0))
        mk('Add marker  (M)', self.marker_add)
        mk('\u25c0 Previous  (PgUp)', lambda: self.marker_jump(-1))
        mk('Next \u25b6  (PgDn)', lambda: self.marker_jump(1))
        mk('Delete nearest  (Del)', self.marker_delete)
        tk.Label(f, text='     Selection', **lab).pack(side='left')
        mk('Start here  (I)', lambda: self.sel_point(0))
        mk('End here  (O)', lambda: self.sel_point(1))
        mk('Clear  (X)', self.sel_clear)
        tk.Label(f, text='   ', **lab).pack(side='left')
        mk('Find problems  (F)', self.find_problems_key)

    def refresh_rows(self):
        """the compare and clip rows and the timeline under them only show when there is something for them: the timeline from the moment a recording starts, a clip is opened or two are compared"""
        state = (self.mode in ('review', 'compare'), self.mode == 'compare', self.mode != 'live')
        if state == self._rows:
            return
        first = self._rows is None
        self._rows = state
        for w in (self.cmp_row, self.clip_row, self.tl):
            w.pack_forget()
        if state[1]:
            self.cmp_row.pack(fill='x')
        if state[0]:
            self.clip_row.pack(fill='x')
        if state[2]:
            self.tl.pack()
        if not first:
            self.root.after(30, self.fit_window)  # the window grows or shrinks with them

    def fit_window(self):
        """make the window as tall as its content now is"""
        try:
            if self.root.state() != 'normal':
                return
            self.root.update_idletasks()
            w = self.root.winfo_width()  # the width stays what it is (the scope's own width before the window is on screen): a long message in a row must not widen the window
            self.root.geometry('%dx%d' % (w if w > 200 else self.CW, self.root.winfo_reqheight()))
        except tk.TclError:
            pass

    def build_transport(self):
        f = tk.Frame(self.root, bg=self.BG)
        f.pack(fill='x')
        st = dict(bg=self.th.btn, fg=self.th.fg, activebackground=self.th.btn_hi, activeforeground='white', relief='flat', bd=0, padx=self.S(12), pady=self.S(5), takefocus=0, font=self.F(10, 'Segoe UI', True))
        mk = lambda text, cmd: Button(f, text=text, command=cmd, **st)
        self.b_rec = mk('● REC', self.rec_toggle)
        self.b_play = mk('▶ PLAY', self.play_toggle)
        self.b_loop = mk('⟲ LOOP', self.loop_toggle)
        for b in (self.b_rec, self.b_play, mk('|◀ Start', lambda: self.seek_t(self.axis_start())), self.b_loop, mk('LIVE', self.go_live), mk('Open…', self.open_clip),
                  mk('Export…', self.export), mk('Compare…', self.compare_open), mk('Compare to live…', self.compare_live_open)):
            b.pack(side='left', padx=(self.S(8), 0), pady=self.S(5))
        self.lbl_time = tk.Label(f, text='', bg=self.BG, fg=self.th.fg, font=self.F(13, 'Consolas', True), width=18)
        self.lbl_time.pack(side='left', padx=self.S(10))
        self.lbl_msg = tk.Label(f, text='', bg=self.BG, fg=self.th.dim, font=self.F(9, 'Segoe UI'), anchor='w')
        self.lbl_msg.pack(side='left', padx=self.S(10), fill='x', expand=True)
        self.transport = f

    def build_cmp_row(self):
        f = tk.Frame(self.root, bg=self.th.panel)
        self.cmp_row = f
        st = dict(bg=self.th.btn, fg=self.th.fg, activebackground=self.th.btn_hi, activeforeground='white', relief='flat', bd=0, padx=self.S(4), pady=self.S(3), takefocus=0, font=self.F(8, 'Segoe UI', True))
        lab = dict(bg=self.th.panel, fg=self.TXT, font=self.F(8, 'Segoe UI'))
        self.v_move = tk.StringVar(value='B')
        self.v_active = tk.StringVar(value='A')
        tk.Label(f, text='COMPARE', bg=self.th.panel, fg=self.th.live, font=self.F(9, 'Segoe UI', True)).pack(side='left', padx=self.S(8))
        tk.Label(f, text='A at', **lab).pack(side='left')
        self.e_sa = tk.Entry(f, width=8, bg=self.th.btn, fg=self.th.fg, insertbackground='white', relief='flat', font=self.F(10, 'Consolas'))
        self.e_sa.pack(side='left', padx=self.S(3))
        tk.Label(f, text='B at', **lab).pack(side='left', padx=(self.S(4), 0))
        self.e_sb = tk.Entry(f, width=8, bg=self.th.btn, fg=self.th.fg, insertbackground='white', relief='flat', font=self.F(10, 'Consolas'))
        self.e_sb.pack(side='left', padx=self.S(3))
        tk.Label(f, text='s', **lab).pack(side='left')
        for e, w in ((self.e_sa, 'A'), (self.e_sb, 'B')):
            e.bind('<Return>', lambda ev, w=w: (self.set_start_from_entry(w), self.root.focus_set()))
        tk.Label(f, text=' move', **lab).pack(side='left')
        for v in ('A', 'B'):
            tk.Radiobutton(f, text=v, variable=self.v_move, value=v, bg=self.th.panel, fg=self.th.fg, selectcolor=self.th.sel, activebackground=self.th.panel, takefocus=0, font=self.F(8, 'Segoe UI', True)).pack(side='left')
        for label, d in self.NUDGES:
            Button(f, text=label, command=lambda d=d: self.nudge(d), **st).pack(side='left', padx=(self.S(1), 0))
        for text, cmd in (('Auto-align', self.cmp_auto), ('Align markers', self.cmp_align_markers), ('Reset', self.cmp_reset), ('Close', self.cmp_close)):
            b = Button(f, text=text, command=cmd, **st)
            b.pack(side='left', padx=(self.S(5), 0))
            if text == 'Close':
                self.b_cclose = b
        tk.Label(f, text=' listen', **lab).pack(side='left')
        for v, label in (('A', 'A'), ('B', 'B'), ('D', 'Δ difference')):
            tk.Radiobutton(f, text=label, variable=self.v_active, value=v, command=self.cmp_activate, bg=self.th.panel, fg=self.th.fg, selectcolor=self.th.sel, activebackground=self.th.panel, takefocus=0,
                           font=self.F(8, 'Segoe UI', True)).pack(side='left')

    def build_timeline(self):
        S = self.S
        self.tl = tk.Canvas(self.root, width=self.CW, height=self.TH, bg=self.th.tl_bg, highlightthickness=0)  # packed by refresh_rows when there is something to show
        self.L0, self.L1 = S(40), self.CW - S(12)
        self.tl.bind('<ButtonPress-1>', self.tl_press)
        self.tl.bind('<B1-Motion>', self.tl_drag)
        self.tl.bind('<ButtonRelease-1>', self.tl_release)
        self.tl.bind('<Shift-ButtonPress-1>', self.tl_sel_press)
        self.tl.bind('<Shift-B1-Motion>', self.tl_sel_drag)
        self.tl.bind('<MouseWheel>', self.tl_wheel)
        self.tl.bind('<ButtonPress-3>', self.tl_pan_start)
        self.tl.bind('<B3-Motion>', self.tl_pan)
        if MACOS:  # the right button is button 2 there
            self.tl.bind('<ButtonPress-2>', self.tl_pan_start)
            self.tl.bind('<B2-Motion>', self.tl_pan)
        self.tl.bind('<Double-Button-1>', self.tl_full)

    def bind_keys(self):
        r = self.root

        def kb(seq, fn, always=False):
            def h(e):
                if not always:
                    try:
                        if isinstance(r.focus_get(), tk.Entry):
                            return
                    except Exception:
                        pass
                fn()
            r.bind(seq, h)
        kb('<space>', lambda: self.play_toggle() if self.mode in ('review', 'compare') else setattr(self, 'paused', not self.paused))
        kb('<F5>', self.rec_toggle, True)
        kb('c', lambda: setattr(self, 'comp', not self.comp))
        kb('r', self.reset_peaks)
        kb('l', self.go_live)
        kb('<Control-o>', self.open_clip, True)
        if MACOS:
            kb('<Command-o>', self.open_clip, True)
        kb('g', lambda: self.set_spec_mode('spectrogram' if self.spec_mode == 'spectrum' else 'spectrum'))
        kb('t', self.cycle_theme)
        kb('u', lambda: setattr(self.cap, 'undo_eq', not self.cap.undo_eq))
        kb('f', self.find_problems_key)
        kb('m', self.marker_add)
        kb('<Delete>', self.marker_delete)
        kb('<Prior>', lambda: self.marker_jump(-1))
        kb('<Next>', lambda: self.marker_jump(1))
        kb('i', lambda: self.sel_point(0))
        kb('o', lambda: self.sel_point(1))
        kb('x', self.sel_clear)
        kb('p', self.loop_toggle)
        kb('e', self.export)
        kb('1', lambda: self.cmp_listen('A'))
        kb('2', lambda: self.cmp_listen('B'))
        kb('3', lambda: self.cmp_listen('D'))
        kb('<Left>', lambda: self.seek_rel(-1))
        kb('<Right>', lambda: self.seek_rel(1))
        kb('<Shift-Left>', lambda: self.seek_rel(-5))
        kb('<Shift-Right>', lambda: self.seek_rel(5))
        kb('<Alt-Left>', lambda: self.nudge(-0.01))
        kb('<Alt-Right>', lambda: self.nudge(0.01))
        kb('<Alt-Shift-Left>', lambda: self.nudge(-0.001))
        kb('<Alt-Shift-Right>', lambda: self.nudge(0.001))
        kb('<Alt-Control-Left>', lambda: self.nudge(-0.1))
        kb('<Alt-Control-Right>', lambda: self.nudge(0.1))
        kb('<Home>', lambda: self.seek_t(self.axis_start()))
        kb('<End>', lambda: self.seek_t(self.axis_end()))
        kb('q', self.quit)
        kb('<Escape>', self.quit, True)

    def rows_base(self):
        """height of the button rows that are showing, at scale 1"""
        try:
            hs = [self.controls.winfo_reqheight(), self.transport.winfo_reqheight()]
            if self._rows and self._rows[1]:
                hs.append(self.cmp_row.winfo_reqheight())
            if self._rows and self._rows[0]:
                hs.append(self.clip_row.winfo_reqheight())
            return sum(hs) / float(self.k)
        except Exception:
            return 84.0

    def fit_k(self, w, h, with_timeline=None):
        """the scale at which the whole window content fits a window of w x h pixels (with the timeline, or without it while it is collapsed)"""
        if with_timeline is None:
            with_timeline = bool(self._rows and self._rows[2])
        k = min(w / float(self.BASE_W), h / float(self.BASE_H + (self.BASE_TH if with_timeline else 0) + self.rows_base()))
        return max(0.5, min(2.0, round(k * 20) / 20.0))

    def on_configure(self, e):
        if e.widget is not self.root:
            return
        if self._rz is not None:
            self.root.after_cancel(self._rz)
        self._rz = self.root.after(250, self.apply_resize)

    def apply_resize(self):
        self._rz = None
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if w < 300 or h < 200:
            return
        k = self.fit_k(w, h)
        if abs(k - self.k) >= 0.05:
            self.k = k
            self.build_ui()

    def msg(self, s):
        self.lbl_msg.config(text=s)

    def set_spec_mode(self, mode):
        self.spec_mode = mode
        self.c.itemconfig('spec', state=('normal' if mode == 'spectrum' else 'hidden'))
        self.c.itemconfig('sg', state=('normal' if mode == 'spectrogram' else 'hidden'))
        self.c.itemconfig(self.spec_title, text=('SPECTRUM' if mode == 'spectrum' else 'SPECTROGRAM  (frequency up, time across; white line = playhead)'))

    # --- clip / mode helpers ---
    def vol_now(self):
        v = self.cap.vol
        return v[0] if (v and not v[2]) else None

    def active_clip(self):
        """the clip whose samples the scopes and the player use (None when the live sound is shown)"""
        if self.mode == 'review':
            return self.clip
        if self.mode == 'compare' and self.cmp:
            if self.cmp.get('live'):
                return self.cmp['A'] if self.cmp['active'] == 'A' else None
            return self.cmp.get({'A': 'vA', 'B': 'vB', 'D': 'vD'}[self.cmp['active']]) or self.empty
        return None

    def origin(self):
        return self.cmp['origin'] if (self.mode == 'compare' and self.cmp) else 0.0

    def axis_start(self):
        return self.origin()

    def axis_end(self):
        if self.mode == 'compare' and self.cmp:
            return self.cmp['end']
        return self.clip.duration if self.clip else 0.0

    def head_t(self):
        """playhead on the timeline's axis (in a live comparison: the running point, where the live sound is now)"""
        if self.mode == 'compare' and self.cmp and self.cmp.get('live'):
            return self.cmp['sb'] + self.cap.rec_frames / SR
        return self.origin() + self.player.pos / SR

    def seek_t(self, t):
        if self.mode == 'compare' and self.cmp and self.cmp.get('live'):
            self.cmp['sb'] = round(t - self.cap.rec_frames / SR, 3)  # move the running point of the recorded clip
            self.cmp_bounds()
            self.cmp_dirty()
            self.tl_key = None
            return
        if self.mode not in ('review', 'compare'):
            return
        c = self.active_clip()
        n = len(c.data) if c is not None else 0
        self.player.pos = int(max(0, min(n, round((t - self.origin()) * SR))))

    def seek_rel(self, dt):
        if self.mode in ('review', 'compare'):
            self.seek_t(self.head_t() + dt)

    def clip_time_ref(self):
        return self.clip if self.mode == 'review' else (self.cmp['A'] if self.cmp else None)

    # --- recorder / player / files ---
    def leave_compare(self):
        c = self.cmp
        if c and c.get('live'):
            self.cap.stop_rec()
        self.cmp = None

    def rec_toggle(self):
        if self.mode == 'rec':
            data, vol = self.cap.stop_rec()
            marks = list(self.rec_markers)
            if data is None or len(data) < SR // 5:
                self.mode = 'live'
                self.msg('recording too short, discarded')
                return
            clip = Clip(data, vol, markers=marks)
            os.makedirs(REC_DIR, exist_ok=True)
            path = os.path.join(REC_DIR, time.strftime('clip_%Y%m%d_%H%M%S.wav'))
            clip.save(path)
            self.msg('saved ' + (os.path.relpath(path, HERE) if path.startswith(HERE) else path))
            self.open_loaded(clip)
        else:
            if self.mode == 'compare' and self.cmp and self.cmp.get('live'):
                self.msg('stop the live comparison first (Stop live)')
                return
            self.player.stop()
            self.leave_compare()
            self.cap.start_rec()
            self.mode = 'rec'
            self.clip = None
            self.sel = None
            self.rec_markers = []
            self.tl_key = None
            self.msg('recording ... F5 or REC again to stop; M drops a marker')

    def open_loaded(self, clip):
        self.leave_compare()
        self.clip = clip
        self.findings_on = False
        self.sel = clip.sel
        self.player.load(clip)
        self.player.region = None
        self.mode = 'review'
        self.view = [0.0, max(0.5, clip.duration)]
        self.tl_key = None
        self.sync_player_region()

    def open_clip(self):
        os.makedirs(REC_DIR, exist_ok=True)
        p = filedialog.askopenfilename(initialdir=self.last_dir, filetypes=[('wav files', '*.wav')], title='Open a recording')
        if p:
            self.last_dir = os.path.dirname(p)
            try:
                self.open_loaded(Clip.load(p))
                self.msg('opened ' + os.path.basename(p))
            except Exception as e:
                self.msg('cannot open: %s' % e)

    def go_live(self):
        if self.mode == 'rec':
            self.rec_toggle()
        self.player.stop()
        self.mode = 'live'
        self.leave_compare()
        self.tl_key = None

    def play_toggle(self):
        c = self.active_clip()
        if self.mode not in ('review', 'compare') or c is None:
            return
        if self.player.playing:
            self.player.pause()
        else:
            self.player.clip = c
            self.sync_player_region()
            self.player.play(self.vol_now())
            if self.player.error:
                self.msg(self.player.error)

    def loop_toggle(self):
        self.player.loop = not self.player.loop
        self.sync_player_region()
        self.msg('loop %s%s' % ('on' if self.player.loop else 'off', ' (the A-B selection)' if (self.player.loop and self.sel) else (' (the whole clip: set A-B with I and O to loop a part)' if self.player.loop else '')))

    def sync_player_region(self):
        if self.sel and self.mode in ('review', 'compare'):
            a, b = self.sel
            o = self.origin()
            self.player.region = (int(max(0, (a - o) * SR)), int(max(0, (b - o) * SR)))
        else:
            self.player.region = None

    def export(self):
        c = self.active_clip()
        if self.mode not in ('review', 'compare') or c is None:
            self.msg('open or record a clip first')
            return
        o = self.origin()
        if self.sel:
            t0, t1 = self.sel
            part = c.slice(t0 - o, t1 - o)
            tag = '_%s-%s' % (fmt_time(t0, True).replace(':', 'm'), fmt_time(t1, True).replace(':', 'm'))
        else:
            part, tag = Clip(c.data, c.vol_db, name=c.name), ''
        base = os.path.splitext(os.path.basename(c.path or 'clip'))[0] + ('_' + self.cmp['active'] if (self.mode == 'compare') else '') + tag
        p = filedialog.asksaveasfilename(initialdir=self.last_dir, initialfile=base + '.wav', defaultextension='.wav', filetypes=[('wav files', '*.wav')], title='Export')
        if p:
            self.last_dir = os.path.dirname(p)
            part.save(p)
            self.msg('exported %.2f s to %s' % (part.duration, os.path.basename(p)))

    # --- markers and selection ---
    def find_problems_key(self):
        c = self.clip
        if self.mode != 'review' or c is None:
            self.msg('open or record a clip first, then press F to look for problems in it')
            return
        if c.findings is None:
            self.msg('looking for problems in %s ...' % c.name)
            self.root.update_idletasks()
            self.scan_clip(c)
            self.findings_on = True
        else:
            self.findings_on = not self.findings_on
        self.hist_key = None

    def scan_clip(self, c):
        """look for problems in each channel of the clip, put markers (they start with !) on the timeline, and save a report and a picture next to a saved clip"""
        c.findings = find_problems(c.data, c.vol_db)
        c.markers = [q for q in c.markers if not str(q.get('name', '')).startswith('!')]
        for q in sorted(c.findings, key=lambda q: -q['severity'])[:30]:
            if q['severity'] >= 2:
                c.markers.append({'t': q['t'], 'name': marker_name(q)})
        c.markers.sort(key=lambda q: q['t'])
        c.save_meta()
        self.tl_key = None
        saved = ''
        if c.path:
            try:
                base = os.path.splitext(c.path)[0] + '.analysis'
                open(base + '.txt', 'w', encoding='utf-8').write(chr(10).join(format_findings(c.findings) or ['no problems found']) + chr(10))
                json.dump(dict(file=os.path.basename(c.path), duration=c.duration, vol_db=c.vol_db, findings=c.findings), open(base + '.json', 'w'), indent=1)
                findings_image(c.data, c.vol_db, c.findings, c.name, left=self.th.left, right=self.th.right).save(base + '.png')
                saved = '; report and picture saved next to the clip (.analysis.txt, .json, .png)'
            except Exception:
                pass
        n = len(c.findings)
        self.msg(('%d finding%s%s' % (n, '' if n == 1 else 's', saved)) if n else 'no problems found%s' % saved)

    def findings_text(self):
        c = self.clip
        n = len(c.findings)
        return chr(10).join(['%s: %d finding%s' % (c.name, n, '' if n == 1 else 's'), ''] + (format_findings(c.findings, 14) or ['no problems found']))

    def marker_add(self):
        if self.mode == 'rec':
            self.rec_markers.append({'t': self.cap.rec_frames / SR, 'name': 'M%d' % (len(self.rec_markers) + 1)})
            self.tl_key = None
            return
        if self.mode == 'review' and self.clip is not None:
            ref, t = self.clip, self.head_t()
        elif self.mode == 'compare' and self.cmp:
            which = self.v_move.get()
            ref = self.cmp[which]
            t = self.head_t() - self.cmp['s' + which.lower()]
            if t < 0 or t > ref.duration:
                self.msg('the playhead is outside clip %s' % which)
                return
        else:
            return
        ref.markers.append({'t': round(float(t), 4), 'name': 'M%d' % (len(ref.markers) + 1)})
        ref.markers.sort(key=lambda m: m['t'])
        ref.save_meta()
        self.tl_key = None
        self.msg('marker at %s' % fmt_time(t, True))

    def markers_view(self):
        """[(time on the timeline axis, name, colour)]"""
        if self.mode == 'rec':
            return [(m['t'], m['name'], self.th.mark_a) for m in self.rec_markers]
        if self.mode == 'review' and self.clip is not None:
            return [(m['t'], m['name'], self.th.mark_a) for m in self.clip.markers]
        if self.mode == 'compare' and self.cmp:
            c = self.cmp
            return ([(c['sa'] + m['t'], 'A' + m['name'], self.th.mark_a) for m in c['A'].markers] + [(c['sb'] + m['t'], 'B' + m['name'], self.th.mark_b) for m in c['B'].markers])
        return []

    def marker_delete(self):
        if self.mode == 'review' and self.clip and self.clip.markers:
            t = self.head_t()
            m = min(self.clip.markers, key=lambda m: abs(m['t'] - t))
            self.clip.markers.remove(m)
            self.clip.save_meta()
            self.tl_key = None
        elif self.mode == 'compare' and self.cmp:
            which = self.v_move.get()
            ref = self.cmp[which]
            if ref.markers:
                t = self.head_t() - self.cmp['s' + which.lower()]
                ref.markers.remove(min(ref.markers, key=lambda m: abs(m['t'] - t)))
                ref.save_meta()
                self.tl_key = None

    def marker_jump(self, d):
        ms = sorted(m[0] for m in self.markers_view())
        if not ms or self.mode not in ('review', 'compare'):
            return
        t = self.head_t()
        cand = [m for m in ms if (m > t + 0.01 if d > 0 else m < t - 0.01)]
        if cand:
            self.seek_t(min(cand) if d > 0 else max(cand))

    def sel_point(self, which):
        if self.mode not in ('review', 'compare'):
            return
        t = self.head_t()
        a, b = self.sel if self.sel else (t, t)
        if which == 0:
            a = t
            b = max(b, a + 0.01)
        else:
            b = t
            a = min(a, b - 0.01)
        self.set_sel(a, b)

    def set_sel(self, a, b):
        a, b = min(a, b), max(a, b)
        self.sel = (a, b) if b - a > 0.005 else None
        ref = self.clip_time_ref()
        if ref is not None and self.mode == 'review':
            ref.sel = self.sel
            ref.save_meta()
        self.sync_player_region()
        self.tl_key = None
        if self.sel:
            self.msg(self.sel_stats_text())

    def sel_clear(self):
        self.sel = None
        ref = self.clip_time_ref()
        if ref is not None and self.mode == 'review':
            ref.sel = None
            ref.save_meta()
        self.sync_player_region()
        self.tl_key = None

    def sel_stats_text(self):
        c = self.active_clip()
        if not (self.sel and c is not None):
            return ''
        o = self.origin()
        a, b = self.sel
        i0, i1 = max(0, int((a - o) * 100)), min(len(c.peaks), int((b - o) * 100))
        if i1 <= i0:
            return ''
        cd = (-c.vol_db) if (self.comp and c.vol_db is not None) else 0.0
        pk = db(float(c.peaks[i0:i1].max())) + cd
        li = integrated(c.ms[i0:i1], cd)
        return 'A %s  B %s  (%.2f s)   peak %.1f dBFS   loudness %s LUFS' % (fmt_time(a, True), fmt_time(b, True), b - a, pk, ('%.1f' % li) if li is not None else '--')

    # --- comparing two clips ---
    def compare_open(self):
        if self.mode == 'compare' and self.cmp:
            A = self.cmp['A']
        elif self.mode == 'review' and self.clip is not None:
            A = self.clip
        else:
            self.msg('record or open a clip first (that becomes A), then press Compare...')
            return
        p = filedialog.askopenfilename(initialdir=self.last_dir, filetypes=[('wav files', '*.wav')], title='Open the clip to compare with (B)')
        if not p:
            return
        self.last_dir = os.path.dirname(p)
        try:
            B = Clip.load(p)
        except Exception as e:
            self.msg('cannot open: %s' % e)
            return
        self.compare_start(A, B)

    def compare_start(self, A, B, auto=True):
        self.player.stop()
        self.cmp = dict(A=A, B=B, sa=0.0, sb=0.0, origin=0.0, end=max(A.duration, B.duration), vA=None, vB=None, vD=None, stats=None, token=0, dirty=None, score=None, active='A', dpk=1.0)
        self.mode = 'compare'
        self.clip = None
        self.sel = None
        self.v_move.set('B')
        self.v_active.set('A')
        if auto:
            lag, score = auto_align(A.data, B.data, A.vol_db, B.vol_db)
            self.cmp['sb'] = -lag
            self.cmp['score'] = score
            self.msg('auto-aligned on the loudest part of A: B starts %+.3f s (match %.2f).  Adjust it if needed: drag a lane, type a start, nudge, or align markers' % (-lag, score))
        self.cmp_bounds()
        self.view = [self.cmp['origin'], max(self.cmp['end'], self.cmp['origin'] + 0.5)]
        self.cmp_dirty()
        self.tl_key = None

    def compare_live_open(self):
        if self.mode == 'review' and self.clip is not None:
            A = self.clip
        elif self.mode == 'compare' and self.cmp:
            A = self.cmp['A']
        else:
            p = filedialog.askopenfilename(initialdir=self.last_dir, filetypes=[('wav files', '*.wav')], title='Open the recorded clip to compare the live sound with')
            if not p:
                return
            self.last_dir = os.path.dirname(p)
            try:
                A = Clip.load(p)
            except Exception as e:
                self.msg('cannot open: %s' % e)
                return
        self.compare_live_start(A)

    def compare_live_start(self, A):
        if self.mode == 'rec':
            self.rec_toggle()
        self.player.stop()
        if self.cmp and self.cmp.get('live'):
            self.cap.stop_rec()
        self.cap.reset()
        self.cap.start_rec()
        self.cmp = dict(A=A, B=LiveClip(self.cap), sa=0.0, sb=0.0, origin=0.0, end=A.duration, live=True, vA=None, vB=None, vD=None, stats=None, token=0, dirty=None, score=None,
                        active='B', dpk=1.0, acc=self.new_acc(A), last_live=0.0, auto_pending=True)
        self.mode = 'compare'
        self.clip = None
        self.sel = None
        self.view_user = False
        self.v_move.set('B')
        self.v_active.set('B')
        self.cmp_bounds()
        self.view = [0.0, max(A.duration, 0.5)]
        self.tl_key = None
        self.msg('live comparison: play the same sound now.  Auto-align fires once after about 6 s of sound; click the timeline to move the running point, or press Auto-align again')

    def new_acc(self, A):
        n = int(math.ceil(A.duration / 0.5)) + 3
        return {k: np.full(n, np.nan) for k in ('sim', 'resid', 'lvl', 'lag')}

    def live_stats_dict(self):
        c = self.cmp
        acc = c['acc']
        n = len(acc['sim'])
        ex = c.get('live_extra') or {}
        return dict(win_t=np.arange(n) * 0.5, t_ref=c['sa'], sim=acc['sim'].copy(), resid=acc['resid'].copy(), lvl=acc['lvl'].copy(), lag=acc['lag'].copy(), hop_s=0.5,
                    level_db=ex.get('level_db', 0.0), null_db=ex.get('null_db', 0.0))

    def live_worker(self, token, A, sa, sb, tail, tau0, vol):
        try:
            if len(tail) < SR:
                return
            t_tail0 = sb + tau0  # where the start of the tail is on the timeline
            t0 = max(sa, t_tail0)
            t1 = min(sa + A.duration, t_tail0 + len(tail) / SR)
            if t1 - t0 < 1.5:
                self.live_result = (token, [], None)
                return
            ia = int(round((t0 - sa) * SR))
            ib = int(round((t0 - t_tail0) * SR))
            n = min(int(round((t1 - t0) * SR)), len(A.data) - ia, len(tail) - ib)
            st = window_stats(comp(A.data[ia:ia + n], A.vol_db), comp(tail[ib:ib + n], vol), search_s=0.5)
            upd = [(t0 + float(st['win_t'][i]), st['sim'][i], st['resid'][i], st['lvl'][i], st['lag'][i]) for i in range(len(st['win_t']))]
            self.live_result = (token, upd, dict(level_db=st['level_db'], null_db=st['null_db']))
        except Exception:
            self.live_result = ('error', traceback.format_exc())
        finally:
            self.cmp_busy = False

    def live_poll(self):
        c = self.cmp
        cap = self.cap
        self.cmp_bounds(entries=False)
        if not self.view_user:
            self.view = [c['origin'], max(c['end'], c['origin'] + 0.5)]
        if self.player.playing:
            self.player.pause()
        if c['active'] == 'A':  # the scopes show the recorded clip at the running point
            self.player.clip = c['A']
            self.player.pos = int(max(0, min(len(c['A'].data), round((self.head_t() - c['sa']) * SR))))
        frames = cap.rec_frames
        if frames >= MAX_REC:
            self.cmp_close()
            return
        if c['auto_pending'] and frames >= 6 * SR:
            c['auto_pending'] = False
            self.live_auto()
        r = self.live_result
        if r is not None:
            self.live_result = None
            if r[0] == 'error':
                self.msg('live comparison failed: ' + r[1].strip().splitlines()[-1])
            elif r[0] == c['token'] and r[2] is not None:
                acc = c['acc']
                for tg, sim, resid, lvl, lag in r[1]:
                    i = int(round((tg - c['sa']) / 0.5))
                    if 0 <= i < len(acc['sim']):
                        acc['sim'][i], acc['resid'][i], acc['lvl'][i], acc['lag'][i] = sim, resid, lvl, lag
                c['live_extra'] = r[2]
                c['stats'] = self.live_stats_dict()
                self.tl_key = None
        if not self.cmp_busy and time.time() - c['last_live'] > 1.0 and frames > 2 * SR:
            c['last_live'] = time.time()
            c['token'] += 1
            self.cmp_busy = True
            tail, tau0 = cap.rec_tail(40 * SR)
            threading.Thread(target=self.live_worker, args=(c['token'], c['A'], c['sa'], c['sb'], tail, tau0, cap.rec_vol), daemon=True).start()

    def live_auto(self):
        """one shot: find where in the recorded clip the live sound is, and put the running point there"""
        c = self.cmp
        tail, tau0 = self.cap.rec_tail(20 * SR)
        if len(tail) < 4 * SR:
            self.msg('auto-align needs a few seconds of live sound first (it fires by itself after about 6 s)')
            return
        lag, score = auto_align(tail, c['A'].data, self.cap.rec_vol, c['A'].vol_db)
        c['score'] = score
        if score < 0.35:
            self.msg('could not find this sound in the recorded clip (match %.2f). Is the same sound playing? You can set the position by hand: click the timeline.' % score)
            return
        c['sb'] = round(c['sa'] + lag - tau0, 3)
        self.cmp_bounds()
        self.cmp_dirty()
        self.tl_key = None
        self.msg('auto-aligned: the live sound is at %s of the clip (match %.2f).  Click the timeline or nudge to adjust, or press Auto-align again.' % (fmt_time(self.head_t() - c['sa'], True), score))

    def live_stop(self, c):
        """end the live comparison: the live recording is saved and opened as clip B of an ordinary comparison, with the alignment you had"""
        data, vol = self.cap.stop_rec()
        A, sa, sb = c['A'], c['sa'], c['sb']
        self.cmp = None
        if data is None or len(data) < SR:
            self.msg('live comparison ended (too short to keep)')
            self.open_loaded(A)
            return
        B = Clip(data, vol, name='live session')
        os.makedirs(REC_DIR, exist_ok=True)
        path = os.path.join(REC_DIR, time.strftime('live_%Y%m%d_%H%M%S.wav'))
        B.save(path)
        self.compare_start(A, B, auto=False)
        self.cmp['sa'], self.cmp['sb'] = sa, sb
        self.cmp_bounds()
        self.view = [self.cmp['origin'], max(self.cmp['end'], self.cmp['origin'] + 0.5)]
        self.cmp_dirty()
        self.msg('live session saved as %s and opened as clip B, with the alignment you had' % os.path.basename(path))

    def live_report(self):
        c = self.cmp
        A, st = c['A'], c['stats']
        elapsed = self.cap.rec_frames / SR
        rp = self.head_t() - c['sa']
        lines = ['live session compared with the recorded clip  (%s)' % A.name,
                 'live for %s    running point in the clip: %s of %s' % (fmt_time(elapsed, True), fmt_time(rp, True), fmt_time(A.duration, True)),
                 'alignment: live time 0 = clip time %s' % fmt_time(c['sb'] - c['sa'], True)]
        if c['score'] is not None:
            lines.append('last auto-align match score %.2f' % c['score'])
        lines.append('')
        if st is None:
            lines.append('measuring ...  (needs a few seconds where the live sound and the clip overlap)')
        else:
            sim, resid, lvl = st['sim'], st['resid'], st['lvl']
            ok = np.flatnonzero(~np.isnan(sim))
            if len(ok):
                rec = ok[-6:]
                lines += ['match, last few seconds       %.2f   (1.00 = same sound, below 0.9 = different)' % float(np.nanmean(sim[rec])),
                          'difference after matching     %.1f dB   (-30 or lower = identical)' % float(np.nanmean(resid[rec])),
                          'level, live relative to clip  %+.1f dB' % float(np.nanmean(lvl[rec])),
                          '',
                          'whole session so far: median match %.2f, %d of %d windows below 0.90' % (float(np.nanmedian(sim[ok])), int((sim[ok] < 0.9).sum()), len(ok))]
            else:
                lines.append('no overlap measured yet')
        lines += ['', 'The white line is the running point.  Click the timeline, drag the live lane, nudge, or use the arrow keys to move it.',
                  'Press Auto-align to fire a one-shot alignment again.  Stop live saves the session as clip B.']
        return '\n'.join(lines)

    def cmp_bounds(self, entries=True):
        c = self.cmp
        c['origin'] = min(c['sa'], c['sb'])
        c['end'] = max(c['sa'] + c['A'].duration, c['sb'] + c['B'].duration)
        if entries:
            self.e_sa.delete(0, 'end')
            self.e_sa.insert(0, '%+.3f' % c['sa'])
            self.e_sb.delete(0, 'end')
            self.e_sb.insert(0, '%+.3f' % c['sb'])

    def cmp_dirty(self):
        c = self.cmp
        c['dirty'] = time.time()
        if c.get('live'):  # the alignment changed: what was measured before no longer counts
            c['token'] += 1
            c['acc'] = self.new_acc(c['A'])
            c['stats'] = None
            c['last_live'] = 0.0

    def set_start_from_entry(self, which):
        if not self.cmp:
            return
        try:
            v = float((self.e_sa if which == 'A' else self.e_sb).get())
        except ValueError:
            self.cmp_bounds()
            return
        self.cmp['s' + which.lower()] = v
        self.cmp_bounds()
        self.cmp_dirty()
        self.tl_key = None

    def nudge(self, d):
        if self.mode != 'compare' or not self.cmp:
            return
        w = 's' + self.v_move.get().lower()
        self.cmp[w] = round(self.cmp[w] + d, 4)
        self.cmp_bounds()
        self.cmp_dirty()
        self.tl_key = None

    def cmp_reset(self):
        if self.cmp:
            self.cmp['sa'] = self.cmp['sb'] = 0.0
            self.cmp_bounds()
            self.cmp_dirty()
            self.tl_key = None

    def cmp_auto(self):
        c = self.cmp
        if not c:
            return
        if c.get('live'):
            self.live_auto()
            return
        rng = None
        if self.sel:
            a0, a1 = self.sel[0] - c['sa'], self.sel[1] - c['sa']  # the selection, in A's own time
            if a1 > 0 and a0 < c['A'].duration:
                rng = (max(0.0, a0), min(c['A'].duration, a1))
        lag, score = auto_align(c['A'].data, c['B'].data, c['A'].vol_db, c['B'].vol_db, a_range=rng)
        c['sb'] = c['sa'] - lag
        c['score'] = score
        self.cmp_bounds()
        self.cmp_dirty()
        self.tl_key = None
        self.msg('auto-aligned on %s: B starts %+.3f s from A (match %.2f)' % ('the selection' if rng else 'the loudest part of A', c['sb'] - c['sa'], score))

    def cmp_align_markers(self):
        c = self.cmp
        if not c or not c['A'].markers or not c['B'].markers:
            self.msg('drop a marker on the same event in both clips first (choose A or B under "move", listen to it, press M)')
            return
        t = self.head_t()
        ma = min(c['A'].markers, key=lambda m: abs(c['sa'] + m['t'] - t))
        mb = min(c['B'].markers, key=lambda m: abs(c['sb'] + m['t'] - t))
        c['sb'] = c['sa'] + ma['t'] - mb['t']
        self.cmp_bounds()
        self.cmp_dirty()
        self.tl_key = None
        self.msg('aligned %s of A with %s of B: B starts %+.3f s from A' % (ma['name'], mb['name'], c['sb'] - c['sa']))

    def cmp_close(self):
        c = self.cmp
        if not c:
            return
        if c.get('live'):
            self.live_stop(c)
            return
        self.player.stop()
        self.open_loaded(c['A'])

    def cmp_listen(self, which):
        if self.mode == 'compare' and self.cmp:
            self.v_active.set(which)
            self.cmp_activate()

    def cmp_activate(self):
        c = self.cmp
        if not c:
            return
        if c.get('live') and self.v_active.get() == 'D':
            self.v_active.set('B')
        c['active'] = self.v_active.get()
        v = self.active_clip()
        if v is not None:
            self.player.swap(v, self.player.pos)
            self.player.set_gain(self.vol_now())
            self.sync_player_region()
        self.tl_key = None

    def cmp_worker(self, token, A, B, sa, sb, want_sg):
        try:
            origin = min(sa, sb)
            end = max(sa + A.duration, sb + B.duration)
            total = int(round((end - origin) * SR))
            pa = place(A.data, int(round((sa - origin) * SR)), total)
            pb = place(B.data, int(round((sb - origin) * SR)), total)
            st = window_stats(comp(pa, A.vol_db), comp(pb, B.vol_db))
            diff = st.pop('diff')
            pk = float(np.abs(diff).max()) or 1e-9
            vA, vB = Clip(pa, A.vol_db, name='A  ' + A.name), Clip(pb, B.vol_db, name='B  ' + B.name)
            vD = Clip((diff * (0.3 / pk)).astype(np.float32), None, name='difference A-B')  # normalised so that it can be heard
            for v in (vA, vB, vD):
                v.ms
                if want_sg:
                    v.sg
            self.cmp_result = (token, origin, end, total, vA, vB, vD, st, pk)
        except Exception:
            self.cmp_result = ('error', traceback.format_exc())
        finally:
            self.cmp_busy = False

    def cmp_poll(self):
        c = self.cmp
        if self.mode != 'compare' or not c:
            return
        if c.get('live'):
            self.live_poll()
            return
        if c['dirty'] is not None and not self.cmp_busy and time.time() - c['dirty'] > 0.25 and self.drag is None:
            c['dirty'] = None
            c['token'] += 1
            self.cmp_busy = True
            threading.Thread(target=self.cmp_worker, args=(c['token'], c['A'], c['B'], c['sa'], c['sb'], self.spec_mode == 'spectrogram'), daemon=True).start()
        r = self.cmp_result
        if r is not None:
            self.cmp_result = None
            if r[0] == 'error':
                self.msg('comparison failed: ' + r[1].strip().splitlines()[-1])
                return
            token, origin, end, total, vA, vB, vD, st, dpk = r
            if token != c['token']:
                return
            t_head = c['origin'] + self.player.pos / SR  # keep the playhead on the same moment when the axis moved
            c.update(vA=vA, vB=vB, vD=vD, stats=st, origin=origin, end=end, dpk=dpk)
            v = self.active_clip()
            self.player.swap(v, int(round((t_head - origin) * SR)))
            self.player.set_gain(self.vol_now())
            self.sync_player_region()
            self.tl_key = None

    # --- timeline: geometry and mouse ---
    def t2x(self, t):
        return self.L0 + (t - self.view[0]) / max(1e-9, self.view[1] - self.view[0]) * (self.L1 - self.L0)

    def x2t(self, x):
        return self.view[0] + (x - self.L0) / (self.L1 - self.L0) * (self.view[1] - self.view[0])

    def duration(self):
        if self.mode == 'rec':
            return self.cap.rec_frames / SR
        return self.axis_end() - self.axis_start()

    def lanes(self):
        S = self.S
        if self.mode == 'compare':
            return dict(A=(S(30), S(68)), B=(S(72), S(110)), sim=(S(115), S(138)), res=(S(142), S(165)))
        return {0: (S(30), S(86)), 1: (S(92), S(148))}

    def lane_at(self, y):
        for k, (a, b) in self.lanes().items():
            if a <= y <= b:
                return k
        return None

    def tl_press(self, e):
        self.root.focus_set()
        self.drag = None
        if self.mode == 'compare' and self.cmp and not (e.state & 0x0004):
            lane = self.lane_at(e.y)
            if lane in ('A', 'B'):
                key = 's' + lane.lower()
                self.drag = ('lane', key, e.x, self.cmp[key])
                self.v_move.set(lane)
                return
        if self.mode in ('review', 'compare'):
            self.drag = ('seek',)
            self.seek_t(self.x2t(e.x))

    def tl_drag(self, e):
        d = self.drag
        if not d:
            return
        if d[0] == 'seek':
            self.seek_t(self.x2t(e.x))
        elif d[0] == 'lane' and self.cmp:
            dt = (e.x - d[2]) / float(self.L1 - self.L0) * (self.view[1] - self.view[0])
            self.cmp[d[1]] = round(d[3] + dt, 3)
            self.cmp_bounds()
            self.tl_key = None

    def tl_release(self, e):
        if self.drag and self.drag[0] == 'lane':
            self.cmp_dirty()
        self.drag = None

    def tl_sel_press(self, e):
        self.root.focus_set()
        if self.mode in ('review', 'compare'):
            self.drag = ('sel', self.x2t(e.x))
            self.set_sel(self.x2t(e.x), self.x2t(e.x) + 0.0)

    def tl_sel_drag(self, e):
        if self.drag and self.drag[0] == 'sel':
            self.set_sel(self.drag[1], self.x2t(e.x))

    def tl_wheel(self, e):
        if self.mode not in ('review', 'compare'):
            return
        k = 0.8 if e.delta > 0 else 1.25
        tc = self.x2t(e.x)
        a, b = self.view
        na, nb = tc - (tc - a) * k, tc + (b - tc) * k
        lo, hi = self.axis_start(), max(self.axis_end(), self.axis_start() + 0.5)
        self.view = [max(lo, na), min(hi, max(nb, na + 0.2))]
        self.view_user = True
        self.tl_key = None

    def tl_pan_start(self, e):
        self.drag = ('pan', e.x, list(self.view))

    def tl_pan(self, e):
        d = self.drag
        if not d or d[0] != 'pan' or self.mode not in ('review', 'compare'):
            return
        dx = (e.x - d[1]) / float(self.L1 - self.L0) * (d[2][1] - d[2][0])
        a, b = d[2][0] - dx, d[2][1] - dx
        lo = self.axis_start()
        if a < lo:
            a, b = lo, b + (lo - a)
        self.view = [a, b]
        self.view_user = True
        self.tl_key = None

    def tl_full(self, e):
        if self.mode in ('review', 'compare'):
            self.view = [self.axis_start(), max(self.axis_end(), self.axis_start() + 0.5)]
            self.view_user = False
            self.tl_key = None

    # --- timeline: drawing ---
    def env_points(self, peaks, t0, cd, lane):
        """polygon (flat list) of the level envelope of `peaks` (one value per 10 ms, starting at time t0) inside `lane` = (y_top, y_bottom)"""
        W = self.L1 - self.L0
        nb = len(peaks)
        a, b = lane
        cy, half = (a + b) / 2.0, (b - a) / 2.0 - 1
        edges = (np.linspace(self.view[0], self.view[1], W + 1) - t0) * 100.0
        ok = (edges[1:] > 0) & (edges[:-1] < nb)
        if not ok.any():
            return None
        i0 = np.clip(np.floor(edges[:-1]).astype(int), 0, nb - 1)
        env = np.maximum.reduceat(np.ascontiguousarray(peaks), i0)
        f = np.clip((20 * np.log10(np.maximum(env, 1e-6)) + cd + 60.0) / 60.0, 0.0, 1.0)
        f[env <= 1e-6] = 0.0
        xs = self.L0 + np.arange(W)
        xs, f = xs[ok], f[ok]
        top = np.stack([xs, cy - f * half], axis=1)
        bot = np.stack([xs[::-1], (cy + f[::-1] * half)], axis=1)
        return np.concatenate([top, bot]).ravel().tolist()

    def heat(self, v, lo, hi, reverse=False):
        """red (bad) - yellow - green (good) colour for v in [lo, hi]; reverse: low is good"""
        x = min(1.0, max(0.0, (v - lo) / (hi - lo)))
        if reverse:
            x = 1.0 - x
        if x < 0.5:
            r, g = 230, int(60 + 2 * x * 140)
        else:
            r, g = int(230 - (x - 0.5) * 2 * 170), 200
        return '#%02x%02x%02x' % (r, g, 70)

    def draw_timeline(self):
        tl, S = self.tl, self.S
        if self.mode == 'live':  # the timeline is collapsed: nothing to draw
            self.tl_key = None
            return
        d = self.duration()
        o = self.origin()
        if self.mode == 'rec':
            self.view = [max(0.0, d - 60.0) if d > 60 else 0.0, max(d, 5.0)]
        c = self.cmp
        key = (self.mode, round(self.view[0], 3), round(self.view[1], 3), int(d * 4) if self.mode == 'rec' else id(self.clip), self.comp, self.k,
               (c['sa'], c['sb'], id(c['stats']), c['active'], int(self.cap.rec_frames / SR * 4) if c.get('live') else 0) if c else None, self.sel, tuple((m[0], m[1]) for m in self.markers_view()))
        if key != self.tl_key:
            self.tl_key = key
            tl.delete('all')
            lanes = self.lanes()
            for k, (a, b) in lanes.items():
                tl.create_rectangle(self.L0, a, self.L1, b, outline=self.th.lane_edge, fill=self.th.lane)
            span = self.view[1] - self.view[0]
            step = next((s for s in (0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if s / span * (self.L1 - self.L0) >= S(90)), 600)
            t = math.ceil(self.view[0] / step) * step
            while t <= self.view[1]:
                x = self.t2x(t)
                tl.create_line(x, S(14), x, self.TH - S(6), fill=self.th.tick)
                tl.create_line(x, S(14), x, S(22), fill=self.th.faint)
                tl.create_text(x + S(3), S(2), text=fmt_time(t, step < 1), fill=self.th.dim, anchor='nw', font=self.F(8))
                t += step
            if self.mode == 'compare' and c:
                for which, col in (('A', self.th.env_a), ('B', self.th.env_b)):
                    clip = c[which]
                    pk = clip.peaks.max(axis=1)
                    cd = (-clip.vol_db) if (self.comp and clip.vol_db is not None) else 0.0
                    s0 = c['s' + which.lower()]
                    pts = self.env_points(pk, s0, cd, lanes[which])
                    if pts and len(pts) >= 6:
                        tl.create_polygon(pts, fill=col, outline='')
                    a, b = lanes[which]
                    ec = self.th.a if which == 'A' else self.th.b
                    tl.create_rectangle(self.t2x(s0), a, self.t2x(s0 + clip.duration), b, outline=ec)
                    tl.create_text(S(4), a + S(2), text=which, fill=ec, anchor='nw', font=self.F(9, 'Consolas', True))
                st = c['stats']
                if st is not None:
                    wt = st['win_t'] + st.get('t_ref', c['origin'])
                    hop = st['hop_s']
                    for i in range(len(wt)):
                        x0, x1 = self.t2x(wt[i]), self.t2x(wt[i] + hop)
                        if x1 < self.L0 or x0 > self.L1:
                            continue
                        x0, x1 = max(self.L0, x0), min(self.L1, x1)
                        if not np.isnan(st['sim'][i]):
                            tl.create_rectangle(x0, lanes['sim'][0], x1, lanes['sim'][1], fill=self.heat(st['sim'][i], 0.3, 0.98), outline='')
                        if not np.isnan(st['resid'][i]):
                            tl.create_rectangle(x0, lanes['res'][0], x1, lanes['res'][1], fill=self.heat(st['resid'][i], -35.0, -5.0, reverse=True), outline='')
                tl.create_text(S(4), lanes['sim'][0] + S(2), text='match', fill=self.th.dim, anchor='nw', font=self.F(8, 'Consolas', True))
                tl.create_text(S(4), lanes['res'][0] + S(2), text='diff', fill=self.th.dim, anchor='nw', font=self.F(8, 'Consolas', True))
            else:
                if self.mode == 'rec':
                    with self.cap.lock:
                        peaks = np.array(self.cap.rec_pk, dtype=np.float32).reshape(-1, 2)
                        flat = np.array(self.cap.rec_fl, dtype=bool).reshape(-1, 2)
                    vol_db = self.cap.rec_vol
                else:
                    peaks, flat, vol_db = self.clip.peaks, self.clip.flat, self.clip.vol_db
                cd = (-vol_db) if (self.comp and vol_db is not None) else 0.0
                if len(peaks):
                    for ch in (0, 1):
                        a, b = lanes[ch]
                        pts = self.env_points(peaks[:, ch], 0.0, cd, lanes[ch])
                        if pts and len(pts) >= 6:
                            tl.create_polygon(pts, fill=(self.th.env_l, self.th.env_r)[ch], outline='')
                        for bi in np.flatnonzero(flat[:, ch])[:4000]:
                            x = self.t2x(bi / 100.0)
                            if self.L0 <= x <= self.L1:
                                tl.create_line(x, a, x, a + S(7), fill=self.th.peak, width=2)
                tl.create_text(S(4), lanes[0][0] + S(2), text='L', fill=self.CL, anchor='nw', font=self.F(8))
                tl.create_text(S(4), lanes[1][0] + S(2), text='R', fill=self.CR, anchor='nw', font=self.F(8))
            if self.sel:
                x0, x1 = self.t2x(self.sel[0]), self.t2x(self.sel[1])
                tl.create_rectangle(max(self.L0, x0), S(14), min(self.L1, x1), self.TH - S(6), fill=self.th.accent, stipple='gray25', outline='')
                for x, lab in ((x0, 'A'), (x1, 'B')):
                    if self.L0 <= x <= self.L1:
                        tl.create_line(x, S(14), x, self.TH - S(6), fill=self.th.accent, width=2)
                        tl.create_text(x + S(2), self.TH - S(16), text=lab, fill=self.th.accent_hi, anchor='nw', font=self.F(8, 'Consolas', True))
            for tm, name, col in self.markers_view():
                x = self.t2x(tm)
                if self.L0 <= x <= self.L1:
                    tl.create_line(x, S(14), x, self.TH - S(6), fill=col, dash=(2, 3))
                    tl.create_polygon(x, S(14), x + S(9), S(14), x, S(24), fill=col, outline='')
                    tl.create_text(x + S(3), S(2), text=name, fill=col, anchor='nw', font=self.F(8, 'Consolas', True))
            tl.create_text(self.CW - S(14), self.TH - S(2), text=('recording' if self.mode == 'rec' else 'showing %.1f s   (wheel zoom, right-drag pan, double-click = all, shift-drag = select A-B)' % span),
                           fill=self.th.faint, anchor='se', font=self.F(8))
        tl.delete('head')
        t = d if self.mode == 'rec' else self.head_t()
        x = self.t2x(t)
        if self.L0 - 1 <= x <= self.L1 + 1:
            col = '#ff4d4d' if self.mode == 'rec' else '#ffffff'
            tl.create_line(x, S(14), x, self.TH - S(6), fill=col, width=2, tags='head')
            tl.create_polygon(x - S(7), S(12), x + S(7), S(12), x, S(24), fill=col, outline='', tags='head')

    # --- main loop ---
    def tick(self):
        t0 = time.perf_counter()
        try:
            self.frame += 1
            self.cmp_poll()
            self.refresh_rows()
            self.update_transport()
            self.draw_timeline()
            if not self.paused:
                self.draw()
        except Exception:
            self.c.itemconfig(self.status, text='drawing error: ' + traceback.format_exc().splitlines()[-1])
        spent = (time.perf_counter() - t0) * 1000.0
        self.work_ms += (spent - self.work_ms) * 0.1
        self.root.after(max(1, int(33 - spent)), self.tick)  # 30 frames a second however long a frame took to draw (as long as it took less than 33 ms)

    def update_transport(self):
        self.update_source_button()
        self.b_rec.config(text=('■ STOP' if self.mode == 'rec' else '● REC'), bg=('#a02828' if self.mode == 'rec' else self.th.btn))
        self.b_play.config(text=('❚❚ PAUSE' if self.player.playing else '▶ PLAY'), state=('normal' if (self.mode == 'review' or (self.mode == 'compare' and not (self.cmp and self.cmp.get('live')))) else 'disabled'))
        self.b_loop.config(bg=(self.th.on if self.player.loop else self.th.btn))
        self.b_spec.config(bg=(self.th.on if self.spec_mode == 'spectrogram' else self.th.btn))
        if self.mode == 'rec':
            self.lbl_time.config(text='● REC  ' + fmt_time(self.duration(), True), fg='#ff6b6b')
            if self.duration() * SR >= MAX_REC:
                self.rec_toggle()
        elif self.mode == 'review':
            self.lbl_time.config(text='%s / %s' % (fmt_time(self.player.pos / SR, True), fmt_time(self.clip.duration, True)), fg=self.th.fg)
        elif self.mode == 'compare':
            lv = bool(self.cmp and self.cmp.get('live'))
            self.lbl_time.config(text=(('LIVE  clip at ' + fmt_time(self.head_t() - self.cmp['sa'], True)) if lv else fmt_time(self.head_t(), True)) + ('  ...' if (self.cmp and not lv and (self.cmp_busy or self.cmp['dirty'])) else ''),
                                 fg=('#ff6b6b' if lv else self.th.fg))
            self.b_cclose.config(text=('Stop live' if lv else 'Close'))
        else:
            self.lbl_time.config(text='LIVE', fg=self.th.live)

    # --- drawing the scope panels ---
    def fx(self, f):
        x0, y0, x1, y1 = self.P['spec']
        return x0 + (math.log10(f) - math.log10(30)) / (math.log10(20000) - math.log10(30)) * (x1 - x0)

    def source(self, n):
        c = self.active_clip()
        if self.mode in ('review', 'compare') and c is not None:
            p = min(self.player.pos, len(c.data))
            x = c.data[max(0, p - n):p]
            if len(x) < n:
                x = np.concatenate([np.zeros((n - len(x), 2), np.float32), x])
            return x
        return self.cap.last(n)

    def draw(self):
        cap, c, S = self.cap, self.c, self.S
        if cap.error:
            c.itemconfig(self.status, text='capture error: ' + cap.error.strip().splitlines()[-1], fill='#ff6666')
            return
        clip = self.active_clip() if self.mode in ('review', 'compare') else None
        x = self.source(4096)
        L, R = x[:, 0], x[:, 1]
        seg = L[:2048]
        zc = np.where((seg[:-1] < 0) & (seg[1:] >= 0))[0]
        s = int(zc[0]) if len(zc) else 0
        n = 1536
        # the gain fits what is drawn (the trace and the last 800 samples of the vectorscope): it falls at once, so a peak never runs into the panel edge, and rises gently
        pk = max(float(np.abs(x[s:s + n]).max()), float(np.abs(x[-800:]).max()))
        tgt = min(1000.0, 0.9 / max(pk, 1e-4))
        self.gain = tgt if tgt < self.gain else self.gain + (tgt - self.gain) * 0.15
        g = self.gain
        if self.zoom in (None, 'osc') and (self.work_ms < 26.0 or self.frame % 2 == 0):
            self.draw_osc(L, R, s, n, g, clip)
        if self.zoom in (None, 'vec'):
            self.draw_vector(x, g, clip)
        # levels
        tnow = time.time()
        if clip is not None:
            v = (clip.vol_db, None, False) if clip.vol_db is not None else None
            cd = (-clip.vol_db) if (self.comp and clip.vol_db is not None) else 0.0
            b = min(len(clip.peaks), max(1, self.player.pos // BLOCK))
            hist = [tuple(h) for h in clip.peaks[max(0, b - 10):b]]
            sess = [float(clip.peaks[:b, 0].max()), float(clip.peaks[:b, 1].max())]
            flat = [int(clip.flat[:b, 0].sum()), int(clip.flat[:b, 1].sum())]
            devtxt = 'clip: ' + (clip.name or '?')
        else:
            cv = cap.vol
            v = cv
            cd = (-cv[0]) if (self.comp and cv and not cv[2]) else 0.0
            with cap.lock:
                hist = [cap.hist[i] for i in range(-min(10, len(cap.hist)), 0)]
                sess = list(cap.sess)
                flat = list(cap.flat)
            devtxt = cap.device + ((' - ' + cap.warn) if cap.warn else '') + (('  ' + cap.eq_note) if cap.eq_note else '')
        recent = hist[-10:] or [(0.0, 0.0)]
        now_pk = [max(h[i] for h in recent) for i in (0, 1)]
        dbn = [db(v_) + cd for v_ in now_pk]
        if self.frame % 3 == 0:  # the average sample over the last second, per channel: loudness figures cannot see this
            second = clip.data[max(0, self.player.pos - SR):max(1, self.player.pos)] if clip is not None else cap.last(SR)
            self.dc_now = [100.0 * float(second[:, i].mean()) * 10 ** (cd / 20.0) for i in (0, 1)] if len(second) else [0.0, 0.0]
        worst_dc = max(abs(self.dc_now[0]), abs(self.dc_now[1]))  # shown only from 1 %: a clean signal has none, so the readout would only ever say 0.0
        c.itemconfig(self.dc_txt, text=('DC  L %+.1f%%  R %+.1f%%' % tuple(self.dc_now)) if worst_dc >= 1.0 else '', fill=(self.th.peak if worst_dc > 3.0 else self.th.dim))
        x0, y0, x1, y1 = self.P['met']
        bars, holds = [], []
        for i in (0, 1):
            if dbn[i] >= self.hold[i] or tnow - self.hold_t[i] > 1.5:
                self.hold[i], self.hold_t[i] = dbn[i], tnow
            xb = self.bar_xs[i]
            bars.append((xb, self.bar_top + min(1.0, max(0.0, -dbn[i] / 60.0)) * self.bar_h, xb + S(50), self.bar_top + self.bar_h))
            holds.append(self.bar_top + min(1.0, max(0.0, -self.hold[i] / 60.0)) * self.bar_h)
        rms = [math.sqrt(float(np.mean(x[-9600:, i] ** 2))) for i in (0, 1)]
        # balance: both channels at once, from the centre outwards: the left level grows to the left, the right level to the right (same 60 dB scale as the peak bars).
        # The levels rise at once and fall over about a sixth of a second, so the bars do not flicker
        for i in (0, 1):
            now = db(rms[i]) + cd
            self.bal_lv[i] = now if now > self.bal_lv[i] else self.bal_lv[i] + (now - self.bal_lv[i]) * 0.2
        half = S(139)
        lens = [min(1.0, max(0.0, (60.0 + v_) / 60.0)) * half for v_ in self.bal_lv]
        bal_rects = [(self.bal_x - lens[0], self.bal_y - S(5), self.bal_x, self.bal_y + S(5)), (self.bal_x, self.bal_y - S(5), self.bal_x + lens[1], self.bal_y + S(5))]
        self.met_geom = {'bars': bars, 'hold': holds, 'bal': bal_rects}  # canvas coordinates
        if self.zoom is None:
            self.draw_bars(x0 + 1, y0 + 1)
        bal = (self.bal_lv[1] - self.bal_lv[0]) if min(self.bal_lv) > -100 else 0.0
        c.itemconfig(self.bal_lbl, text='balance  %+.1f dB' % (-bal + 0.0))  # positive: the left channel is louder (its bar is the longer)
        c.itemconfig(self.m_txt, text=('peak  L %6.1f   R %6.1f dBFS\n' % tuple(dbn) +
                                       'hold  L %6.1f   R %6.1f\n' % tuple(self.hold) +
                                       '%s  L %5.1f  R %5.1f\n' % ('clip peak' if clip is not None else 'session peak', db(sess[0]) + cd, db(sess[1]) + cd) +
                                       'clipped blocks  L %d  R %d' % tuple(flat)))
        if self.spec_mode == 'spectrum':
            pos = self.player.pos if clip is not None else None
            if self.zoom in (None, 'spec') and not (pos is not None and pos == self.plot_pos.get('spec') and 'spec' in self.photos):
                self.plot_pos['spec'] = pos
                self.draw_spectrum(L, R, cd)
        elif self.frame % 3 == 0:
            self.draw_spectrogram(clip, cd)
        in_cmp = self.mode == 'compare'
        in_find = self.findings_on and self.mode == 'review' and self.clip is not None and self.clip.findings is not None
        c.itemconfig('hist', state=('hidden' if (in_cmp or in_find) else 'normal'))
        c.itemconfig('cmp', state=('normal' if (in_cmp or in_find) else 'hidden'))
        c.itemconfig(self.hist_title, text=(('COMPARE   A = %s     B = %s' % (self.cmp['A'].name, self.cmp['B'].name)) if in_cmp else
                                            ('FINDINGS  (F hides them; their markers on the timeline start with !)' if in_find else 'LEVEL HISTORY')))
        if in_cmp:
            c.itemconfig(self.cmp_txt, text=self.cmp_report())
            self.hist_key = None
        elif in_find:
            c.itemconfig(self.cmp_txt, text=self.findings_text())
            self.hist_key = None
        volt = ''
        if v:
            if v[1] is not None:
                volt = 'Windows volume %d%% (%.1f dB)%s' % (round(v[1] * 100), v[0], '  MUTED - nothing is heard here!' if v[2] else '')
            else:
                volt = 'recorded at Windows volume %.1f dB' % v[0]
            if self.comp:
                volt += '  Windows volume ignored'
        lv = bool(self.cmp and self.cmp.get('live'))
        who = ({'A': 'the recorded clip at the running point', 'B': 'the live sound', 'D': ''}[self.cmp['active']] if lv else {'A': 'A', 'B': 'B', 'D': 'the difference'}[self.cmp['active']]) if self.cmp else ''
        mode = {'live': 'LIVE', 'rec': 'LIVE + RECORDING', 'review': ('PLAYING' if self.player.playing else 'CLIP'),
                'compare': (('LIVE COMPARE - showing %s' % who) if lv else ('COMPARE - listening to %s%s' % (who, ' (PLAYING)' if self.player.playing else '')))}[self.mode]
        c.itemconfig(self.status, text='%s   |   %s   |   %s' % ('PAUSED' if self.paused else mode, devtxt, volt), fill=('#ff6666' if (v and v[2]) else self.TXT))
        if self.sel and self.frame % 10 == 0 and self.mode in ('review', 'compare'):
            self.msg(self.sel_stats_text())

    def stop_plots(self):
        """ends the threads of the graphs; they are made again when they are next drawn (after a theme change, a zoom or a resize)"""
        for wk in self.plots.values():
            wk.stop()
        self.plots, self.photos, self.plot_pos = {}, {}, {}
        self.beam, self.vec_last = None, None

    def beam_plot(self, name):
        """the BeamPlot of the oscilloscope ('osc'), the spectrum ('spec') or the level history ('hist'): made when it is first needed, and again after a theme change, a zoom or a resize"""
        wk = self.plots.get(name)
        if wk is not None:
            return wk
        x0, y0, x1, y1 = self.P[name]
        w, h = int(x1 - x0) + 1, int(y1 - y0) + 1
        th = self.th
        glow = 1.0 if th.glow else 0.35  # the Classic theme keeps crisp lines
        colors = (th.left, th.right)
        rows = [int(round(i * (h - 1) / float(len(DB_LINES) - 1))) for i in range(len(DB_LINES))]
        if name == 'osc':
            pl = BeamPlot(plot_base(w, h, th.bg, th.grid, middle=True), th.bg, colors, 0.025, 1.3, 0.35, 64, glow)
        elif name == 'spec':
            bands, cols = [], []
            for i, (lo, hi, _names, _rng) in enumerate(EQ_BANDS):
                a, b_ = int(round(self.fx(max(lo, 30)) - x0)), int(round(self.fx(hi) - x0))
                if i % 2:
                    bands.append((a, b_))
                if lo > 30:
                    cols.append(a)
            pl = BeamPlot(plot_base(w, h, th.bg, th.grid, th.peak, rows, cols, bands, mix(th.bg, th.fg, 0.05)), th.bg, colors, 0.04, 3.2, 0.25, 64, glow)
        elif name == 'met':
            wm, hm = int(x1 - x0) - 1, int(y1 - y0) - 1  # the picture is one pixel inside the panel's frame
            a = plot_base(wm, hm, th.bg, th.grid, frame=False)
            g = np.array(rgbtuple(th.grid), np.uint8)
            for xb in self.bar_xs:  # the frames of the two level bars
                xa, ya, xz, yz = int(xb - x0 - 1), int(self.bar_top - y0 - 1), int(xb + self.S(50) - x0 - 1), int(self.bar_top + self.bar_h - y0 - 1)
                a[ya, xa:xz + 1] = g
                a[yz, xa:xz + 1] = g
                a[ya:yz + 1, xa] = g
                a[ya:yz + 1, xz] = g
            by, cx, half = int(self.bal_y - y0 - 1), int(self.bal_x - x0 - 1), self.S(139)
            a[by, cx - half:cx + half + 1] = g  # the balance bar's baseline and centre mark
            a[by - self.S(7):by + self.S(7) + 1, cx] = g
            pl = BeamPlot(a, th.bg, colors, 0.05, 1.3, 1.0, 64, glow)
        else:  # a level history has to keep its dips visible, so a fast stroke is not dimmed (power 0)
            pl = BeamPlot(plot_base(w, h, th.bg, th.grid, th.peak, rows), th.bg, colors, 0.05, 0.32, 0.0, 200, glow, 'max')  # where the two channels overlap each keeps its colour instead of burning out to white
        wk = self.plots[name] = BeamWorker(pl, self.THREADED)
        return wk

    def show_plot(self, name, item, wk):
        """puts the newest finished picture of a graph on the canvas (if there is a new one)"""
        if wk.error:
            raise RuntimeError(wk.error.strip().splitlines()[-1])
        img = wk.take()
        if img is None:
            return
        photo = self.photos.get(name)
        if photo is not None and (photo.width(), photo.height()) == img.size:
            photo.paste(img)  # the same Tk picture, new pixels
        else:
            self.photos[name] = ImageTk.PhotoImage(img)
            self.c.itemconfig(item, image=self.photos[name])

    def frame_dt(self, name):
        """the seconds since this graph was last drawn (between 16 and 100 ms): how long its phosphor has been fading"""
        now = time.time()
        dt = min(0.1, max(0.016, now - self.plot_time.get(name, now - 0.033)))
        self.plot_time[name] = now
        return dt

    def draw_osc(self, L, R, s, n, g, clip):
        """the oscilloscope (rising-edge trigger on the left channel): the stretch is added to each channel's phosphor screen.  A paused recording keeps its picture"""
        x0, y0, x1, y1 = self.P['osc']
        pos = self.player.pos if clip is not None else None
        wk = self.beam_plot('osc')
        if pos is not None and pos == self.plot_pos.get('osc') and 'osc' in self.photos:
            return
        self.plot_pos['osc'] = pos
        dt = self.frame_dt('osc')
        w, h = x1 - x0, y1 - y0
        xs = np.linspace(0.0, w, n)
        self.osc_pts, paths = [], []
        for d in (L, R):
            ys = np.clip(h / 2.0 - d[s:s + n] * g * (h / 2.0 - 4), 1.0, h - 1.0)
            paths.append((xs, ys))
            self.osc_pts.append((xs + x0, ys + y0))
        wk.add(lambda pl: [pl.add(ch, a[0], a[1], dt) for ch, a in enumerate(paths)])
        self.show_plot('osc', self.osc_item, wk)

    def draw_vector(self, x, g, clip):
        """the vectorscope: the samples since the last frame are added to the beam screen (left across, right up) and its picture is shown"""
        x0, y0, x1, y1 = self.P['vec']
        side = int(min(x1 - x0, y1 - y0)) - 2
        size = max(64, min(side, 520))
        wk = self.plots.get('vec')
        if wk is None or wk.plot.screen.size != size or wk.plot.side != side:
            self.stop_plot('vec')
            wk = self.plots['vec'] = BeamWorker(BeamVector(size, side, self.vec_lut), self.THREADED)
            self.beam, self.vec_last = wk.plot.screen, None
        pos = self.player.pos if clip is not None else self.cap.pos
        new = None if self.vec_last is None else pos - self.vec_last
        clear = False
        if new is None or new < 0 or new > 4000:  # the first frame, or a jump: start again from the last 1600 samples
            clear, new = True, 1600
        elif new == 0:  # paused: the picture stays
            self.show_plot('vec', self.vec_item, wk)
            return
        self.vec_last = pos
        seg = x[-(new + 1):]  # the first is the last sample of the previous frame, so the path goes on without a gap
        u, v, dt = seg[:, 0] * g, seg[:, 1] * g, new / float(SR)

        def job(pl):
            if clear:
                pl.screen.clear()
            pl.screen.add(u, v, dt)
        wk.add(job)
        self.show_plot('vec', self.vec_item, wk)

    def draw_bars(self, ox, oy):
        """the level bars, their hold lines and the balance bars: each channel's light (a dim fill, a white-hot edge, a glow around it) is put into its screen; ox, oy: where the picture
        starts on the canvas"""
        wk = self.beam_plot('met')
        geom = self.met_geom
        R = lambda v, o: int(round(v)) - int(o)
        spans = []
        for i in (0, 1):
            bx0, ty, bx1, by = (R(geom['bars'][i][0], ox), R(geom['bars'][i][1], oy), R(geom['bars'][i][2], ox), R(geom['bars'][i][3], oy))
            rx0, ry0, rx1, ry1 = (R(geom['bal'][i][0], ox), R(geom['bal'][i][1], oy), R(geom['bal'][i][2], ox), R(geom['bal'][i][3], oy))
            spans.append((bx0, ty, bx1, by, R(geom['hold'][i], oy), rx0, ry0, rx1, ry1))

        def job(pl):
            for i, (bx0, ty, bx1, by, hy, rx0, ry0, rx1, ry1) in enumerate(spans):
                buf = pl.screens[i].buf
                buf[:] = 0.0
                if by - ty > 1:
                    buf[ty:by, bx0 + 1:bx1] = 0.22  # the fill (dim: the glow adds to it, and over a whole bar it would otherwise turn white)
                    buf[ty:ty + 2, bx0 + 1:bx1] = 6.0  # the white-hot edge
                buf[max(0, hy - 1):hy + 1, bx0:bx1 + 1] = 10.0  # the hold line
                if rx1 - rx0 > 1:
                    buf[ry0:ry1, rx0:rx1] = 0.22
                    edge = slice(rx0, rx0 + 2) if i == 0 else slice(rx1 - 2, rx1)
                    buf[ry0:ry1, edge] = 6.0
        wk.add(job)
        self.show_plot('met', self.met_item, wk)

    def stop_plot(self, name):
        wk = self.plots.pop(name, None)
        if wk is not None:
            wk.stop()
        self.photos.pop(name, None)

    def draw_spectrum(self, L, R, cd):
        c = self.c
        x0, y0, x1, y1 = self.P['spec']
        win = np.hanning(4096)
        wsum = win.sum()
        fr = np.fft.rfftfreq(4096, 1.0 / SR)
        edges = np.logspace(math.log10(30), math.log10(20000), 140)
        wk = self.beam_plot('spec')
        dt = self.frame_dt('spec')
        self.spec_pts, paths = [], []
        for ch, data in ((0, L), (1, R)):
            mag = np.abs(np.fft.rfft(data * win)) * 2.0 / wsum
            px, py = [], []
            for a, b_ in zip(edges[:-1], edges[1:]):
                sel = (fr >= a) & (fr < b_)
                v_ = float(mag[sel].max()) if sel.any() else float(mag[np.searchsorted(fr, a)])
                dd = db(v_) + cd
                px.append(self.fx(math.sqrt(a * b_)))
                py.append(min(y1, max(y0, y0 + (-dd) / DB_RANGE * (y1 - y0))))
            px, py = np.array(px), np.array(py)
            paths.append((px - x0, py - y0))
            self.spec_pts.append((px, py))
        wk.add(lambda pl: [pl.add(ch, a[0], a[1], dt) for ch, a in enumerate(paths)])
        self.show_plot('spec', self.spec_item, wk)

    def draw_spectrogram(self, clip, cd):
        c = self.c
        x0, y0, x1, y1 = self.P['spec']
        W, H = x1 - x0 - 2, y1 - y0 - 2
        ncols = max(40, W // 2)
        nb = SG_BANDS
        arr = np.full((ncols, nb), FLOOR, np.float32)
        head = None
        if clip is None:
            cap = self.cap
            end = cap.pos
            if self.sg_pos == 0 or end - self.sg_pos > SR:
                self.sg_pos = end
            k = 0
            while self.sg_pos + SG_HOP <= end and k < 8:
                self.sg_pos += SG_HOP
                if end - self.sg_pos < SR + SG_NFFT:
                    w = cap.window(self.sg_pos, SG_NFFT).astype(np.float64).mean(axis=1)
                    self.sg_cols.append(sg_column(w))
                k += 1
            cols = list(self.sg_cols)[-ncols:]
            if cols:
                arr[-len(cols):] = np.array(cols)
        else:
            sg = clip.sg
            ci = max(0, (self.player.pos - SG_NFFT) // SG_HOP)
            fut = int(ncols * 0.25)
            c0 = ci - (ncols - fut) + 1
            lo, hi = max(0, c0), min(len(sg), c0 + ncols)
            if hi > lo:
                arr[lo - c0:hi - c0] = sg[lo:hi]
            head = x0 + 1 + int((ncols - fut) / float(ncols) * W)
        idx = (np.clip((arr + cd + 90.0) / 90.0, 0.0, 1.0) * 255).astype(np.uint8)
        img = np.ascontiguousarray(np.transpose(self.lut[idx], (1, 0, 2))[::-1])
        self.sg_photo = ImageTk.PhotoImage(Image.fromarray(img).resize((W, H), Image.Resampling.BILINEAR))
        c.itemconfig(self.sg_item, image=self.sg_photo)
        c.coords(self.sg_head, (head if head is not None else -10), y0, (head if head is not None else -10), y1)

    def history_loop(self):
        try:
            self.refresh_history()
        except Exception:
            self.c.itemconfig(self.status, text='drawing error: ' + traceback.format_exc().splitlines()[-1])
        self.root.after(4, self.history_loop)

    def refresh_history(self):
        """redraw the level history when it has moved on by a pixel or what it shows has changed.  It has its own fast timer because the main loop runs at a different and uneven pace"""
        if self.paused or self.mode == 'compare' or (self.findings_on and self.mode == 'review') or self.zoom not in (None, 'hist'):
            return False
        if time.time() - self.plot_time.get('hist', 0.0) < 0.03:  # at most about 30 pictures a second, however wide the history is
            return False
        x0, y0, x1, y1 = self.P['hist']
        width = int(x1 - x0)
        clip = self.clip if self.mode == 'review' else None
        if clip is not None:
            total = min(len(clip.peaks), max(1, self.player.pos // BLOCK))
            cd = (-clip.vol_db) if (self.comp and clip.vol_db is not None) else 0.0
        else:
            total = self.cap.pos // BLOCK
            v = self.cap.vol
            cd = (-v[0]) if (self.comp and v and not v[2]) else 0.0
        key = ((total - 1) * width // HIST_BLOCKS, round(cd, 2), id(clip), width)  # the column the newest block is in
        if key == self.hist_key:
            return False
        self.hist_key = key
        if clip is not None:
            hist = clip.peaks[max(0, total - HIST_BLOCKS - 100):total]
        else:
            with self.cap.lock:
                hist = list(self.cap.hist)
                total = self.cap.pos // BLOCK
        self.draw_history(hist, cd, total)
        return True

    def draw_history(self, hist, cd, total):
        """hist: the last blocks (oldest first, (peak L, peak R) each) of a run of `total` blocks.  The panel has one column per pixel and every block belongs to one fixed column
        (block * width // 3000), so a complete column never changes and the picture moves left by exactly one pixel when the next column completes"""
        x0, y0, x1, y1 = self.P['hist']
        width = int(x1 - x0)
        arr = np.asarray(hist, dtype=np.float64)
        if len(arr) < 3:
            return
        cols = np.arange(total - len(arr), total) * width // HIST_BLOCKS
        starts = np.concatenate([[0], np.flatnonzero(np.diff(cols)) + 1])
        bars = np.maximum.reduceat(arr, starts, axis=0)[1:-1]  # the first column may lack blocks and the last one is still filling
        ids = cols[starts][1:-1]
        if len(ids) < 2:
            return
        keep = ids > ids[-1] - width
        bars, ids = bars[keep], ids[keep]
        xs = (x1 - (ids[-1] - ids)).astype(float)
        wk = self.beam_plot('hist')
        self.plot_time['hist'] = time.time()
        self.hist_pts, paths = [], []
        for i in (0, 1):
            dd = np.maximum(-DB_RANGE, 20 * np.log10(np.maximum(bars[:, i], 1e-6)) + cd)
            ys = y0 + (-np.minimum(dd, 0.0)) / DB_RANGE * (y1 - y0)
            paths.append((xs - x0, ys - y0))
            self.hist_pts.append((xs, ys))

        offsets = self.HIST_OFFSETS

        def job(pl):
            pl.clear()  # a fresh picture each time: the history scrolls, it does not fade
            for i, a in enumerate(paths):
                for dy in offsets:  # the line is drawn a few times a fraction of a pixel apart: a more solid line
                    pl.add(i, a[0], a[1] + dy, 0.0)
        wk.add(job)
        self.show_plot('hist', self.hist_item, wk)

    def cmp_report(self):
        c = self.cmp
        if c.get('live'):
            return self.live_report()
        A, B, st = c['A'], c['B'], c['stats']
        cdA = (-A.vol_db) if (self.comp and A.vol_db is not None) else 0.0
        cdB = (-B.vol_db) if (self.comp and B.vol_db is not None) else 0.0
        fm = lambda v: ('%.1f' % v) if v is not None else '--'
        la, lb = A.integrated(cdA), B.integrated(cdB)
        pa, pb = db(A.peak) + cdA, db(B.peak) + cdB
        lines = ['loudness (integrated)   A %s LUFS    B %s LUFS    B - A  %s LU' % (fm(la), fm(lb), ('%+.1f' % (lb - la)) if (la is not None and lb is not None) else '--'),
                 'peak                    A %.1f dBFS   B %.1f dBFS   B - A  %+.1f dB' % (pa, pb, pb - pa),
                 'start positions         A %+.3f s    B %+.3f s    (B starts %+.3f s after A)' % (c['sa'], c['sb'], c['sb'] - c['sa'])]
        if c['score'] is not None:
            lines.append('auto-align match score  %.2f   (1.00 = identical shape)' % c['score'])
        lines.append('')
        if st is None:
            lines.append('measuring ...')
        else:
            sim, resid, lag, lvl = st['sim'], st['resid'], st['lag'], st['lvl']
            ok = ~np.isnan(sim)
            if ok.any():
                bad = ok & (sim < 0.9)
                first = ''
                if bad.any():
                    i = int(np.flatnonzero(bad)[0])
                    first = '   first at %s' % fmt_time(st['win_t'][i] + c['origin'], True)
                lines += ['match at this alignment',
                          '   median %.2f   windows below 0.90: %d of %d (%.0f%%)%s' % (float(np.nanmedian(sim)), int(bad.sum()), int(ok.sum()), 100.0 * bad.sum() / ok.sum(), first),
                          '   level B relative to A (source level): %+.1f dB' % st['level_db'],
                          '   null test (A minus level-matched B): %.1f dB   (-30 or lower = identical)' % st['null_db'], '']
                t = self.head_t() - c['origin']
                i = int(min(len(st['win_t']) - 1, max(0, t / st['hop_s'])))
                if not np.isnan(sim[i]):
                    lines += ['at the playhead (window starting %s)' % fmt_time(st['win_t'][i] + c['origin'], True),
                              '   match %.2f   difference %.1f dB   level B-A %+.1f dB' % (sim[i], resid[i], lvl[i]),
                              '   B would line up best %+.3f s from where it is now' % (lag[i] if not np.isnan(lag[i]) else 0.0)]
            lines += ['', 'strips under the clips: green = alike, red = different', '(top: match, bottom: what is left of A after subtracting B)']
        if c['active'] == 'D' and A.peak > 0:
            lines.append('listening to the difference, made audible (normalised); it is really %.1f dB below A' % (-20 * math.log10(max(c.get('dpk', 1e-6) / max(A.peak, 1e-6), 1e-6))))
        return '\n'.join(lines)


def self_check(out=None):
    """start the program in a hidden window on the real sound card for a few seconds and report; used to test builds.  Returns the exit code."""
    cap = Capture()
    cap.start()
    root = tk.Tk()
    root.withdraw()
    app = App(root, cap)
    t0 = time.time()
    while time.time() - t0 < 3.0:
        root.update()
        time.sleep(0.02)
        if time.time() - t0 > 1.5:
            app.set_spec_mode('spectrogram')
    status = app.c.itemcget(app.status, 'text')
    frames = cap.pos
    root.destroy()
    cap.stop = True
    bad = bool(cap.error) or 'drawing error' in status
    report = '%s: frames=%d input=%s error=%s status=%s' % ('FAIL' if bad else 'OK', frames, cap.device, (cap.error or 'none').strip().splitlines()[-1], status)
    if out:
        open(out, 'w').write(report + '\n')
    else:
        print(report)
    return 1 if bad else 0


def main():
    if '--analyze' in sys.argv:  # no window: a report, a JSON file and a picture next to each WAV (and a segment comparison for two)
        files = [a for a in sys.argv[sys.argv.index('--analyze') + 1:] if not a.startswith('--')]
        if not files:
            sys.exit('usage: pc_audio_scope.py --analyze CLIP.wav [OTHER.wav]')
        text = analyze_files(files)
        try:
            print(text)
        except Exception:
            pass
        sys.exit(0)
    if WINDOWS:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            sys.setswitchinterval(0.001)  # the window thread gets the interpreter back within a millisecond when a graph's thread has it
            ctypes.windll.winmm.timeBeginPeriod(1)  # without it Windows timers tick every 15.6 ms, so 33 ms frames come 33-48 ms apart
        except Exception:
            pass
        try:  # its own taskbar button with its own icon, not grouped under Python's when run from source
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('PCAudioScope.App')
        except Exception:
            pass
    if '--check' in sys.argv:
        i = sys.argv.index('--check')
        sys.exit(self_check(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))
    cap = Capture()
    cap.start()
    root = tk.Tk()
    app = App(root, cap)
    try:
        root.mainloop()
    finally:
        cap.stop = True
        app.player.stop()
        if WINDOWS:
            try:
                ctypes.windll.winmm.timeEndPeriod(1)
            except Exception:
                pass


if __name__ == '__main__':
    main()
