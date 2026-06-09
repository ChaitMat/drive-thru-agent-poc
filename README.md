# Highway Bites — Voice-First Drive-Thru Agent

An end-to-end POC for an AI ordering agent at a fast-food drive-thru kiosk. The
customer speaks; the agent listens, takes the order, applies promotions, and
submits to the kitchen — all via voice, with a live kiosk display.

Highway Bites is a fictional Indian highway fast-food chain. The menu, prices,
and promotions are seeded for demo purposes (₹ rupees, paise integer math, no
floats anywhere).

## What this demonstrates

- A **LangGraph state machine** driving an OpenAI-backed conversational agent
  with custom-bound tools for menu lookup, order mutation, promotion
  application, and submission.
- **Voice I/O** that works in two surfaces:
  - **Terminal**: push-to-talk via `sounddevice` + local
    `faster-whisper` ASR + `Piper` neural TTS — no cloud audio dependency.
  - **Browser kiosk**: always-listening via Chrome's Web Speech API, Piper
    TTS streamed back as WAV, all served by Streamlit.
- A **structural eval harness** (23 cases — 8 from spec §9, 15 regressions
  collected during the build) that drives the agent through scripted
  conversations and asserts on tool calls, order state, and reply phrasing.
- **Grounded behavior**: the agent never invents menu items, prices, or
  promotions; every fact comes from a SQLite tool call.

## Three ways to run it

| Mode | Command | Audio | Use case |
|---|---|---|---|
| Text CLI | `python -m drive_thru.agent.cli` | none | iterate on prompt/tools |
| Voice CLI | `python -m drive_thru.voice.cli` | push-to-talk in terminal | local voice demo |
| Kiosk UI | `streamlit run src/drive_thru/ui/kiosk.py` | continuous browser mic | shareable web demo |

## Setup

### Common steps (all three modes)

```bash
git clone <your-fork-url> capstone-poc-planner
cd capstone-poc-planner

# Python ≥ 3.11
python3 -m venv .venv
source .venv/bin/activate

# Core install — enough for the text CLI and Streamlit kiosk
pip install -e .

# Seed the SQLite menu / combos / modifications / promotions
python -m drive_thru.db.init_db --reset

# Configure secrets
cp .env.example .env
# then edit .env and set OPENAI_API_KEY
```

### Mode 1 — Text CLI (minimum deps)

The text REPL is the fastest iteration loop — no audio, no browser, just type
turns and watch the agent respond.

```bash
python -m drive_thru.agent.cli           # plain mode
python -m drive_thru.agent.cli -v        # verbose: shows every tool call,
                                          # tool result, and graph node
```

What works out of the box: ordering, modifications, meal upsell, promotions,
cancel, confirm, submit. No extra deps needed.

### Mode 2 — Voice CLI (local audio)

Push-to-talk over your laptop's microphone. ASR runs locally via
`faster-whisper`; TTS plays locally via `Piper`.

```bash
pip install -e '.[voice]'    # adds faster-whisper, piper-tts, sounddevice, numpy

python -m drive_thru.voice.cli            # full voice loop
python -m drive_thru.voice.cli --mute     # ASR + LLM only, no TTS playback
```

First run will download the Whisper model (~500 MB for `small`) and the Piper
voice (~30 MB) into `~/.cache/huggingface/` — one-time delay.

Mic permission: macOS will prompt on first recording — grant via System
Settings → Privacy & Security → Microphone.

**Tuning**: `FASTER_WHISPER_MODEL=base|small|medium|large-v3` controls accuracy
vs. latency. Default `small` is the drive-thru sweet spot. `PIPER_VOICE` picks
the voice (see [Piper voices catalog](https://github.com/rhasspy/piper/blob/master/VOICES.md)).

### Mode 3 — Streamlit Kiosk UI (browser, always-listening)

A web-based kiosk view. Always-on listening through Chrome's Web Speech API,
TTS streamed back to the browser. Use this for shareable demos.

```bash
pip install -e .             # Piper is pulled in by the core install for TTS
                              # (Whisper isn't needed — Web Speech does ASR
                              # client-side, no server-side audio decoding)

streamlit run src/drive_thru/ui/kiosk.py
```

Open the printed URL in **Chrome** (Web Speech is Chrome-only in practice).
Click 🚗 Car arrived → grant mic permission → talk normally. The agent's reply
plays through your speakers; the listener pauses for the reply's duration
(half-duplex) so the agent's voice isn't transcribed back.

## Environment variables

| Variable | Default | Used by | Notes |
|---|---|---|---|
| `OPENAI_API_KEY` | _(required)_ | all modes | model auth |
| `OPENAI_MODEL` | `gpt-4o-mini` | all modes | LLM choice; `gpt-5.4-mini` also tested |
| `FASTER_WHISPER_MODEL` | `base` | voice CLI | `small` recommended for better accuracy |
| `FASTER_WHISPER_DEVICE` | `cpu` | voice CLI | `cuda` for NVIDIA, `cpu` on Mac |
| `FASTER_WHISPER_COMPUTE_TYPE` | `int8` | voice CLI | `int8_float16` or `float32` for higher precision |
| `PIPER_VOICE` | `en_US-amy-medium` | voice CLI, kiosk | catalog: github.com/rhasspy/piper/blob/master/VOICES.md |
| `KIOSK_GREETING` | `Welcome to Highway Bites! What would you like to have?` | kiosk | shown + spoken on 🚗 Car arrived |

Drop these in `.env` (a template is in `.env.example`).

## Tests and evals

```bash
# Unit tests — tool behavior, schema invariants, money formatting.
python -m pytest -q

# Behavioral evals — drive the LLM through scripted conversations,
# assert on tool calls and final state.
python -m evals                # run all 23 cases
python -m evals 4 11 21        # run a subset by case-id
python -m evals --list         # list everything
```

Current status: **66/66 pytest** ✓ · **23/23 evals** ✓ (regressions all green;
spec cases occasionally flake on LLM non-determinism with `gpt-5.4-mini`).

## Project structure

```
src/drive_thru/
├── agent/          LangGraph wiring, system prompt, tool wrappers, text CLI
├── tools/          Domain logic — query_menu, update_order, swap_meal_item,
│                   confirm_order, submit_order, apply_promotion, cancel_order
├── db/             SQLite schema + seed data + repository helpers
├── order_state.py  Pydantic models: Order, OrderLine, AppliedPromotion
├── money.py        Single rupee-formatting helper (paise → "₹338" / "₹338.65")
├── voice/          asr (faster-whisper), tts (Piper), audio (sounddevice), CLI
└── ui/
    ├── kiosk.py    Streamlit kiosk UI — menu tabs, cart, voice listener
    └── components/voice_listener/index.html
                    Custom Streamlit component wrapping Web Speech API

evals/              Behavioral eval harness — 8 spec cases + 15 regressions
tests/              Unit tests for each tool + graph + money
drive-thru-agent-poc-spec.md
                    Original POC spec (LLM choice deviates: OpenAI vs Gemini)
docs/system-design.md
                    Architecture deep dive
```

## Going further

- **Deploy**: free hosting on Streamlit Community Cloud — see the end of
  `docs/system-design.md` for the deployment recipe.
- **Mock POS**: the spec calls for `/kitchen` and `/cashier` endpoints that
  `submit_order` should dispatch to. Deferred — currently `submit_order`
  writes to SQLite only. Hook for FastAPI POS is in `src/drive_thru/pos/`.
- **Latency**: text-mode p95 ≈ 3 s; voice-mode end-to-end ≈ 13 s (mostly
  Whisper). Levers tried and deferred: embed compact menu in system prompt
  + OpenAI prompt caching; switch to whisper.cpp + Metal on Apple Silicon.

## Acknowledgments

Built against the original `drive-thru-agent-poc-spec.md`. Deviations from the
spec are documented inline in `docs/system-design.md`.
