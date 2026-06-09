"""Voice REPL for the Highway Bites drive-thru agent.

Run:
    .venv/bin/python -m drive_thru.voice.cli            # full voice loop
    .venv/bin/python -m drive_thru.voice.cli --mute     # ASR + LLM, no TTS (cheap debug)

Push-to-talk flow per turn:
    1. Press Enter at the prompt to start recording.
    2. Speak your order.
    3. Press Enter again to stop. ASR runs immediately.
    4. The agent's reply is printed AND spoken back through the speakers.

Required env: OPENAI_API_KEY (LLM). ASR and TTS run locally — no other keys.
Required deps: `uv pip install -e '.[voice]'`. macOS will prompt for mic
permission on the first recording — grant it via System Settings.

Per-stage latency is printed for each turn so you can see where the
voice-pipeline budget is going (ASR / LLM / TTS).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from drive_thru.agent.graph import build_graph
from drive_thru.order_state import Order
from drive_thru.voice import asr, tts
from drive_thru.voice.audio import play_pcm, record_until_enter

_MIN_AUDIO_SAMPLES = 8000  # ~0.5s at 16 kHz; ignore accidental Enter-Enter

# The kiosk greets the customer at session start. Deterministic + zero-latency
# (no LLM round-trip), so the speaker starts the moment the program is ready.
# Override via env to A/B different copy without touching code.
_DEFAULT_GREETING = "Welcome to Highway Bites! What would you like to have?"


def _greeting() -> str:
    return os.getenv("KIOSK_GREETING", _DEFAULT_GREETING)


def _split_voice_and_display(reply: str) -> tuple[str, str]:
    """Split the agent's reply into (spoken, display-only).

    The agent's prompt instructs it to use a two-paragraph format for replies
    that present a list of options: first paragraph is the brief spoken
    summary, second paragraph is the detail block that goes only to the
    screen. We split on the first blank line.

    Replies without a blank line (a normal acknowledgment, a yes/no question,
    etc.) are spoken in full.
    """
    parts = reply.split("\n\n", 1)
    if len(parts) == 1:
        return reply.strip(), ""
    return parts[0].strip(), parts[1].strip()


def _require_env(name: str) -> None:
    if not os.getenv(name):
        print(f"ERROR: {name} is not set. Add it to .env or export it.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Voice-mode drive-thru REPL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mute", action="store_true",
        help="Skip TTS playback (still prints the reply text). Useful for "
             "iterating without waiting for the audio to play.",
    )
    args = parser.parse_args()

    load_dotenv()
    _require_env("OPENAI_API_KEY")

    app = build_graph()
    thread_id = f"voice-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    first_turn = True

    asr_cfg = asr.current_config()
    tts_voice = tts.current_voice_id()
    print(
        f"Voice mode (thread={thread_id})\n"
        f"  LLM:  {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}\n"
        f"  ASR:  faster-whisper '{asr_cfg['model']}' on {asr_cfg['device']} ({asr_cfg['compute_type']})\n"
        f"  TTS:  Piper '{tts_voice}'" + ('   [muted]' if args.mute else '')
    )

    # Pre-load the TTS voice so a misconfigured PIPER_VOICE fails at startup
    # instead of crashing mid-conversation. Also warms the cache so the first
    # spoken reply isn't held up by a 30s model download.
    if not args.mute:
        print("  preloading TTS voice (first run downloads the model — ~30 MB)...",
              end="", flush=True)
        try:
            tts.synthesize(" ")  # tiny no-op synthesis to force load
            print(" ready.")
        except Exception as exc:
            print(" FAILED.")
            print(f"\nERROR loading Piper voice '{tts_voice}': {exc}", file=sys.stderr)
            print(
                "\nCheck PIPER_VOICE in .env. Browse the catalog at "
                "https://github.com/rhasspy/piper/blob/master/VOICES.md\n"
                "Known-good defaults: en_US-amy-medium, en_US-hfc_female-medium, "
                "en_GB-jenny_dioco-medium",
                file=sys.stderr,
            )
            sys.exit(1)

    print("Push-to-talk: press Enter to record, Enter again to stop. Type 'quit' to exit.")

    greeting = _greeting()
    print(f"\n🍔 Agent (spoken): {greeting}")
    if not args.mute:
        greet_audio, greet_sr = tts.synthesize(greeting)
        play_pcm(greet_audio, sample_rate=greet_sr)

    while True:
        try:
            cmd = input("\n🎤 Ready — Enter to record: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if cmd == "quit":
            return

        print("  recording... (Enter to stop)")
        t_record_start = time.perf_counter()
        audio_np = record_until_enter(sample_rate=asr.DEFAULT_SAMPLE_RATE)
        t_record_end = time.perf_counter()

        if audio_np.size < _MIN_AUDIO_SAMPLES:
            print("  (no audio captured — skipping)")
            continue

        t_asr_start = time.perf_counter()
        transcript = asr.transcribe(audio_np)
        t_asr_end = time.perf_counter()
        if not transcript:
            print("  (Whisper returned empty — skipping)")
            continue
        print(f"👤 You: {transcript}   [ASR {t_asr_end - t_asr_start:.2f}s]")

        update: dict = {"messages": [HumanMessage(content=transcript)]}
        if first_turn:
            update["order"] = Order()
            update["submitted_order_id"] = None
            update["session_ended"] = False
            first_turn = False

        t_llm_start = time.perf_counter()
        result = app.invoke(update, config=config)
        t_llm_end = time.perf_counter()
        reply = (result["messages"][-1].content or "").strip()
        spoken, displayed = _split_voice_and_display(reply)

        print(f"🍔 Agent (spoken): {spoken}   [LLM {t_llm_end - t_llm_start:.2f}s]")
        if displayed:
            indented = "\n".join(f"    {line}" for line in displayed.splitlines())
            print(f"  📋 on-screen:\n{indented}")

        if not args.mute and spoken:
            t_tts_start = time.perf_counter()
            audio_bytes, tts_sample_rate = tts.synthesize(spoken)
            t_tts_end = time.perf_counter()
            print(f"  [TTS gen {t_tts_end - t_tts_start:.2f}s, playing...]")
            play_pcm(audio_bytes, sample_rate=tts_sample_rate)
            t_end = time.perf_counter()
        else:
            t_end = t_llm_end

        # End-to-end latency excludes recording time (that's user-controlled) —
        # measures from "Enter pressed to stop" through the agent's reply being
        # fully delivered (printed + spoken if TTS is on).
        total = t_end - t_record_end
        print(f"  ⏱  total {total:.2f}s  (target: < 2.0s per spec §9)")

        if result.get("submitted_order_id"):
            print(f"✅ Order #{result['submitted_order_id']} placed. Drive forward.")
            return
        if result.get("session_ended"):
            print("👋 Session ended.")
            return


if __name__ == "__main__":
    main()
