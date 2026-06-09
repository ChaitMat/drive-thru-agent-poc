"""Streamlit kiosk UI for the Highway Bites drive-thru agent.

Run:
    .venv/bin/streamlit run src/drive_thru/ui/kiosk.py

Mirrors what a real drive-thru kiosk shows: a chat-style transcript on the
left (only the agent's SPOKEN paragraph appears as a bubble — the same text
that would come out of a real speaker), and the kiosk screen on the right
with the live cart plus the agent's display panel (lists, prices, options).

Drive-thru flow:
    1. Customer's car pulls up → cashier hits "🚗 Car arrived".
    2. Kiosk greets via TTS, the customer presses-to-talk or types.
    3. Agent processes the order; cart + display panel update live.
    4. On submit/cancel, "🚗 Next car" resets for the next customer.

Voice input uses the browser microphone (`st.audio_input`); TTS output
autoplays via `st.audio`. Both routes the same audio path the voice CLI
uses (faster-whisper for ASR, Piper for TTS) so behavior stays consistent.
"""

from __future__ import annotations

import io
import os
import sys
import uuid
import wave
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# --- deployment bootstrap -------------------------------------------------
# Streamlit Community Cloud runs this file directly without `pip install`ing the
# project, so `src/` isn't on sys.path and `import drive_thru` would fail. Add it
# ourselves. No-op for local runs where the package is installed (pip install -e .).
_SRC_DIR = Path(__file__).resolve().parents[2]  # .../src
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from drive_thru.agent.graph import build_graph
from drive_thru.db import repository as repo
from drive_thru.money import format_rupees
from drive_thru.order_state import Order
from drive_thru.voice import tts

# Continuous-listening component: uses Chrome's webkitSpeechRecognition with
# `continuous=true`. Returns {transcript, serial} per final utterance via the
# Streamlit component bridge. See components/voice_listener/index.html.
_VOICE_LISTENER = components.declare_component(
    "voice_listener",
    path=str(Path(__file__).parent / "components" / "voice_listener"),
)

# Menu-panel tabs, rendered in the center column. Order matters — left to right.
MENU_TABS = [
    "Combos",
    "Veg Burgers",
    "Non-veg Burgers",
    "Sides",
    "Drinks",
    "Desserts",
    "Offers",
]
_DEFAULT_TAB = "Combos"

load_dotenv()

st.set_page_config(page_title="Highway Bites — Kiosk", layout="wide", page_icon="🍔")


def _load_secrets_into_env() -> None:
    """Mirror Streamlit secrets into os.environ.

    On Streamlit Community Cloud there is no .env file — configuration comes from
    st.secrets. Copying string secrets into the environment lets every existing
    os.getenv(...) call site (OPENAI_API_KEY, OPENAI_MODEL, PIPER_VOICE,
    KIOSK_GREETING) keep working unchanged. `setdefault` means a real environment
    variable always wins over a secret of the same name.
    """
    try:
        items = list(st.secrets.items())
    except Exception:
        return  # no secrets.toml locally; .env / real env vars are used instead
    for key, value in items:
        if isinstance(value, str):
            os.environ.setdefault(key, value)


@st.cache_resource
def _ensure_database() -> str:
    """Build the seeded SQLite DB on first boot if it's missing.

    data/drive_thru.db is gitignored, so it won't exist on a fresh deploy.
    @st.cache_resource runs this once per process rather than on every rerun.
    """
    from drive_thru.db.init_db import DEFAULT_DB_PATH, init_db

    if not DEFAULT_DB_PATH.exists():
        init_db(DEFAULT_DB_PATH)
    return str(DEFAULT_DB_PATH)


_load_secrets_into_env()
_ensure_database()

_DEFAULT_GREETING = "Welcome to Highway Bites! What would you like to have?"


def _greeting() -> str:
    return os.getenv("KIOSK_GREETING", _DEFAULT_GREETING)


def _split_voice_and_display(reply: str) -> tuple[str, str]:
    """Split on the first blank-line break. See voice/cli.py for the contract."""
    parts = reply.split("\n\n", 1)
    if len(parts) == 1:
        return reply.strip(), ""
    return parts[0].strip(), parts[1].strip()


# ---------- audio conversion helpers ----------

def _pcm_to_wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw int16 PCM (mono) bytes into a complete WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()




# ---------- session lifecycle ----------

def _new_session() -> None:
    """Reset state for a new customer. Called by the 'Car arrived' button."""
    st.session_state.car_arrived = True
    st.session_state.thread_id = f"kiosk-{uuid.uuid4().hex[:8]}"
    st.session_state.messages = []
    st.session_state.order = Order()
    st.session_state.display_block = ""
    st.session_state.submitted_order_id = None
    st.session_state.session_ended = False
    st.session_state.first_turn = True
    st.session_state.pending_audio_wav = None
    st.session_state.audio_seq = 0
    st.session_state.played_audio_seq = 0
    st.session_state.tts_duration_ms = 0
    st.session_state.last_voice_serial = 0
    # Use the pending pattern even on session reset: if the user clicks
    # "🚗 Next car" *after* the segmented_control was already instantiated
    # this run, a direct `menu_tab` assignment would raise. `main()` applies
    # `pending_menu_tab` at its top on the next rerun, before the widget.
    st.session_state.pending_menu_tab = _DEFAULT_TAB
    st.session_state.pop("tab_filter", None)
    if "app" not in st.session_state:
        st.session_state.app = build_graph()

    greeting = _greeting()
    st.session_state.messages.append({"role": "assistant", "content": greeting})
    _queue_tts(greeting)


def _ensure_pre_session() -> None:
    """Defaults for the pre-arrival state (before the first 'Car arrived' click)."""
    st.session_state.setdefault("car_arrived", False)
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("order", Order())
    st.session_state.setdefault("display_block", "")
    st.session_state.setdefault("submitted_order_id", None)
    st.session_state.setdefault("session_ended", False)
    st.session_state.setdefault("first_turn", True)
    st.session_state.setdefault("pending_audio_wav", None)
    st.session_state.setdefault("menu_tab", _DEFAULT_TAB)
    # Sequence-counter pair: every queued TTS bumps `audio_seq`. We autoplay
    # only when `audio_seq > played_audio_seq` — preventing the browser from
    # replaying the previous reply on every script rerun.
    st.session_state.setdefault("audio_seq", 0)
    st.session_state.setdefault("played_audio_seq", 0)
    # Voice-listener coordination. `tts_duration_ms` is the length of the
    # most recent TTS reply; passed to the listener so it mutes its mic for
    # exactly that long (half-duplex — prevents the agent's voice from being
    # transcribed back as the customer). `last_voice_serial` dedupes
    # transcripts the component sends across reruns.
    st.session_state.setdefault("tts_duration_ms", 0)
    st.session_state.setdefault("last_voice_serial", 0)


def _queue_tts(text: str) -> None:
    """Synthesize text to WAV bytes and stash them for autoplay on next render."""
    if not text:
        return
    try:
        pcm, sr = tts.synthesize(text)
    except Exception as exc:
        st.warning(f"TTS failed: {exc}. Continuing without audio for this reply.")
        return
    if not pcm:
        return
    st.session_state.pending_audio_wav = _pcm_to_wav_bytes(pcm, sr)
    st.session_state.audio_seq += 1
    # 16-bit mono PCM → samples = len(pcm) / 2. Duration is forwarded to the
    # voice listener so it mutes the mic for exactly the reply's runtime
    # (half-duplex, prevents the agent's voice from being transcribed back).
    samples = len(pcm) // 2
    st.session_state.tts_duration_ms = int(samples / sr * 1000)


# ---------- agent turn ----------

def _process_pending_turn_inline(user_input: str) -> None:
    """Run an agent turn — renders user bubble + Thinking spinner + reply bubble
    inline inside the chat-window's `with` block, and appends both messages to
    state for the next render."""
    st.session_state.messages.append({"role": "user", "content": user_input})

    update: dict = {"messages": [HumanMessage(content=user_input)]}
    if st.session_state.first_turn:
        update["order"] = Order()
        update["submitted_order_id"] = None
        update["session_ended"] = False
        st.session_state.first_turn = False

    config = {"configurable": {"thread_id": st.session_state.thread_id}}

    with st.chat_message("user"):
        st.write(user_input)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            result = st.session_state.app.invoke(update, config=config)
        reply = (result["messages"][-1].content or "").strip()
        spoken, displayed = _split_voice_and_display(reply)
        st.write(spoken)

    st.session_state.messages.append({"role": "assistant", "content": spoken})
    if displayed:
        st.session_state.display_block = displayed
    if result.get("order") is not None:
        st.session_state.order = result["order"]
    st.session_state.submitted_order_id = result.get("submitted_order_id")
    st.session_state.session_ended = bool(result.get("session_ended"))

    # If the agent's tool calls this turn hint at a category, auto-open the
    # matching menu tab AND forward any name/price filter so the panel shows
    # only what the agent asked about (e.g. just chicken burgers, not all
    # non-veg burgers).
    #
    # IMPORTANT: we write `pending_menu_tab`, NOT `menu_tab`. Streamlit
    # forbids modifying a widget's bound state key once the widget has been
    # instantiated this run, and the segmented_control with `key="menu_tab"`
    # has already rendered in `_render_menu_panel` by the time we get here.
    # `main()` consumes `pending_menu_tab` at its top on the next rerun,
    # BEFORE the widget renders, where direct assignment is allowed.
    tab, tab_filter = _detect_menu_intent_from_messages(result["messages"])
    if tab:
        st.session_state.pending_menu_tab = tab
        if tab_filter is not None:
            st.session_state.tab_filter = tab_filter
        else:
            # New tab without filter — clear any stale filter from a prior turn.
            st.session_state.pop("tab_filter", None)

    if spoken:
        _queue_tts(spoken)


# ---------- menu panel ----------

_VEG_BURGER_HINTS = ("veg", "paneer", "aloo", "corn", "bean", "tikki")
_NONVEG_BURGER_HINTS = ("chicken", "fish", "egg", "bacon", "tandoori", "maharaja", "peri")


_MEAL_UPGRADE_NAMES = {"Regular Meal", "Large Meal"}


def _fetch_tab_items(
    tab: str,
    *,
    name_contains: str | None = None,
    max_price_paise: int | None = None,
) -> list[dict]:
    """Return rows to display under a menu tab. Optional name/price filters
    let us narrow the list to exactly what the agent's most recent
    `query_menu` call asked for."""
    conn = repo.get_connection()
    if tab == "Combos":
        rows = repo.search_combos(
            conn, name_contains=name_contains, max_price_paise=max_price_paise
        )
        # Regular Meal / Large Meal are meal upgrades shown in the top banner,
        # not standalone "combos" — exclude them from the tab to avoid
        # duplicating the upsell prompt.
        return [r for r in rows if r["name"] not in _MEAL_UPGRADE_NAMES]
    if tab == "Veg Burgers":
        return repo.search_menu_items(
            conn, category="burger", is_veg=True,
            name_contains=name_contains, max_price_paise=max_price_paise,
        )
    if tab == "Non-veg Burgers":
        return repo.search_menu_items(
            conn, category="burger", is_veg=False,
            name_contains=name_contains, max_price_paise=max_price_paise,
        )
    if tab == "Sides":
        return repo.search_menu_items(
            conn, category="side",
            name_contains=name_contains, max_price_paise=max_price_paise,
        )
    if tab == "Drinks":
        return repo.search_menu_items(
            conn, category="drink",
            name_contains=name_contains, max_price_paise=max_price_paise,
        )
    if tab == "Desserts":
        return repo.search_menu_items(
            conn, category="dessert",
            name_contains=name_contains, max_price_paise=max_price_paise,
        )
    if tab == "Offers":
        return repo.list_active_promotions(conn)
    return []


def _detect_menu_intent_from_messages(messages) -> tuple[str | None, dict | None]:
    """Inspect the most recent AIMessage's tool calls and return
    `(tab_name, filter_args)` for the menu panel.

    `tab_name` is the segmented_control value to select. `filter_args` is the
    subset of the agent's `query_menu` args we'll forward to the panel's
    fetch (name_contains, max_price_paise) so the panel shows ONLY the items
    the agent asked about — not the entire tab. Returns (None, None) when the
    recent calls don't map to a menu category (order-modifying tools, etc.).
    """
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for tc in tool_calls:
            name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
            args = (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)) or {}

            if name == "query_promotions":
                return ("Offers", None)
            if name != "query_menu":
                continue

            category = args.get("category")
            is_veg = args.get("is_veg")
            name_contains = args.get("name_contains")
            max_price = args.get("max_price_paise")

            tab: str | None = None
            if category == "burger":
                if is_veg is True:
                    tab = "Veg Burgers"
                elif is_veg is False:
                    tab = "Non-veg Burgers"
                elif name_contains:
                    lowered = name_contains.lower()
                    if any(h in lowered for h in _NONVEG_BURGER_HINTS):
                        tab = "Non-veg Burgers"
                    elif any(h in lowered for h in _VEG_BURGER_HINTS):
                        tab = "Veg Burgers"
            elif category == "side":
                tab = "Sides"
            elif category == "drink":
                tab = "Drinks"
            elif category == "dessert":
                tab = "Desserts"
            elif category == "combo":
                tab = "Combos"
            elif name_contains:
                # No category but a name hint — try to land on the right
                # burger tab. Covers the agent shape `query_menu(name_contains="chicken")`.
                lowered = name_contains.lower()
                if any(h in lowered for h in _NONVEG_BURGER_HINTS):
                    tab = "Non-veg Burgers"
                elif any(h in lowered for h in _VEG_BURGER_HINTS):
                    tab = "Veg Burgers"

            if tab is None:
                return (None, None)

            filter_args: dict = {"for_tab": tab}
            if name_contains:
                filter_args["name_contains"] = name_contains
            if max_price is not None:
                filter_args["max_price_paise"] = max_price
            return (tab, filter_args if len(filter_args) > 1 else None)
        # Only the most recent AIMessage with tool calls matters this turn.
        return (None, None)
    return (None, None)


def _render_meal_upgrade_banner() -> None:
    """Top-of-menu banner reminding the customer that meal upgrades exist —
    Regular Meal / Large Meal are bundled side+drink add-ons rather than
    standalone combo lines, so they don't belong inside the Combos tab."""
    conn = repo.get_connection()
    regular = repo.get_combo_by_name(conn, "Regular Meal")
    large = repo.get_combo_by_name(conn, "Large Meal")
    if not regular or not large:
        return
    st.info(
        f"🍟 **Make any burger a meal** &nbsp; — &nbsp; "
        f"**Regular Meal** {format_rupees(regular['price_paise'])} "
        f"(Fries + Coke) &nbsp; · &nbsp; "
        f"**Large Meal** {format_rupees(large['price_paise'])} "
        f"(Large Fries + Large Coke)",
        icon=None,
    )


def _render_menu_panel() -> None:
    st.subheader("📋 Menu")
    # Tabs are a passive visual indicator — the agent drives which one is
    # active. `disabled=True` keeps the styling but ignores clicks so the
    # kiosk behaves like a static drive-thru menu board, not a touchscreen.
    st.segmented_control(
        "Menu category",
        MENU_TABS,
        key="menu_tab",
        label_visibility="collapsed",
        disabled=True,
    )
    active = st.session_state.menu_tab or _DEFAULT_TAB

    # Apply the agent's most recent filter ONLY when the active tab still
    # matches the filter's target — so a manual tab click effectively shows
    # the unfiltered list.
    tab_filter = st.session_state.get("tab_filter") or {}
    apply_filter = tab_filter.get("for_tab") == active
    name_contains = tab_filter.get("name_contains") if apply_filter else None
    max_price = tab_filter.get("max_price_paise") if apply_filter else None

    items = _fetch_tab_items(active, name_contains=name_contains, max_price_paise=max_price)

    if apply_filter:
        bits = []
        if name_contains:
            bits.append(f"matching '{name_contains}'")
        if max_price is not None:
            bits.append(f"under {format_rupees(max_price)}")
        if bits:
            st.caption("🔎 Showing items " + " & ".join(bits))

    if not items:
        st.caption("(nothing in this category right now)")
        return

    if active == "Offers":
        for row in items:
            st.markdown(f"**{row['name']}**")
            st.caption(row.get("description") or "")
        return

    for row in items:
        veg_tag = ""
        if "is_veg" in row:
            veg_tag = "🟢 " if row["is_veg"] else "🔴 "
        price = format_rupees(row["price_paise"])
        st.markdown(f"{veg_tag}**{row['name']}** &nbsp; · &nbsp; {price}")
        if row.get("description"):
            st.caption(row["description"])


# ---------- render helpers ----------

def _render_cart(order: Order) -> None:
    st.subheader("🧾 Your Order")
    if not order.lines:
        st.caption("Cart is empty.")
        return
    for line in order.lines:
        qty = f"{line.quantity} × " if line.quantity > 1 else ""
        st.markdown(f"**{qty}{line.name}** &nbsp;&nbsp; {format_rupees(line.line_total_paise)}")
        for mod in line.modifications:
            st.caption(f"  + {mod.name}")
    st.divider()
    st.markdown(f"Subtotal: **{format_rupees(order.subtotal_paise)}**")
    if order.discount_paise:
        promo = order.applied_promotion
        promo_name = promo.name if promo else "Discount"
        st.markdown(f"{promo_name}: −{format_rupees(order.discount_paise)}")
    st.markdown(f"### Total: {format_rupees(order.total_paise)}")


def _render_display(block: str) -> None:
    st.subheader("📋 On Screen")
    if not block:
        st.caption("(no menu shown — the kiosk screen updates when the agent presents options)")
        return
    st.markdown(block)


def _render_pre_arrival() -> None:
    """The waiting state before a car has arrived."""
    st.markdown(
        "<div style='text-align:center;padding:60px 0'>"
        "<h1>🍔 Highway Bites</h1>"
        "<p style='color:#888;font-size:18px'>Drive-thru kiosk</p>"
        "<p style='color:#555;margin-top:40px'>Waiting for the next customer…</p>"
        "<p style='color:#999;font-size:14px;margin-top:24px'>"
        "🎙️ Voice ordering works in <b>Google Chrome</b> only. "
        "In other browsers, use the <b>⌨️ Type instead</b> box."
        "</p>"
        "</div>",
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        if st.button("🚗 Car arrived", type="primary", use_container_width=True):
            _new_session()
            st.rerun()


# ---------- main ----------

def main() -> None:
    _ensure_pre_session()

    # Apply any pending menu-tab switch BEFORE the segmented_control widget
    # is instantiated this run. Setting `st.session_state.menu_tab` here is
    # legal (the widget hasn't rendered yet); setting it after would raise
    # `StreamlitAPIException`.
    pending_tab = st.session_state.pop("pending_menu_tab", None)
    if pending_tab is not None:
        st.session_state.menu_tab = pending_tab

    if not st.session_state.car_arrived:
        _render_pre_arrival()
        return

    session_done = (
        st.session_state.submitted_order_id is not None
        or st.session_state.session_ended
    )

    # Top-center slot: voice listener while we're accepting input, "Next car"
    # button once the session ends. Both go in the same spot so the customer
    # always knows what to look at the moment the page renders.
    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        if session_done:
            if st.button("🚗 Next car", type="primary", use_container_width=True):
                _new_session()
                st.rerun()
        else:
            mute_for_ms = st.session_state.tts_duration_ms
            mute_serial = st.session_state.audio_seq
            if mute_for_ms:
                st.session_state.tts_duration_ms = 0
            listener_result = _VOICE_LISTENER(
                start=True,
                mute_for_ms=mute_for_ms,
                mute_serial=mute_serial,
                key="voice_listener",
                default=None,
            )
            if listener_result and listener_result.get("transcript"):
                serial = listener_result.get("serial", 0)
                if serial > st.session_state.last_voice_serial:
                    st.session_state.last_voice_serial = serial
                    st.session_state.pending_user_input = listener_result["transcript"]
                    st.rerun()

    # Three columns: conversation (left), tabbed menu screen (center, the
    # focal "kiosk display"), cart (right). Weights give the menu the most
    # room since it carries the most info; chat + cart get equal sides.
    chat_col, menu_col, cart_col = st.columns([1.5, 2, 1.5], gap="medium")

    with chat_col:
        st.header("🍔 Highway Bites")
        st.caption(f"Thread: `{st.session_state.thread_id}`")

        # Only render the audio widget on the very render where the TTS is
        # genuinely new. Subsequent reruns (e.g. user pressing the mic widget)
        # unmount the element entirely — no DOM element, no browser replay.
        # Trade-off: the customer can't manually re-play the agent's reply
        # via the audio controls; they have to ask the agent to repeat. That's
        # the right kiosk UX anyway — interrupting the agent to speak is a
        # natural drive-thru behavior.
        if (
            st.session_state.pending_audio_wav
            and st.session_state.audio_seq > st.session_state.played_audio_seq
        ):
            st.audio(
                st.session_state.pending_audio_wav,
                format="audio/wav",
                autoplay=True,
            )
            st.session_state.played_audio_seq = st.session_state.audio_seq

        # Reserve a slot for the chat window. We'll fill it at the BOTTOM of
        # main() with a single `with chat_window_slot.container(...)` block
        # that includes both the history AND any pending-input processing.
        # Filling the slot once-and-for-all (rather than creating the container
        # here and re-entering it later via `with chat_window:`) avoids the
        # "second chat box appears below" sibling-container bug.
        chat_window_slot = st.empty()

        if st.session_state.submitted_order_id:
            st.success(
                f"✅ Order #{st.session_state.submitted_order_id} placed — drive forward."
            )
        elif st.session_state.session_ended:
            st.info("👋 Session ended.")

    with menu_col:
        _render_meal_upgrade_banner()
        _render_menu_panel()

    with cart_col:
        _render_cart(st.session_state.order)

    if session_done:
        # Fill chat-window slot with the final transcript. The "Next car"
        # button already rendered at the top of the page in the listener
        # slot — no second button needed here.
        with chat_window_slot.container(height=180, border=True):
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.write(msg["content"])
        return

    # Text fallback for debugging — collapsed into the chat column so it
    # doesn't anchor to the bottom of the page (which was scrolling the
    # viewport down on every render). `clear_on_submit=True` empties the
    # field after each send so the next keystroke starts fresh.
    with chat_col:
        with st.expander("⌨️ Type instead", expanded=False):
            with st.form("text_fallback_form", clear_on_submit=True):
                typed = st.text_input(
                    "message",
                    label_visibility="collapsed",
                    placeholder="Type what you'd say at the kiosk…",
                )
                if st.form_submit_button("Send") and typed:
                    st.session_state.pending_user_input = typed
                    st.rerun()

    # Fill the chat-window slot at the very bottom of main(). Streamlit
    # routes this content to where `chat_window_slot` was reserved at the
    # top of chat_col, regardless of the script's current render position.
    # Doing it once-and-for-all here means: history, the new user bubble,
    # and the Thinking… spinner all land in a single container with no
    # sibling boxes.
    pending = st.session_state.pop("pending_user_input", None)
    with chat_window_slot.container(height=180, border=True):
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        if pending:
            _process_pending_turn_inline(pending)

    # IMPORTANT: rerun must happen OUTSIDE the `with` block above. Calling
    # st.rerun() while inside an active container context manager leaves the
    # container's DOM in a half-mounted state — the next rerun then renders
    # a fresh container alongside it instead of replacing it, producing the
    # "two chat boxes stacked" bug. Rerun after the `with` block exits cleanly
    # so the audio-autoplay block at the top of chat_col can re-evaluate
    # with the bumped audio_seq on the next render.
    if pending:
        st.rerun()


main()
