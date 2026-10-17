"""The narrator. Gemini reads the whole script in one take, so the delivery carries from line to line; Whisper times
every word against the script, and a take that skips or adds words is read again. When Gemini can't, Kokoro-82M
(open source, on the runner's CPU) reads it line by line and gives its own word times."""

from __future__ import annotations

import difflib
import logging
import os
import unicodedata
from pathlib import Path

import numpy as np
import soundfile as sf

from . import gemini

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
VOICE = os.environ.get("DESK_VOICE", "Puck")
STYLE = ("Energetic, confident tech-news host talking to a friend. Quick pace, crisp and clear, warm and smiling, "
         "punchy emphasis on names and numbers, natural and never robotic.")
KOKORO_VOICE = os.environ.get("DESK_KOKORO_VOICE", "am_michael")
ALIGN_MODEL = os.environ.get("DESK_ALIGN_MODEL", "small.en")
WHISPER_RATE = 16000
SPEECH_FLOOR = 0.01
EDGE_KEEP = 0.05
SPEECH_DB = -35.0
LONGEST_PAUSE = 0.32
REHEAR_GAP = 2.0
LONGEST_WORD = 1.5
MIN_COVERAGE = 0.75
MAX_UNSCRIPTED = 1.2
TAKES = 3
_PUNCTUATION = set(".,!?;:\u2026\u2014\u2013-\"'()[]\u201c\u201d\u2018\u2019")


def _tighten(audio: np.ndarray, longest: float) -> np.ndarray:
    """The take with every silence inside it longer than `longest` seconds cut down to that, from its middle."""
    frame = int(0.01 * SAMPLE_RATE)
    count = len(audio) // frame
    if not longest or count < 3:
        return audio
    level = np.sqrt(np.mean(audio[: count * frame].reshape(count, frame) ** 2, axis=1))
    quiet = level < 10 ** (SPEECH_DB / 20) * level.max()
    keep, cuts, run = int(longest / 2 * SAMPLE_RATE), [], 0
    for i, still in enumerate(np.append(quiet, False)):
        if still:
            run += 1
            continue
        if run and i - run > 0 and i < count and run * frame > 2 * keep:
            cuts.append(((i - run) * frame + keep, i * frame - keep))
        run = 0
    if not cuts:
        return audio
    fade = int(0.005 * SAMPLE_RATE)
    ramp = np.linspace(0.0, 1.0, fade, dtype=audio.dtype)
    out = audio[: cuts[0][0]]
    for (_, end), following in zip(cuts, [c[0] for c in cuts[1:]] + [len(audio)]):
        piece = audio[end:following]
        out = np.concatenate([out[:-fade], out[-fade:] * (1 - ramp) + piece[:fade] * ramp, piece[fade:]])
    return out


def _speech_bounds(audio: np.ndarray) -> tuple[int, int]:
    loud = np.flatnonzero(np.abs(audio) > SPEECH_FLOOR * np.abs(audio).max(initial=0.0))
    if not loud.size:
        return 0, len(audio)
    keep = int(EDGE_KEEP * SAMPLE_RATE)
    return max(int(loud[0]) - keep, 0), min(int(loud[-1]) + keep + 1, len(audio))


def _letters(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFC", text).lower() if unicodedata.category(ch)[0] in "LMN")


_whisper = None


def _heard(wav: Path, prompt: str | None = None) -> list[tuple[str, float, float]]:
    """The words Whisper hears in `wav`, with their times; long stretches it skipped are heard again on their own."""
    global _whisper
    from faster_whisper import WhisperModel, decode_audio

    if _whisper is None:
        _whisper = WhisperModel(ALIGN_MODEL, device="cpu", compute_type="int8")
    audio = decode_audio(str(wav), sampling_rate=WHISPER_RATE)

    def hear(start: float, end: float) -> list[tuple[str, float, float]]:
        segments, _ = _whisper.transcribe(audio[int(start * WHISPER_RATE):int(end * WHISPER_RATE)], language="en",
                                          word_timestamps=True, temperature=0.0, condition_on_previous_text=False,
                                          initial_prompt=prompt)
        return [(w.word, start + w.start, start + w.end) for segment in segments for w in segment.words or []
                if start + w.start < end - 0.1]

    duration = len(audio) / WHISPER_RATE
    heard = [word for word in hear(0.0, duration) if word[2] - word[1] <= LONGEST_WORD]
    tenth = WHISPER_RATE // 10
    floor = float(np.abs(audio).max()) * 10 ** (SPEECH_DB / 20)
    loud = [float(np.sqrt(np.mean(audio[i:i + tenth] ** 2))) > floor for i in range(0, len(audio), tenth)]
    edges = [0.0, *(t for _, start, end in heard for t in (start, end)), duration]
    for start, end in zip(edges[::2], edges[1::2]):
        if end - start > REHEAR_GAP and sum(loud[int(start * 10):int(end * 10)]) >= 10:
            heard += hear(start, end)
    return sorted(heard, key=lambda word: word[1])


def _align(tokens: list[tuple[str, int]], heard: list[tuple[str, float, float]]) -> tuple[list[dict], list[float]]:
    """Time the script's own words (text, beat) by matching their letters to the ones Whisper heard, and the share of
    each beat's letters it heard. Words it missed share the time between their neighbors."""
    script, owner = "", []
    beats = max(beat for _, beat in tokens) + 1
    total, found = [0] * beats, [0] * beats
    for index, (text, beat) in enumerate(tokens):
        letters = _letters(text)
        script += letters
        owner += [index] * len(letters)
        total[beat] += len(letters)
    spoken, clock = "", []
    for text, start, end in heard:
        letters = _letters(text)
        spoken += letters
        step = (end - start) / max(len(letters), 1)
        clock += [(start + k * step, start + (k + 1) * step) for k in range(len(letters))]
    first: list[float | None] = [None] * len(tokens)
    last: list[float | None] = [None] * len(tokens)
    for a, b, size in difflib.SequenceMatcher(None, script, spoken, autojunk=False).get_matching_blocks():
        for k in range(size):
            i = owner[a + k]
            found[tokens[i][1]] += 1
            if first[i] is None:
                first[i] = clock[b + k][0]
            last[i] = clock[b + k][1]
    known = [i for i in range(len(tokens)) if first[i] is not None]
    if not known:
        raise RuntimeError("Whisper heard none of the script")
    words, floor = [], 0.0
    for i, (text, beat) in enumerate(tokens):
        if first[i] is None:
            before = max((j for j in known if j < i), default=None)
            after = min((j for j in known if j > i), default=None)
            lo = last[before] if before is not None else heard[0][1]
            hi = first[after] if after is not None else heard[-1][2]
            span = range(before + 1 if before is not None else 0, after if after is not None else len(tokens))
            sizes = [max(len(_letters(tokens[j][0])), 1) for j in span]
            done = sum(sizes[: i - span.start])
            first[i] = lo + (hi - lo) * done / sum(sizes)
            last[i] = lo + (hi - lo) * (done + sizes[i - span.start]) / sum(sizes)
        start = max(first[i], floor)
        words.append({"text": text, "start": round(start, 3), "end": round(max(last[i], start + 0.05), 3), "beat": beat})
        floor = start
    return words, [f / max(t, 1) for f, t in zip(found, total)]


def _unscripted(tokens: list[tuple[str, int]], heard: list[tuple[str, float, float]]) -> float:
    """Seconds of the longest run of heard words that mostly match nothing in the script."""
    script = "".join(_letters(text) for text, _ in tokens)
    words = [(_letters(text), start, end) for text, start, end in heard]
    spoken = "".join(letters for letters, _, _ in words)
    matched = [False] * len(spoken)
    for block in difflib.SequenceMatcher(None, script, spoken, autojunk=False).get_matching_blocks():
        matched[block.b:block.b + block.size] = [True] * block.size
    longest, since, at = 0.0, None, 0
    for letters, start, end in words:
        hit = sum(matched[at:at + len(letters)])
        at += len(letters)
        if not letters:
            continue
        if hit < len(letters) / 2:
            since = start if since is None else since
            longest = max(longest, end - since)
        else:
            since = None
    return longest


def _kokoro(lines: list[str], wav: Path) -> dict:
    try:
        from kokoro import KPipeline
    except ImportError:
        import subprocess
        import sys

        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "kokoro==0.9.4"], check=True)
        from kokoro import KPipeline

    pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    pieces, words, clock = [], [], 0.0
    gap = np.zeros(int(0.12 * SAMPLE_RATE), dtype=np.float32)
    for beat, line in enumerate(lines):
        for result in pipe(line, voice=KOKORO_VOICE, speed=1.08):
            audio = np.asarray(result.audio, dtype=np.float32)
            pending = None
            for tok in result.tokens or []:
                if tok.start_ts is None or tok.end_ts is None:
                    continue
                if pending is None:
                    pending = [tok.text, clock + tok.start_ts, clock + tok.end_ts]
                else:
                    pending[0] += tok.text
                    pending[2] = clock + tok.end_ts
                if tok.whitespace:
                    _add_word(words, pending, beat)
                    pending = None
            if pending is not None:
                _add_word(words, pending, beat)
            pieces += [audio, gap]
            clock += (len(audio) + len(gap)) / SAMPLE_RATE
    audio = np.concatenate(pieces)
    sf.write(wav, audio, SAMPLE_RATE)
    return {"wav": str(wav), "duration": round(len(audio) / SAMPLE_RATE, 3), "words": words, "model": f"kokoro:{KOKORO_VOICE}",
            "coverage": [1.0] * len(lines)}


def _add_word(words: list[dict], pending: list, beat: int) -> None:
    text = pending[0].strip()
    if not text:
        return
    if all(ch in _PUNCTUATION for ch in text):
        if words:
            words[-1]["text"] += text
        return
    words.append({"text": text, "start": round(pending[1], 3), "end": round(max(pending[2], pending[1] + 0.05), 3), "beat": beat})


def narrate(lines: list[str], work: Path) -> dict:
    """The narration of `lines` (one per scene): {"wav", "duration", "words": [{text, start, end, beat}], "model"}."""
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "narration.wav"
    tokens = [(word, beat) for beat, line in enumerate(lines) for word in line.split()]
    text = " ".join(line.strip() for line in lines)
    best = None
    for take in range(TAKES):
        try:
            audio, model = gemini.speech(text, VOICE, STYLE)
        except gemini.NoModel as exc:
            log.warning("Gemini TTS unavailable: %s", exc)
            break
        lo, hi = _speech_bounds(audio)
        audio = _tighten(audio[lo:hi], LONGEST_PAUSE)
        sf.write(wav, audio, SAMPLE_RATE)
        heard = _heard(wav, prompt=text)
        words, coverage = _align(tokens, heard)
        extra = _unscripted(tokens, heard)
        result = {"wav": str(wav), "duration": round(len(audio) / SAMPLE_RATE, 3), "words": words, "model": model,
                  "coverage": [round(c, 3) for c in coverage], "unscripted": round(extra, 2)}
        log.info("take %d (%s): %.1f s, coverage %s, unscripted %.1f s", take + 1, model, result["duration"],
                 result["coverage"], extra)
        if min(coverage) >= MIN_COVERAGE and extra <= MAX_UNSCRIPTED:
            return result
        if best is None or min(coverage) > min(best["coverage"]):
            best = result
            sf.write(work / "best_take.wav", audio, SAMPLE_RATE)
    if best and min(best["coverage"]) >= 0.6:
        (work / "best_take.wav").replace(wav)
        log.info("keeping the best Gemini take (coverage %s)", best["coverage"])
        return best
    log.info("reading with Kokoro")
    return _kokoro(lines, wav)
