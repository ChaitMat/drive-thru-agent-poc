# Deploying the kiosk to Streamlit Community Cloud

The kiosk (`src/drive_thru/ui/kiosk.py`) is ready to run on
[Streamlit Community Cloud](https://share.streamlit.io). This repo already
contains everything the platform needs:

| File | Purpose |
| --- | --- |
| `requirements.txt` | Lean pip install — the agent + Piper TTS, no faster-whisper/sounddevice. |
| `packages.txt` | `espeak-ng` (apt) as insurance for Piper phonemization. |
| `.streamlit/config.toml` | Headless server + kiosk-friendly client/theme. |
| `.streamlit/secrets.toml.example` | Template for the secrets you paste into the dashboard. |

The app builds the seeded SQLite DB on first boot (it's gitignored, so it
isn't in the repo) and reads its `OPENAI_API_KEY` from Streamlit secrets.

## Steps

1. **Push to GitHub.** The repo is already wired to
   `github.com/ChaitMat/drive-thru-agent-poc`. Commit these deploy files and push:

   ```bash
   git add requirements.txt packages.txt .streamlit/config.toml \
           .streamlit/secrets.toml.example .gitignore DEPLOY.md \
           src/drive_thru/ui/kiosk.py
   git commit -m "Add Streamlit Community Cloud deployment config"
   git push origin main
   ```

2. **Create the app.** Go to https://share.streamlit.io → **Create app** →
   **Deploy a public app from GitHub**, then set:
   - **Repository:** `ChaitMat/drive-thru-agent-poc`
   - **Branch:** `main`
   - **Main file path:** `src/drive_thru/ui/kiosk.py`
   - **Advanced → Python version:** `3.12` (matches local development)

3. **Add secrets.** In **Advanced settings → Secrets** (or later via
   **App → Settings → Secrets**), paste — at minimum:

   ```toml
   OPENAI_API_KEY = "sk-..."
   ```

   Optionally also `OPENAI_MODEL`, `PIPER_VOICE`, `KIOSK_GREETING`
   (see `.streamlit/secrets.toml.example`).

4. **Deploy.** First boot is slower: it installs `espeak-ng`, builds the
   SQLite DB, and downloads the ~30 MB Piper voice model from Hugging Face.
   Subsequent loads are fast.

## Notes & limits

- **Voice input** uses Chrome's `webkitSpeechRecognition` — it only works in
  Chromium-based browsers and requires HTTPS (Community Cloud serves HTTPS, so
  this is fine). In other browsers, use the **⌨️ Type instead** fallback.
- **Resources:** the free tier is ~1 GB RAM. This build stays lean by skipping
  faster-whisper/sounddevice; Piper + onnxruntime fit comfortably.
- **Ephemeral filesystem:** the SQLite DB and downloaded voice model live in
  the container and are rebuilt/re-fetched whenever the app restarts. That's
  fine here — the DB is seed data, not user state.
- **Local runs are unchanged:** `streamlit run src/drive_thru/ui/kiosk.py`
  still uses `.env` and the local `data/drive_thru.db`.
