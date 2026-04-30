# Milestones

## 2026-04-30 - WHOOP Integration

**Status:** In Progress

### Goal

Add WHOOP data integration so the assistant can use private recovery, sleep, strain, and recent activity context in health-aware recommendations while keeping the user data local to the Spark demo environment.

### Planned Scope

- Define the WHOOP auth and data-access flow for local development.
- Add a local integration layer for pulling and caching WHOOP health signals.
- Expose summarized WHOOP context to the assistant prompts/tools without leaking raw data unnecessarily.
- Add demo-safe responses that combine WHOOP signals with visual context, food history, and personal preferences.
- Add prompt and runtime tests covering health-context retrieval, privacy wording, and graceful behavior when WHOOP data is unavailable.

### Current Status

- Milestone created.
- Implementation not started yet.
- No WHOOP-specific tests have been run yet.

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
