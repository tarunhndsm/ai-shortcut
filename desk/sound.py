"""Sound for a Short: a bed composed from scratch for it (no license or Content ID question can arise), the voice
polish, effects placed on the picture's cuts and reveals, and the mix at -14 LUFS."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf

from . import bed, ff, sfx

SAMPLE_RATE = 48000
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
VOICE = ("highpass=f=80,equalizer=f=220:t=q:w=1:g=-1.5,equalizer=f=3300:t=q:w=1.2:g=2.5,"
         "equalizer=f=9000:t=q:w=1:g=1.5,acompressor=threshold=-20dB:ratio=3:attack=6:release=120:makeup=2.5")


def _rng(seed: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))


def _hit(rng: np.random.Generator) -> np.ndarray:
    """A deep impact: a falling sine boom under a short noise burst."""
    t = bed._t(1.2)
    pitch = 40 + 95 * np.exp(-t / 0.05)
    boom = np.sin(2 * np.pi * np.cumsum(pitch) / SAMPLE_RATE) * np.exp(-t / 0.35)
    burst = rng.standard_normal(len(t)) * np.exp(-t / 0.03) * 0.3
    return np.tanh(1.5 * (boom + burst))


def _click(rng: np.random.Generator) -> np.ndarray:
    """A key press: a bright tick and a softer thock under it."""
    t = bed._t(0.035)
    tick = np.diff(rng.standard_normal(len(t) + 1)) * np.exp(-t / 0.0025)
    thock = np.sin(2 * np.pi * (900 + rng.uniform(-120, 120)) * t) * np.exp(-t / 0.008) * 0.5
    return tick * 0.6 + thock


def _ding(rng: np.random.Generator) -> np.ndarray:
    t = bed._t(0.6)
    f = 1318.5 * (1 + rng.uniform(-0.01, 0.01))
    return (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(4 * np.pi * f * t)) * np.exp(-t / 0.16)


def _effects(seed: str, seconds: float, events: list[tuple[float, str, float]], cache: Path) -> np.ndarray:
    """One track holding every effect at its time: (seconds, name, gain dB)."""
    rng = _rng(f"{seed}:fx")
    track = np.zeros(int((seconds + 1) * SAMPLE_RATE))
    made = {"whoosh": sfx.whoosh(0.45, seed=3).astype(np.float64), "pop": sfx.pop().astype(np.float64),
            "riser": sfx.riser(0.6, seed=9).astype(np.float64), "hit": _hit(rng)}
    for at, name, gain in events:
        if name == "click":
            sound = _click(rng)
        elif name == "ding":
            sound = _ding(rng)
        else:
            sound = made[name]
        if name == "riser":
            at -= len(sound) / SAMPLE_RATE
        bed._add(track, sound, at, 10 ** (gain / 20))
    return track[: int(seconds * SAMPLE_RATE)].astype(np.float32)


def mix(voice: Path, vo_start: float, seconds: float, work: Path, seed: str, mood: str = "tech",
        events: list[tuple[float, str, float]] | None = None) -> Path:
    """Voice (polished, from `vo_start`) over the bed with ducking, and the effects, at -14 LUFS: a 48 kHz wav."""
    work.mkdir(parents=True, exist_ok=True)
    bed_path = work / "bed.wav"
    sf.write(bed_path, bed.music(seed, seconds, mood), SAMPLE_RATE)
    fx_path = work / "fx.wav"
    sf.write(fx_path, _effects(seed, seconds, events or [], work), SAMPLE_RATE)
    prep = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono"
    delay = int(vo_start * 1000)
    graph = [
        f"[0:a]{prep},{VOICE},adelay=delays={delay}:all=1,apad,atrim=0:{seconds:.3f}[nar]",
        "[nar]asplit=2[voice][key]",
        f"[1:a]{prep},atrim=0:{seconds:.3f},volume=-17dB,afade=t=out:st={max(0.0, seconds - 0.9):.3f}:d=0.9[bedraw]",
        "[bedraw][key]sidechaincompress=threshold=0.04:ratio=5:attack=12:release=260[bed]",
        f"[2:a]{prep},volume=-9dB[fx]",
        "[voice][bed][fx]amix=inputs=3:normalize=0:duration=first[out]",
    ]
    premix = work / "premix.wav"
    ff.run("-i", voice, "-i", bed_path, "-i", fx_path, "-filter_complex", ";".join(graph), "-map", "[out]",
           "-t", f"{seconds:.3f}", "-c:a", "pcm_f32le", premix)
    stats = ff.loudnorm_stats(premix, LOUDNORM)
    normalize = (f"{LOUDNORM}:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
                 f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
                 f":offset={stats['target_offset']}:linear=true")
    out = work / "mix.wav"
    ff.run("-i", premix, "-af", f"{normalize},aresample=48000", "-ac", "2", "-c:a", "pcm_s16le", out)
    return out
