# System Design

This doc explains how the Highway Bites agent is wired end-to-end: the
LangGraph state machine, the tool catalog, the voice pipeline, the kiosk's
display split, the SQLite schema, and the eval harness model. Inline notes
flag deviations from the original POC spec.

## High-level pipeline

```
        ┌───────────────┐                      ┌────────────────────┐
        │   CUSTOMER    │                      │   AGENT (LLM)      │
        │   (mic /      │                      │   gpt-4o-mini      │
        │   keyboard)   │                      │   via LangGraph    │
        └──────┬────────┘                      └─────────┬──────────┘
               │ utterance                               │
               ▼                                         │ tool calls
        ┌───────────────┐                                │
        │     ASR       │                                ▼
        │ Whisper local │             ┌──────────────────────────────┐
        │ / Web Speech  │             │      8 stateful tools        │
        └──────┬────────┘             │  (query_menu, update_order,  │
               │ transcript           │   apply_promotion, …)        │
               ▼                      └──────────────┬───────────────┘
        ┌────────────────┐                           │ reads/mutates
        │ Custom         │                           ▼
        │ Sequential     │                  ┌──────────────────┐
        │ ToolNode       │                  │   Order state    │
        │ (LangGraph)    │                  │   (Pydantic)     │
        └──────┬─────────┘                  │ + SQLite menu    │
               │ reply text                 └──────────────────┘
               ▼
        ┌───────────────┐
        │   TTS         │     ┌──────────────────┐
        │ Piper neural  │ ──▶ │   speaker /      │
        │   ONNX        │     │   browser audio  │
        └───────────────┘     └──────────────────┘
                                       │
                       split on \n\n   │
                                       ▼
                             ┌──────────────────┐
                             │  Kiosk display   │
                             │  (panel of menu  │
                             │  items + cart)   │
                             └──────────────────┘
```

The customer's mic feeds ASR; the transcript flows into the LangGraph agent;
the agent calls one or more tools sequentially; the reply is split into a
spoken paragraph and a display paragraph; the spoken half is read aloud
through Piper TTS; the display half — when present — is routed to the kiosk
screen.

## LangGraph wiring

`src/drive_thru/agent/graph.py` builds a 2-node graph with a `MemorySaver`
checkpointer (one thread per session).

```
START → llm → tools → llm → … → END
        ↑                ↓
        └────────────────┘
        (loops while LLM keeps issuing tool calls)
```

### State schema

`src/drive_thru/agent/state.py` — a `TypedDict` plus a `LastValue` channel for
the `order` field:

| Field | Type | Notes |
|---|---|---|
| `messages` | `list[BaseMessage]` (annotated `add_messages`) | LangChain chat history |
| `order` | `Order` (Pydantic, `LastValue` channel) | live cart; channel forbids concurrent updates |
| `submitted_order_id` | `int \| None` | non-None signals end of session |
| `session_ended` | `bool` | cancel path sets True without submitting |

### Custom sequential ToolNode

The default `langgraph.prebuilt.ToolNode` runs tool calls in **parallel**.
That bit us early: two `update_order` calls in one turn both tried to update
the `order` channel, and LangGraph's `LastValue` channel rejected the
concurrent write with `InvalidUpdateError`.

Fix in `src/drive_thru/agent/graph.py` — `_make_sequential_tools_node` builds
a ToolNode that **threads state through tool calls sequentially**, so each
call's `Command(update={...})` lands before the next call reads state.

Side benefit: tool errors are caught and formatted into a `ToolMessage` the
LLM can recover from, instead of crashing the graph.

## Tool catalog

All eight tools are registered in `src/drive_thru/agent/tools.py` and wired
into the graph via `bind_tools`. Each is a thin wrapper around a pure
domain function in `src/drive_thru/tools/`.

| Tool | Purpose | Touches `order`? |
|---|---|---|
| `query_menu` | Search menu items by category, name, veg/non-veg, max price | no |
| `query_promotions` | List active promotions | no |
| `update_order` | Add / mutate / remove a line | yes |
| `swap_meal_item` | Decompose a meal/combo, swap one component à la carte | yes |
| `apply_promotion` | Attach an order-level discount (percent / flat / combo-price) | yes |
| `cancel_order` | Discard the cart, set `session_ended=True` | yes |
| `confirm_order` | Return a structured read-back (no mutation) | no |
| `submit_order` | Persist to SQLite, return `order_id` | yes (clears) |

### Stateful tools use the `InjectedState + Command` pattern

Each order-mutating tool's wrapper takes the live `Order` via
`InjectedState` and returns a `langgraph.types.Command(update={"order": ...})`
so the graph state stays the single source of truth. The wrappers also
catch `ValueError` from the domain layer and surface a friendly message the
LLM can recover from.

## Voice/display split protocol

The system prompt tells the agent to use a **two-paragraph reply format**
whenever it presents multiple priced items (3+ options, or any cross-category
list). Format:

```
Brief spoken summary + prompt for the customer.

- Option 1 — ₹X
- Option 2 — ₹Y
- Option 3 — ₹Z
```

Voice CLI (`src/drive_thru/voice/cli.py`) and the kiosk both split the reply
on the first blank line. The first paragraph goes to Piper TTS; the second
goes to the screen (terminal stdout or kiosk panel). Single-paragraph replies
are spoken in full and displayed normally.

This keeps short utterances natural ("Crispy Chicken Burger added. Anything
else?" is one paragraph, spoken as-is) while preventing the dreaded "we have
six chicken burgers: the Crispy Chicken Burger for ₹149, the Grilled Chicken
Burger for ₹169, the Tandoori Chicken Burger for ₹179, the Spicy Peri…"
spoken readout that's the default LLM failure mode.

## Voice pipeline

### ASR

| Surface | Tech | Where it runs |
|---|---|---|
| Voice CLI | `faster-whisper` (CTranslate2) | local CPU; default `base` model, `small` recommended |
| Kiosk UI | Chrome Web Speech API | browser (uses Google's cloud ASR under the hood) |

The voice CLI uses `faster-whisper`'s `initial_prompt` parameter to bias the
recognizer toward menu vocabulary ("Crispy Chicken Burger, Aloo Tikki, masala
chai, …"), plus Silero VAD to skip silence. This noticeably improves recognition
of domain-specific phrases on the `base` model.

The kiosk uses Chrome's continuous Web Speech recognizer wrapped in a custom
Streamlit component (`src/drive_thru/ui/components/voice_listener/index.html`).
Each finalized utterance is sent back via `Streamlit.setComponentValue`. The
component is told the duration of each agent TTS reply and mutes itself for
exactly that long (half-duplex), so the agent's voice isn't transcribed as
the customer.

### TTS

Both surfaces use **Piper** — a small, fast neural ONNX TTS that runs on CPU.
The voice CLI plays raw int16 PCM through `sounddevice`; the kiosk wraps the
PCM in a WAV container and serves it via `st.audio(autoplay=True)`.

Voice models are downloaded from `rhasspy/piper-voices` on HuggingFace on
first use (~30 MB) and cached.

> **Deviation from spec**: the spec called for Gemini 2.0 Flash for the LLM
> and ElevenLabs for TTS. We use OpenAI for the LLM (the project's API key
> didn't have access to Whisper or Gemini), and Piper for TTS (ElevenLabs's
> free tier blocked the library voices we needed).

## Display layer (kiosk)

The kiosk (`src/drive_thru/ui/kiosk.py`) renders a 3-column layout:

```
┌─────────────────┬─────────────────┬─────────────────┐
│  💬  Chat       │  📋  Menu       │  🧾  Cart       │
│  (scrollable    │  tabs (passive  │                 │
│   transcript)   │  visual         │  Line items     │
│                 │  indicator,     │  Subtotal       │
│                 │  agent-driven)  │  Discount       │
│                 │                 │  Total          │
└─────────────────┴─────────────────┴─────────────────┘
```

- **Voice listener** pinned at the top center: green pulsing dot when
  listening, gray when muted (during TTS), red on permission error.
- **Menu tabs** (`st.segmented_control(disabled=True)`) are visual-only.
  Every agent `query_menu` / `query_promotions` call updates which tab is
  active *and* what filter is applied (e.g., `query_menu(category=burger,
  name_contains=chicken)` → opens **Non-veg Burgers**, filtered to chicken
  burgers only). Customers can't click tabs; the agent drives them.
- **Cart** updates after every `update_order` / `swap_meal_item` /
  `apply_promotion`.
- **Meal-upgrade banner** above the tabs reminds the customer that Regular
  Meal (₹129) and Large Meal (₹189) exist as upgrades — these are excluded
  from the Combos tab to avoid confusion with proper standalone combos.

State sequencing tricks worth knowing:

- `pending_menu_tab` — Streamlit forbids modifying `st.session_state.menu_tab`
  after the segmented_control widget is instantiated this run, so we stash
  the new tab in `pending_menu_tab` and apply it at the top of `main()` on
  the next rerun, before the widget renders.
- `pending_user_input` — the same two-rerun handshake for transcripts. The
  voice listener stashes the transcript; the next rerun consumes it inside
  the chat-window slot so the user/assistant bubbles and the Thinking spinner
  all land in a single container (avoids a "second chat box appears below"
  bug where late content was rendered as a sibling).
- `audio_seq` vs `played_audio_seq` — TTS autoplay is gated so the same reply
  never re-plays on subsequent reruns. The same `audio_seq` is used as the
  `mute_serial` for the listener so it mutes itself once per new reply.

## Database

SQLite schema in `src/drive_thru/db/schema.sql`. All prices stored as
integer **paise** (1 ₹ = 100 paise) — no floats anywhere in the price math.

```
menu_items       45 rows  (burgers, sides, drinks, desserts; with is_veg flag)
combos           14 rows  (Regular/Large Meal + 12 named combos)
combo_items      41 rows  (links combos to their component menu_items)
modifications    21 rows  (extra cheese, no mayo, no cheese, no sauce, …)
promotions        6 rows  (percent, flat, combo-price types)
orders            -       (created at submit_order time)
order_lines       -       (one per ordered item/combo)
```

`repository.py` exposes typed accessors used by both the tools (`search_menu_items`,
`get_promotion_by_name`, `insert_order`, …) and the kiosk UI (for populating
the menu tabs).

### Promotions

Three discount types are supported, all behind a single `apply_promotion` tool:

| Type | Stored as | Behavior |
|---|---|---|
| `percent` | `discount_value` = bps (e.g., 1500 = 15%) | dynamic — recomputed if order changes |
| `flat_paise` | `discount_value` = paise | dynamic — recomputed if order changes |
| `combo_price_paise` | `discount_value` = bundle price; `condition_json` describes the qualifying items | snapshotted at apply time |

The `combo_price_paise` path supports two condition types: `specific_items`
("Maharaja Combo for ₹299") and `any_n_in_category` ("any two veg burgers for
₹199"). The evaluator picks the most expensive matching items to maximize the
discount.

## Eval harness

`evals/runner.py` drives each `EvalCase` through `build_graph()` against a
fresh `thread_id`, captures every tool call via `app.stream(stream_mode="updates")`,
and runs structural assertions plus optional `custom_check` lambdas.

Each case has:

- `user_messages: list[str]` — scripted turns
- `expected_lines: list[ExpectedLine] | None` — order shape match
- `expected_tools_called: set[str] | None` — must-call set
- `expected_tools_not_called: set[str] | None` — must-not-call set
- `expected_submit: bool | None` — order must / must not be submitted
- `custom_check` — fall-through for things assertions can't express (e.g.,
  "the spoken paragraph has no prices in it")
- `category` — `spec` (the 8 §9 cases) or `regression` (15 bug-derived cases)

23 cases total. Run via `python -m evals`.

### Notable regression cases

| # | Catches |
|---|---|
| 9 | "Make it large" decomposes the meal to à la carte (not just upcharge) |
| 11 | Generic "chicken burger" presents choices (doesn't auto-pick) |
| 14 | Modifications survive `swap_meal_item` |
| 16 | Combo-price promo (Two-Burger Tuesday) actually applies, not just acknowledged |
| 18 | "no garlic mayo" / 19 "no cheddar" normalize to canonical mods (`no mayo`, `no cheese`) |
| 20 | Recommendation reply uses voice/display split, not long readout |
| 21 | After meal upsell resolves, agent invites the next item ("Anything else?") |
| 22 | Vague combo request asks for clarification before `swap_meal_item` |
| 23 | After `swap_meal_item`, reply invites the next item (not just states total) |

## Deployment notes

For a shareable demo, **Streamlit Community Cloud** is the path of least
resistance:

1. Push to GitHub (public or private).
2. Commit a pre-built `data/drive_thru.db` (run `python -m drive_thru.db.init_db --reset`).
3. Add a slim `requirements.txt` listing only what the kiosk needs — Web
   Speech does ASR client-side, so you can drop `faster-whisper`,
   `sounddevice`, `numpy`. Keep `piper-tts`.
4. Sign in at https://share.streamlit.io, point it at the repo, main file
   `src/drive_thru/ui/kiosk.py`.
5. Add `OPENAI_API_KEY` (and any optional tuning vars) in the app's secrets.

Caveats:
- App sleeps after ~7 days idle; cold-start wake adds ~30 s.
- 1 GB RAM cap (Piper voice + LangGraph + OpenAI client comfortably fit).
- Chrome required on the visitor side (Web Speech).
- SQLite is ephemeral — orders don't survive a container restart.
