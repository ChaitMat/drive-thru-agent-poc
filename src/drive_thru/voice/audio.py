"""Microphone capture and speaker playback for voice mode.

Push-to-talk: the caller presses Enter to start `record_until_enter()`, then
Enter again to stop. We use a daemon thread to watch for the second Enter so
the input stream can keep pulling audio chunks without blocking.

On macOS the first call to InputStream triggers an OS-level microphone
permission prompt — once granted, subsequent runs proceed silently.
"""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

# Whisper expects 16 kHz mono int16 PCM.
DEFAULT_SAMPLE_RATE = 16000
_BLOCK_SIZE = 1024


def record_until_enter(sample_rate: int = DEFAULT_SAMPLE_RATE) -> np.ndarray:
    """Capture mic input until the next Enter keypress.

    Returns a 1-D int16 numpy array of samples at `sample_rate` Hz. Returns
    an empty array if no audio was captured (e.g. immediate Enter).
    """
    stop = threading.Event()

    def _await_enter() -> None:
        try:
            input()
        except EOFError:
            pass
        stop.set()

    threading.Thread(target=_await_enter, daemon=True).start()

    chunks: list[np.ndarray] = []
    with sd.InputStream(
        samplerate=sample_rate, channels=1, dtype="int16", blocksize=_BLOCK_SIZE
    ) as stream:
        while not stop.is_set():
            data, _overflow = stream.read(_BLOCK_SIZE)
            chunks.append(data.copy())

    if not chunks:
        return np.zeros(0, dtype=np.int16)
    return np.concatenate(chunks).flatten()


def play_pcm(audio_bytes: bytes, sample_rate: int) -> None:
    """Play raw mono int16 PCM at `sample_rate` Hz. Blocks until done."""
    if not audio_bytes:
        return
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
    sd.play(audio_np, samplerate=sample_rate)
    sd.wait()
