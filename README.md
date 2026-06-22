# spark-realtime-chatbot

A voice + vision AI assistant running locally on DGX Spark — streaming speech recognition, a single joint vision-language-reasoning model, and text-to-speech, all on a single GB10.

![Demo](demo.png)

**Highlights**
- **Single joint model**: Qwen3.6-35B-A3B handles text, vision, and reasoning (no separate VLM/reasoner)
- **Ultra-low latency**: ~300ms voice turns, ~900ms video turns (warm, GB10), 80-90 tok/s for code and LLM generation
- **Fully local**: llama.cpp on host, Whisper ASR, Kokoro TTS — no cloud dependencies
- **Agentic**: streaming multi-turn tool-call loop (filesystem, Python sandbox, web search, memory)
- **Face recognition**: DeepFace enrollment + identification in video-call mode

## Quick Start

**Prerequisites:** DGX Spark (GB10) with CUDA 13, Python 3.10+, `git`, `ffmpeg`, `jq`, and a C++ build toolchain. A [Hugging Face account](https://huggingface.co) with a token, and a [Discord account](https://discord.com).

```bash
git clone https://github.com/sewilliams-ai/spark-realtime-chatbot.git
cd spark-realtime-chatbot
./setup.sh
```

The script will walk you through configuration (including creating your own Discord bot and printing a personalized invite link), download models, build dependencies, and launch all three servers. Open https://localhost:8443 when it finishes.

To stop everything later — keeping models and builds intact — run `./stop.sh`. Re-running `./setup.sh` is safe; it skips already-completed steps.

For troubleshooting, FAQs, and Ollama backend instructions, see [SETUP.md](SETUP.md).

---

## Configuration

All defaults live in `config.py` and can be overridden via environment variables.

| Variable | Default | Description |
|---|---|---|
| `LLM_SERVER_URL` | `http://localhost:30000/v1/chat/completions` | OpenAI-compatible endpoint (llama.cpp) |
| `LLM_MODEL` | `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` | Same model for text + vision |
| `LLM_REASONING_EFFORT` | `none` | `none` / `low` / `high` — `none` gates out `<think>` on the voice path |
| `VLM_SERVER_URL` / `VLM_MODEL` | same as LLM | Vision shares the model |
| `REASONING_EFFORT` | `high` | For the deep-reasoning agent tool only |
| `ASR_MODE` | `api` | `api` (separate whisper server) or `local` (in-process) |
| `ASR_MODEL` | `Systran/faster-whisper-small.en` | Whisper model |
| `KOKORO_VOICE` | `af_bella` | TTS voice (Kokoro only) |
| `TTS_ENGINE` | `kokoro` | `kokoro` (default) or `chatterbox` (experimental; see bench above) |
| `TTS_DEVICE` | `cuda` | `cuda` (default, ~70× realtime on GB10 with torch cu130) or `cpu` |
| `TTS_OVERLAP` | `false` | Start TTS while LLM still streaming |

---

## Architecture

```
Browser ──► FastAPI (server.py) ──► llama.cpp :30000  (Qwen3.6-35B-A3B)
                │
                ├── ASR      (faster-whisper, local or API)
                ├── TTS      (Kokoro)
                ├── Face     (DeepFace)
                └── Tools    (read/write_file, run_python, web_search, memory, agents)
```

**Agent loop.** When Qwen3.6 emits tool calls, the server executes them (in parallel for ≥2 calls), appends the `tool_result` messages, and re-streams the model until no more tool calls are emitted, capped at 4 iterations. TTS announces *"working on it…"* immediately when a long-running tool fires; a user barge-in cancels the in-flight generation.

**Single model for everything.** The December 2025 demo used one llama.cpp server for Qwen3-VL and another for Nemotron reasoning. This upgrade collapses both onto one Qwen3.6-35B-A3B process: 3B active parameters, Q4_K_M, ~24 GB resident. Text turns run with `reasoning_effort=none` for realtime TTFT; the reasoning agent flips to `effort=high` for deliberate analysis.

Key files:
- `server.py` — FastAPI WS handlers, voice/video paths, tool-call loop
- `clients/llm.py` — `LlamaCppClient` (OpenAI-compat streaming) + `ReasoningClient`
- `clients/vlm.py` — vision helper, same backend
- `clients/asr.py`, `clients/tts.py`, `clients/face.py` — supporting services
- `tools.py` — tool schema + execution
- `prompts.py` — system prompts (voice, video, reasoning variants)
- `static/` — frontend

---

## Usage

1. **Connect**: the app auto-connects on load.
2. **Choose Mode**: voice call or video call.
3. **Voice Input**: hands-free with VAD, or hold SPACE for push-to-talk.
4. **Enable Tools**: check agents in the sidebar; the LLM can now call them.
5. **Face Recognition**: in video mode, say *"remember my face as <name>"*.

### Things to try

- **Sketch → Frontend**: draw a frontend sketch, show it in video mode, say "convert this into a markdown README."*
- **Architecture review**: show a diagram, ask "what's missing from this design?"
- **Menu Translation & Recommendation for Personalized Health Recommendations**: "what should I order based on this menu?"*
- **Face recognition**: say "remember my face as Alex," end the call, start a new one — the bot greets you by name.

\* Currently tuned for a chip selection agent and high blood pressure based on mock demo data, users can configure with personalized data for richer results.

---

## Acknowledgements

- [Kedar's Original Repo](https://github.com/kedarpotdar-nv/spark-realtime-chatbot) - original demo with similar core functionality
- [llama.cpp](https://github.com/ggml-org/llama.cpp) — local model serving
- [Qwen3.6](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) — joint VL + reasoning (Alibaba)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — ASR
- [Kokoro](https://github.com/hexgrad/kokoro) — TTS
- [DeepFace](https://github.com/serengil/deepface) — face recognition
- [Silero VAD](https://github.com/ricky0123/vad) — voice activity detection
- NVIDIA Marketing Team: Thank you for your feedback during demo devlepment