"""Text-to-speech via local Piper (neural).

Runs entirely on your laptop — no API key, no per-character cost, no network
once the model is cached. Quality is genuinely good (neural ONNX model);
on Apple Silicon expect ~300ms–1s of generation per ~100-character reply.

Voice model is fetched from rhasspy/piper-voices on Hugging Face the first
time it's needed (~30 MB for the default `en_US-amy-medium`). Cached to
~/.cache/huggingface/ afterward.

Tuning knobs (env, optional):
    PIPER_VOICE   Voice ID, e.g. en_US-amy-medium (default), en_US-ryan-high,
                  en_GB-alan-medium. Catalog: https://github.com/rhasspy/piper/blob/master/VOICES.md
"""

from __future__ import annotations

import os
import threading

from huggingface_hub import hf_hub_download
from piper import PiperVoice

_PIPER_REPO = "rhasspy/piper-voices"
_DEFAULT_VOICE = "en_US-amy-medium"

_VOICE: PiperVoice | None = None
_VOICE_LOCK = threading.Lock()


def current_voice_id() -> str:
    """Return the env-driven voice ID that will be used on next load.

    Read lazily — `.env` may not have been loaded yet at module-import time.
    """
    return os.getenv("PIPER_VOICE", _DEFAULT_VOICE)


def _hf_relpaths(voice_id: str) -> tuple[str, str]:
    """Return (onnx, onnx.json) repo-relative paths for a Piper voice ID.

    Repo layout: <lang>/<locale>/<name>/<quality>/<voice_id>.onnx
        en_US-amy-medium → en/en_US/amy/medium/en_US-amy-medium.onnx
    """
    locale, name, quality = voice_id.split("-")
    lang = locale.split("_")[0]
    base = f"{lang}/{locale}/{name}/{quality}/{voice_id}"
    return f"{base}.onnx", f"{base}.onnx.json"


def _get_voice() -> PiperVoice:
    global _VOICE
    if _VOICE is None:
        with _VOICE_LOCK:
            if _VOICE is None:
                voice_id = current_voice_id()
                onnx_rel, json_rel = _hf_relpaths(voice_id)
                onnx_path = hf_hub_download(repo_id=_PIPER_REPO, filename=onnx_rel)
                json_path = hf_hub_download(repo_id=_PIPER_REPO, filename=json_rel)
                _VOICE = PiperVoice.load(onnx_path, config_path=json_path)
    return _VOICE


def synthesize(text: str) -> tuple[bytes, int]:
    """Return (raw int16 mono PCM bytes, sample_rate_hz) for the given text.

    Caller is responsible for playing the PCM at the returned sample rate
    (Piper's medium-quality models default to 22050 Hz, but higher-quality
    voices may differ — read from the result).
    """
    if not text.strip():
        return b"", 0
    voice = _get_voice()
    audio_chunks: list[bytes] = []
    sample_rate = 0
    for chunk in voice.synthesize(text):
        if sample_rate == 0:
            sample_rate = chunk.sample_rate
        audio_chunks.append(chunk.audio_int16_bytes)
    return b"".join(audio_chunks), sample_rate
