# Milestones

## Future

- Add a dev-mode launch script that handles CTranslate2 source compilation for DGX Spark/GB10, including environment creation, activation, dependency installation, and launching through `launch-https.sh`.

## 2026-05-06 - Bidirectional Conversation Handoff

**Status:** Done

### Summary

Added process-local, context-preserving handoff for active voice/video conversations. A second device now receives an in-call offer only when another active device owns the same `conversation_id`; accepting hydrates completed conversation context, selected voice, system prompt, and enabled tools, then transfers ownership. The displaced device shows a bring-back action so the same conversation can move phone -> laptop or laptop -> phone repeatedly.

### Implementation

- `server.py` keeps sanitized in-memory handoff state keyed by `conversation_id`, with active-owner tracking, TTL pruning, pending-handoff guards, and generic transfer control.
- `static/js/app.js` assigns browser-local conversation ids, sends `device`, `chat_id`, and `conversation_id` on `/ws/voice`, replays resumed messages into the current call, and handles continue/bring-back actions.
- `static/css/styles.css` adds a compact handoff banner without changing `static/index.html`.
- `bench/test_handoff.py` covers the bidirectional server mechanics without starting the GPU server.

### Test Status

- Handoff helper smoke: **PASS**.
- Python/JS syntax checks: **PASS**.
- Handoff static assertions: **PASS**.
- `git diff --check`: **PASS**.

## 2026-04-30 - WHOOP Integration

**Status:** Done

### Goal

Add WHOOP data integration so the assistant can use private recovery, sleep, strain, and recent activity context in health-aware recommendations while keeping the user data local to the Spark demo environment.

### Planned Scope

- Define the WHOOP auth and data-access flow for local development.
- Add a local integration layer for pulling and caching WHOOP health signals.
- Expose summarized WHOOP context to the assistant prompts/tools without leaking raw data unnecessarily.
- Add demo-safe responses that combine WHOOP signals with visual context, food history, and personal preferences.
- Add prompt and runtime tests covering health-context retrieval, privacy wording, and graceful behavior when WHOOP data is unavailable.

### Current Status

- Done for the demo path. The local live cache is `demo_files/health.yaml` (gitignored), and the committed fallback is `demo_files/health-dummy-data.yaml` containing dummy private condition, lab, meal, goals, travel, workout, and stub WHOOP context.
- `prompts._load_health_context()` reads that YAML at import time, converts numeric health and WHOOP values into qualitative labels, and appends a speech-safe private block to `VIDEO_CALL_PROMPT`.
- Beat 3 menu guidance now uses visible translated dishes plus food-language reasons by default; diagnosis names, medication names, sensitive category words, and raw numbers stay out of the default spoken path.
- `VoiceSession.load_demo_files()` explicitly skips `health.yaml` and `whoop_auth.json`, so private health data does not leak into the customer-feedback reasoning context.
- Live WHOOP OAuth is implemented behind `WHOOP_CLIENT_ID` / `WHOOP_CLIENT_SECRET`: `clients/whoop.py` handles auth URLs, token exchange, refresh, endpoint fetches, token storage, and replacement of only the `whoop:` subtree in local `demo_files/health.yaml`. The committed dummy file remains the fallback when live cache is absent.

### Implementation Commits

- `6266481 [feat] add fake local health data for Beat 3`
- `b5aa9d8 [feat] inject always-on private health context into VLM prompt`
- `[feat] add WHOOP OAuth flow with local cache and stub fallback`

### Test Status

All requested tests for the stubbed demo path passed.

- Test A speech-safe loader: **PASS**.
- Test B demo-file isolation: **PASS**.
- Test C missing WHOOP subtree graceful degrade: **PASS**.
- Test D live Chinese-menu privacy and grounding regression: **PASS** against local `qwen3.6:35b-a3b`.
- Test F import-time concatenation: **PASS**.
- WHOOP auth URL configuration: **PASS**.
- WHOOP YAML cache and auth token writers: **PASS**.
- WHOOP FastAPI route registration: **PASS**.
- Test G real WHOOP OAuth: **Not run**; browser consent is pending.

## 2026-04-30 - Claw Demo Integration And GPU Runtime

**Recorded commit:** `733ca23 [docs] record final GPU dev server health check`

### Summary

This commit marks the current working Claw demo baseline after merging the main-branch 4-beat demo work into `claw`, hardening Beat 4 routing, and fixing the local runtime so ASR and TTS run on GPU.

### Key Changes And Integrations

- Integrated the main demo changes into `claw`, including the Beat 1 README/realtime-design flow and the 4-beat prompt behavior.
- Added deterministic Beat 4 handwritten-note routing so project tasks, realtime design updates, and personal todos are written to the expected workspace files.
- Tuned the cold-open and demo prompt behavior for the camera/audio readiness response, architecture-to-README flow, fashion beat, private menu recommendation, and handwritten todo callback.
- Built and wired a CUDA-ready `.venv-gpu` environment with torch `2.11.0+cu130` and CUDA-enabled CTranslate2 `4.7.1`.
- Enforced GPU execution for local faster-whisper ASR and Kokoro TTS; the app now fails fast instead of silently falling back to CPU when CUDA is requested.
- Added `launch-gpu-dev.sh` for the Spark demo path: HTTPS on port `8445`, local ASR on CUDA, Kokoro TTS on CUDA, TTS overlap, and uvicorn reload.
- Added a venv-local `imageio-ffmpeg` fallback so browser mic audio decoding works even when system `ffmpeg` is not installed.

### Test Status

All tests recorded for this milestone passed.

- Prompt regression suite: **7/7 PASS** against local `qwen3.6:35b-a3b`.
- Beat coverage: cold open, Beat 1 README tool call, Beat 1 Redis/pub-sub judgment, Beat 1 realtime design follow-up, Beat 2 fashion, Beat 3 private menu recommendation, and Beat 4 handwritten todo routing all passed.
- Beat 4 deterministic routing: **PASS**.
- Python and shell syntax checks: **PASS**.
- Torch CUDA check: **PASS** on `NVIDIA GB10`.
- CTranslate2 CUDA check: **PASS**, including `float16` support.
- Local faster-whisper ASR warmup: **PASS** on `cuda` with `float16`.
- Kokoro TTS synthesis: **PASS** with pipeline loaded on `cuda`.
- FFmpeg fallback check: **PASS** using the `imageio-ffmpeg` aarch64 binary from `.venv-gpu`.
- Detached dev server health check: **PASS** at `https://localhost:8445/health`.

### Current Runtime

- Branch: `claw`
- Demo URL: `https://localhost:8445`
- Health endpoint: `https://localhost:8445/health`
- ASR: local faster-whisper, `Systran/faster-whisper-small.en`, `cuda`, `float16`
- TTS: Kokoro, `cuda`
- LLM/VLM: local Ollama endpoint, `qwen3.6:35b-a3b`

### Known Notes

- Host/user Python had CPU-only torch and CPU-only CTranslate2, so the demo runtime now uses `.venv-gpu`.
- The server uses a self-signed HTTPS certificate; browsers and phones must accept the warning once.
- GitHub push access previously failed for this repository with the available credentials, so this milestone reflects the local branch state.
