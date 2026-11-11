"""Code-synthesized audio: sound effects synced to the animation + an original background beat.

Everything is generated from math (sines, noise, envelopes). No samples, no licensed music.
Pure Python (stdlib only), mono float buffers at 44.1 kHz, written as 16-bit stereo WAV.
"""
from __future__ import annotations

import math
import random
import struct
import wave
from array import array
from functools import lru_cache
from pathlib import Path

SR = 44100
TAU = 2 * math.pi


def _buf(n: int) -> array:
    return array("f", bytes(4 * n))


def _noise(n: int, rng: random.Random) -> list[float]:
    return [rng.uniform(-1, 1) for _ in range(n)]


def _lowpass(x, a: float):
    y, out = 0.0, []
    for v in x:
        y += a * (v - y)
        out.append(y)
    return out


def _env_exp(n: int, decay_s: float) -> list[float]:
    k = math.exp(-1.0 / (decay_s * SR))
    e, out = 1.0, []
    for _ in range(n):
        out.append(e)
        e *= k
    return out


# ---------------------------------------------------------------------------
# sound effects
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def sfx(name: str) -> tuple:
    rng = random.Random(name)
    if name == "pop":
        n = int(0.07 * SR)
        env = _env_exp(n, 0.018)
        ph, out = 0.0, []
        for i in range(n):
            f = 700 + 900 * (i / n)
            ph += TAU * f / SR
            out.append(math.sin(ph) * env[i] * 0.8)
        return tuple(out)
    if name == "tick":
        n = int(0.05 * SR)
        env = _env_exp(n, 0.008)
        return tuple(math.sin(TAU * 1600 * i / SR) * env[i] for i in range(n))
    if name == "flip":
        n = int(0.06 * SR)
        nz = _lowpass(_noise(n, rng), 0.5)
        env = _env_exp(n, 0.012)
        return tuple((nz[i] * 0.9 + 0.3 * math.sin(TAU * 2400 * i / SR)) * env[i] for i in range(n))
    if name in ("swish", "whoosh"):
        dur = 0.16 if name == "swish" else 0.45
        n = int(dur * SR)
        nz = _noise(n, rng)
        out, y = [], 0.0
        for i in range(n):
            p = i / n
            a = 0.05 + 0.35 * math.sin(math.pi * p)          # brighter in the middle
            y += a * (nz[i] - y)
            out.append(y * math.sin(math.pi * p) ** 1.5 * 1.6)
        return tuple(out)
    if name == "chips":
        n = int(0.32 * SR)
        out = [0.0] * n
        for k in range(rng.randint(4, 6)):
            start = int(rng.uniform(0, 0.22) * SR)
            f1, f2 = rng.uniform(2800, 4200), rng.uniform(5200, 6800)
            m = int(0.05 * SR)
            env = _env_exp(m, 0.01)
            for i in range(m):
                if start + i < n:
                    out[start + i] += (math.sin(TAU * f1 * i / SR) + 0.6 * math.sin(TAU * f2 * i / SR)) * env[i] * 0.35
        return tuple(out)
    if name == "impact":
        n = int(0.9 * SR)
        env = _env_exp(n, 0.22)
        nz = _lowpass(_noise(n, rng), 0.15)
        ph, out = 0.0, []
        for i in range(n):
            f = 40 + 90 * math.exp(-i / (0.06 * SR))
            ph += TAU * f / SR
            tr = nz[i] * math.exp(-i / (0.03 * SR))
            out.append((math.sin(ph) * 0.95 + tr * 0.8) * env[i])
        return tuple(out)
    if name == "ding":
        n = int(1.4 * SR)
        env = _env_exp(n, 0.35)
        return tuple((math.sin(TAU * 1318.5 * i / SR) + 0.5 * math.sin(TAU * 1975.5 * i / SR)
                      + 0.25 * math.sin(TAU * 2637 * i / SR)) * env[i] * 0.45 for i in range(n))
    if name == "thump":  # heartbeat: lub-dub
        n = int(0.55 * SR)
        out = [0.0] * n
        for off, amp in ((0, 1.0), (0.2, 0.7)):
            s = int(off * SR)
            m = int(0.22 * SR)
            env = _env_exp(m, 0.05)
            ph = 0.0
            for i in range(m):
                ph += TAU * (55 + 30 * math.exp(-i / 800)) / SR
                if s + i < n:
                    out[s + i] += math.sin(ph) * env[i] * amp
        return tuple(out)
    if name in ("sad", "win"):
        notes = [392.0, 349.2, 311.1, 293.7] if name == "sad" else [523.3, 659.3, 784.0, 1046.5]
        step, hold = (0.32, 0.5) if name == "sad" else (0.11, 0.45)
        n = int((step * (len(notes) - 1) + hold + 0.6) * SR)
        out = [0.0] * n
        for k, f in enumerate(notes):
            s = int(k * step * SR)
            m = int((hold + (0.6 if k == len(notes) - 1 else 0.0)) * SR)
            env = _env_exp(m, 0.18 if name == "win" else 0.25)
            for i in range(m):
                if s + i >= n:
                    break
                t = i / SR
                vib = 1 + (0.012 * math.sin(TAU * 5.5 * t) if name == "sad" else 0)
                v = sum(math.sin(TAU * f * h * vib * t) / h for h in (1, 2, 3)) * 0.4
                out[s + i] += v * env[i] * min(1.0, i / 300)
        return tuple(out)
    raise KeyError(name)


SFX_GAIN = {"pop": 0.25, "tick": 0.6, "flip": 0.45, "swish": 0.35, "whoosh": 0.4, "chips": 0.55,
            "impact": 0.8, "ding": 0.7, "thump": 0.75, "sad": 0.7, "win": 0.7}


def sfx_track(events: list[tuple[float, str, float]], duration: float) -> array:
    """Mix (time, name, gain) events into a mono buffer; near-duplicate events are dropped."""
    out = _buf(int(duration * SR))
    last: dict[str, float] = {}
    for t, name, gain in sorted(events):
        if t < 0 or t >= duration or t - last.get(name, -9) < 0.06:
            continue
        last[name] = t
        snd = sfx(name)
        g = gain * SFX_GAIN.get(name, 0.5)
        s = int(t * SR)
        end = min(len(out), s + len(snd))
        for i in range(s, end):
            out[i] += snd[i - s] * g
    return out


# ---------------------------------------------------------------------------
# background beat (original, generated)
# ---------------------------------------------------------------------------

PROGRESSIONS = [  # semitone offsets of chord roots from the key, minor-ish lo-fi feel
    [0, 8, 3, 10], [0, 5, 8, 7], [0, 3, 8, 10], [0, 10, 8, 7],
]


def _freq(semi: float, base: float = 110.0) -> float:
    return base * 2 ** (semi / 12)


def beat_track(duration: float, seed: int) -> array:
    rng = random.Random(seed)
    bpm = rng.choice([84, 88, 90, 92, 96])
    key = rng.choice([0, 2, 3, 5, 7, 9, 10])
    prog = rng.choice(PROGRESSIONS)
    beat = 60.0 / bpm
    bar = 4 * beat
    out = _buf(int(duration * SR))

    def add(buf, start_s, gain):
        s = int(start_s * SR)
        end = min(len(out), s + len(buf))
        for i in range(max(0, s), end):
            out[i] += buf[i - s] * gain

    # drum one-shots
    kn = int(0.35 * SR)
    kenv = _env_exp(kn, 0.09)
    ph, kick = 0.0, []
    for i in range(kn):
        ph += TAU * (45 + 80 * math.exp(-i / (0.03 * SR))) / SR
        kick.append(math.sin(ph) * kenv[i])
    sn = int(0.2 * SR)
    senv = _env_exp(sn, 0.05)
    nz = _lowpass(_noise(sn, rng), 0.6)
    snare = [(nz[i] * 0.8 + 0.35 * math.sin(TAU * 185 * i / SR)) * senv[i] for i in range(sn)]
    hn = int(0.05 * SR)
    henv = _env_exp(hn, 0.01)
    hz = _noise(hn, rng)
    hat = [(hz[i] - (hz[i - 1] if i else 0)) * henv[i] * 0.5 for i in range(hn)]

    # chords (one per bar) and bass
    def chord(root: int, length: float):
        n = int(length * SR)
        tones = [root + 24, root + 27, root + 31, root + 34]  # minor 7th voicing
        buf = []
        for i in range(n):
            t = i / SR
            a = min(1.0, t / 0.25) * math.exp(-t / (length * 1.2))
            v = sum(math.sin(TAU * _freq(s + key) * t + k) for k, s in enumerate(tones)) / len(tones)
            buf.append(v * a)
        return buf

    chords = {r: chord(r, bar) for r in set(prog)}
    bass_cache = {}
    t = 0.0
    bar_i = 0
    while t < duration:
        root = prog[bar_i % len(prog)]
        add(chords[root], t, 0.22)
        if root not in bass_cache:
            n = int(beat * 1.8 * SR)
            env = _env_exp(n, 0.4)
            f = _freq(root + key, 55.0)
            bass_cache[root] = [math.sin(TAU * f * i / SR) * env[i] for i in range(n)]
        for b in (0, 2.5):
            add(bass_cache[root], t + b * beat, 0.35)
        for b in (0, 1.75, 2.5):   # kick pattern
            add(kick, t + b * beat, 0.55)
        for b in (1, 3):           # snare on 2 and 4
            add(snare, t + b * beat, 0.32)
        for k in range(8):         # swung eighth hats
            add(hat, t + (k + (0.12 if k % 2 else 0)) * beat / 2, 0.22 if k % 2 else 0.3)
        t += bar
        bar_i += 1
    return out


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def fade(buf: array, fade_s: float = 1.0) -> None:
    n = len(buf)
    f = int(fade_s * SR)
    for i in range(min(f, n)):
        g = i / f
        buf[i] *= g
        buf[n - 1 - i] *= g


def mix(*layers: tuple[array, float]) -> array:
    n = max(len(b) for b, _ in layers)
    out = _buf(n)
    for b, g in layers:
        for i in range(len(b)):
            out[i] += b[i] * g
    return out


def normalize(buf: array, peak: float = 0.89) -> None:
    m = max((abs(v) for v in buf), default=0.0)
    if m > 0:
        g = peak / m
        for i in range(len(buf)):
            buf[i] *= g


def write_wav(path: Path, buf: array) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        frames = bytearray()
        pack = struct.Struct("<hh").pack
        for v in buf:
            s = int(max(-1.0, min(1.0, v)) * 32767)
            frames += pack(s, s)
        w.writeframes(bytes(frames))
