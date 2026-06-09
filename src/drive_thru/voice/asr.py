"""Speech-to-text via local faster-whisper.

Runs entirely on your laptop — no API keys, no per-minute cost, no network.
On Apple Silicon (M1/M2/M3) with the default int8 quantization, expect roughly
500ms–1.5s per turn for typical drive-thru utterances.

First-run note: the model weights (~150 MB for "base") download to
~/.cache/huggingface/ the first time `transcribe()` is called. Expect a
30s–2min delay then. Subsequent runs load instantly from cache.

Tuning knobs (env vars, all optional):
    FASTER_WHISPER_MODEL         tiny | base (default) | small | medium | large-v3
    FASTER_WHISPER_DEVICE        cpu (default) | cuda — keep cpu on Mac
    FASTER_WHISPER_COMPUTE_TYPE  int8 (default, recommended for CPU) | int8_float16 | float32

Bigger model = more accurate but slower. "base" is the drive-thru sweet spot.
"""

from __future__ import annotations

import os
import threading

import numpy as np
from faster_whisper import WhisperModel

DEFAULT_SAMPLE_RATE = 16000

# Bias Whisper toward our menu vocabulary. `initial_prompt` is treated like
# preceding text — Whisper preferentially recognizes words it sees in it. This
# fixes the "chicken burger" → "push-pitching" / "Krispy Kreme" / etc. class
# of mistakes that plague generic-vocabulary ASR on domain-specific speech.
_MENU_PROMPT = (
    "Indian fast food drive-thru order at Highway Bites. Items: "
    "Crispy Chicken Burger, Grilled Chicken Burger, Tandoori Chicken Burger, "
    "Spicy Peri Chicken Burger, Double Chicken Burger, Chicken Maharaja Burger, "
    "Aloo Tikki Burger, Paneer Makhani Burger, Veggie Supreme Burger, "
    "Corn and Cheese Burger, Spicy Bean Burger, Fish Fillet Burger, "
    "Regular Fries, Large Fries, Peri Peri Fries, Masala Wedges, Onion Rings, "
    "Chicken Nuggets, Veg Nuggets, Garlic Bread, "
    "Coke, Sprite, Fanta, Iced Tea, Masala Chai, Filter Coffee, "
    "Mango Shake, Chocolate Shake, Vanilla Shake, "
    "Regular Meal, Large Meal, Maharaja Combo, Family Feast. "
    "Modifications: extra cheese, no ice, no salt, no onion, no mayo, "
    "extra spicy, no sugar, less sugar, no lettuce. "
    "Common phrases: I would like, make it a meal, that's all, anything else, "
    "place the order, cancel."
)

# Cache the loaded model — first call pays the load cost, all subsequent
# transcriptions reuse the same in-memory model.
_MODEL: WhisperModel | None = None
_MODEL_LOCK = threading.Lock()


def current_config() -> dict[str, str]:
    """Return the env-driven ASR config that will be used on next load.

    Read lazily — `.env` may not have been loaded yet at module-import time.
    """
    return {
        "model": os.getenv("FASTER_WHISPER_MODEL", "base"),
        "device": os.getenv("FASTER_WHISPER_DEVICE", "cpu"),
        "compute_type": os.getenv("FASTER_WHISPER_COMPUTE_TYPE", "int8"),
    }


def _get_model() -> WhisperModel:
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                cfg = current_config()
                _MODEL = WhisperModel(
                    cfg["model"], device=cfg["device"], compute_type=cfg["compute_type"]
                )
    return _MODEL


def transcribe(audio: np.ndarray, sample_rate: int = DEFAULT_SAMPLE_RATE) -> str:
    """Transcribe int16 mono PCM audio to text. Returns "" if empty."""
    if audio.size == 0:
        return ""

    # faster-whisper expects float32 PCM normalized to [-1, 1].
    audio_float = audio.astype(np.float32) / 32768.0

    model = _get_model()
    segments, _info = model.transcribe(
        audio_float,
        language="en",         # POC is English-only per spec §6 — forcing
                               # language skips Whisper's language-detect pass.
        beam_size=5,
        initial_prompt=_MENU_PROMPT,
        vad_filter=True,       # Drop silence before transcribing (Silero VAD).
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    return " ".join(seg.text for seg in segments).strip()
