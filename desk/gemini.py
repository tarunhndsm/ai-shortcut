"""Google's Gemini API on the AI Studio free tier, for text and speech. Each model has its own daily quota, so every
call walks a ladder of models and skips the ones that ran out in this run."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import time

import numpy as np
import requests
import soundfile as sf

from . import env

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models"
# Quick and plentiful: scouting, editing, checking.
FAST = ["gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview",
        "gemini-3.1-flash-lite", "gemini-2.5-flash"]
# The writer: the strongest model that answers, then the quick ones.
SMART = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.8-flash", "gemini-3-flash-preview",
         "gemini-2.5-flash"]
TTS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts",
       "gemini-2.5-pro-preview-tts"]
# Gemini 3.0 and 3.1 can loop below their default temperature of 1.0, as Google warns.
LOOP_WHEN_COLD = ("gemini-3-", "gemini-3.1-")
SAMPLE_RATE = 24000
MAX_QUOTA_WAIT = 70.0
_spent: set[str] = set()


class NoModel(RuntimeError):
    """No model on the ladder gave an answer."""


def _quota(resp: requests.Response) -> tuple[str, float | None]:
    """The quotas a 429 names, and how many seconds Google asks us to wait, if it says."""
    try:
        details = resp.json()["error"].get("details", [])
    except (ValueError, KeyError, AttributeError):
        return "", None
    quota, delay = "", None
    for detail in details:
        kind = detail.get("@type", "")
        if kind.endswith("QuotaFailure"):
            quota = ", ".join(f"{v.get('quotaId', '?')}={v.get('quotaValue', '?')}" for v in detail.get("violations", []))
        elif kind.endswith("RetryInfo"):
            try:
                delay = float(str(detail.get("retryDelay", "")).rstrip("s"))
            except ValueError:
                pass
    return quota, delay


def _post(model: str, body: dict, timeout: float) -> requests.Response | None:
    """One request, asked again after a dropped connection, a per-minute 429 or a busy 5xx. None when the model is
    out of quota for today or keeps failing."""
    for attempt in range(3):
        try:
            resp = requests.post(f"{API}/{model}:generateContent", headers={"x-goog-api-key": env.need("AI_GEMINI_API_KEY")},
                                 json=body, timeout=timeout)
        except requests.RequestException as exc:
            log.info("%s: %s", model, type(exc).__name__)
            if attempt == 2:
                return None
            continue
        if resp.status_code == 429:
            quota, delay = _quota(resp)
            log.info("%s: HTTP 429 %s (wait %s s)", model, quota or "(no quota named)", delay)
            if "PerDay" in quota or delay is None or delay > MAX_QUOTA_WAIT or attempt == 2:
                _spent.add(model)
                return None
            time.sleep(delay + 1)
            continue
        if resp.status_code in (500, 502, 503, 504) and attempt < 2:
            time.sleep(6 * (attempt + 1))
            continue
        return resp
    return None


def _parse(raw: str):
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def text_json(system: str, prompt: str, *, models: list[str] | None = None, temperature: float = 0.6,
              images: list[tuple[str, bytes]] | None = None, timeout: float = 150) -> tuple[dict, str]:
    """A JSON answer and the model that gave it. `images` are (mime, bytes) parts placed before the prompt."""
    parts = [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}} for mime, data in images or []]
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [*parts, {"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}}
    errors = []
    for model in models or FAST:
        if model in _spent:
            continue
        body["generationConfig"]["temperature"] = 1.0 if model.startswith(LOOP_WHEN_COLD) else temperature
        started = time.monotonic()
        resp = _post(model, body, timeout)
        if resp is None:
            errors.append(f"{model}: no answer")
            continue
        if resp.status_code != 200:
            errors.append(f"{model}: HTTP {resp.status_code} {resp.text[:160]}")
            continue
        try:
            cand = resp.json()["candidates"][0]
            raw = "".join(p.get("text", "") for p in cand["content"]["parts"] if not p.get("thought"))
            data = _parse(raw)
        except (KeyError, IndexError, ValueError) as exc:
            errors.append(f"{model}: unreadable answer ({exc})")
            continue
        log.info("%s answered in %.1f s", model, time.monotonic() - started)
        return data, model
    raise NoModel("; ".join(errors) or "every model is out of quota")


def _samples(data: bytes, mime: str) -> np.ndarray:
    """Gemini's audio as float samples at SAMPLE_RATE: raw 16-bit PCM from older models, a WAV file from 3.8."""
    if data[:4] == b"RIFF":
        audio, rate = sf.read(io.BytesIO(data), dtype="float32")
        audio = audio.mean(axis=1) if audio.ndim > 1 else audio
    else:
        audio = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        rate = next((int(p[5:]) for p in mime.replace(" ", "").split(";") if p.startswith("rate=")), SAMPLE_RATE)
    if rate != SAMPLE_RATE:
        n = round(len(audio) * SAMPLE_RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def speech(text: str, voice: str, style: str, models: list[str] | None = None) -> tuple[np.ndarray, str]:
    """One reading of the whole script by a prebuilt Gemini voice, and the model that read it."""
    part = {"text": text, "speechMetadata": {"style": style}}
    body = {"contents": [{"parts": [part]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}},
                                                  "languageCode": "en-US"}}}
    errors = []
    for model in models or TTS:
        if model in _spent:
            continue
        for _ in range(2):
            resp = _post(model, body, 300)
            if resp is None:
                errors.append(f"{model}: no answer")
                break
            if resp.status_code == 400 and "speechMetadata" in part and "metadata" in resp.text.lower():
                # TTS models before 3.8 take no style; they read the script as it is.
                part.pop("speechMetadata", None)
                continue
            if resp.status_code != 200:
                errors.append(f"{model}: HTTP {resp.status_code} {resp.text[:160]}")
                break
            try:
                inline = resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                return _samples(base64.b64decode(inline["data"]), inline.get("mimeType", "")), model
            except (KeyError, IndexError):
                errors.append(f"{model}: no audio")
                break
        part["speechMetadata"] = {"style": style}
    raise NoModel("; ".join(errors) or "every TTS model is out of quota")
