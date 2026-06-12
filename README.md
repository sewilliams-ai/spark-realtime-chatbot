# spark-realtime-chatbot

A voice + vision AI assistant running locally on DGX Spark — streaming speech recognition, a single joint vision-language-reasoning model, and text-to-speech, all on a single GB10.

![Demo](demo.png)

**Highlights**
- **Single joint model**: Qwen3.6-35B-A3B handles text, vision, and reasoning (no separate VLM/reasoner)
- **Ultra-low latency**: ~300ms voice turns, ~900ms video turns (warm, GB10)
- **Fully local**: llama.cpp on host, Whisper ASR, Kokoro TTS — no cloud dependencies
- **Agentic**: streaming multi-turn tool-call loop (filesystem, Python sandbox, web search, memory)
- **Face recognition**: DeepFace enrollment + identification in video-call mode

**Benchmarked on DGX Spark (warm, Q4_K_M Qwen3.6-35B-A3B via llama.cpp, N=5)**

| Path | TTFT (median) | End-to-end (median) |
|------|---------------|---------------------|
| Voice turn (effort=none) | ~225 ms | ~365 ms |
| Video turn (image+text, effort=none) | ~880 ms | ~1340 ms |
| Tool-call roundtrip (1 tool declared) | ~840 ms | ~840 ms |
| Agent loop (LLM → run_python → LLM) | ~1550 ms | ~1860 ms |
| Reasoning turn (effort=high, ~4k chars thinking) | — | ~20 s |

Reproduce:
```
python3 bench/bench.py --trials 5 --out bench/after.json
python3 bench/diff.py bench/baseline.json bench/after.json
python3 bench/test_tools.py        # e2e smoke for every inline tool
python3 bench/test_agent_loop.py   # e2e parallel-dispatch / math / memory
```

**Full-stack end-to-end** (WebSocket `text_message` → Qwen3.6 → Kokoro TTS → audio, warm):

| | Total |
|--|--|
| text → final_response text → first TTS chunk | **~1.1 s** |

Reproduce:
```
docker build -f bench/Dockerfile.tts -t realtime2-tts .
docker run -d --gpus all --network host --ipc=host \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -v $(pwd):/workspace/realtime2 -w /workspace/realtime2 \
  --name rt2 realtime2-tts \
  uvicorn server:app --host 0.0.0.0 --port 8453
docker exec rt2 python bench/test_ws_text.py --url ws://localhost:8453/ws/voice \
  --text "What is 2+2 in one word?"
```

**TTS backend benchmark** (GB10, N=3 per sentence, torch 2.11 + CUDA 13.0 wheels):

| Sentence length | Kokoro **CUDA** TTFT | Kokoro CPU TTFT | Chatterbox CUDA TTFT |
|---|---|---|---|
| 15 chars | **39 ms** | 476 ms | 793 ms |
| 31 chars | **42 ms** | 783 ms | 1134 ms |
| 81 chars | **78 ms** | 1224 ms | 2148 ms |
| 189 chars | **158 ms** | 2098 ms | 4741 ms |

Kokoro CUDA runs at RTF ~0.015 (≈ 65× realtime) on GB10 when torch uses the **cu130** wheels — the cu128 wheels ship without sm_121/sm_120 kernels and fall back to torch nvrtc JIT, which crashes on Blackwell. `TTS_DEVICE=cuda` is the default. Chatterbox-Turbo sounds better subjectively but is 2–3× slower per utterance and has no native streaming — kept as an opt-in backend via `TTS_ENGINE=chatterbox`.

Bench harness:
```
docker build -f bench/Dockerfile.tts -t realtime2-tts .
docker run --rm --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -v $(pwd):/workspace/realtime2 -w /workspace/realtime2 \
  realtime2-tts python bench/bench_tts.py --trials 3 --out bench/tts.json
```

---

## Quick Start

Two processes run side by side: a **llama.cpp** model server (`:30000`) and the **HTTPS frontend** (`:8443`); a **Discord bot** is optional. This is the condensed path — for the full walkthrough (building llama.cpp, Discord bot setup, vLLM alternative), see **[docs/setup-guide.md](docs/setup-guide.md)**.

### Prerequisites

- **DGX Spark (GB10)** with the **CUDA 13 toolchain + driver** (`nvcc --version` works), **Python 3.10+**, and `git`, `ffmpeg`, `jq`, plus a C++ build toolchain (`cmake`, `make`, a compiler) for building llama.cpp and the local-ASR CTranslate2.
- The **Hugging Face CLI** (provides the `hf` command used below):
  ```bash
  pipx install huggingface_hub   # PEP 668-safe; run `sudo apt install pipx` first if needed
  ```

### 1. Serve Qwen3.6 with llama.cpp

Build [llama.cpp](https://github.com/ggml-org/llama.cpp) from source, then download the GGUF models and start `llama-server` with speculative decoding. `hf download --quiet` prints just the local cache path (downloading first if needed), so we capture it instead of hardcoding snapshot paths.

```bash
MODEL=$(hf download --quiet unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q4_K_M.gguf)
MMPROJ=$(hf download --quiet unsloth/Qwen3.6-35B-A3B-GGUF mmproj-BF16.gguf)
DRAFT=$(hf download --quiet unsloth/Qwen3.5-0.8B-GGUF Qwen3.5-0.8B-Q4_K_M.gguf)

~/llama.cpp/build/bin/llama-server \
  --model "$MODEL" --mmproj "$MMPROJ" -md "$DRAFT" \
  --host 0.0.0.0 --port 30000 --n-gpu-layers 99 --ctx-size 16384 \
  --spec-draft-ngl 99 --spec-draft-n-max 16 --spec-draft-n-min 0 --spec-draft-p-min 0.75 \
  --chat-template-kwargs '{"enable_thinking": false}' --threads 8
```

> **Keep `--ctx-size` ≥ 16384** — the html_assistant needs it; llama.cpp's 4096 default silently truncates.

Sanity check:
```bash
curl -s http://localhost:30000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3.6-35B-A3B-UD-Q4_K_M.gguf","messages":[{"role":"user","content":"hi"}],"max_tokens":20,"reasoning_effort":"none"}' | jq .
```

### 2. Run the HTTPS frontend

```bash
git clone https://github.com/sewilliams-ai/spark-realtime-chatbot.git
cd spark-realtime-chatbot
python3 -m venv venv && source venv/bin/activate
./setup.sh                    # CUDA CTranslate2 (local ASR) + requirements
./launch-https.sh --local-asr
```

Defaults already point at the llama.cpp backend on `:30000`, so **no environment variables are needed**. Open **https://localhost:8443**, accept the self-signed cert, and allow the microphone.

### 3. (Optional) Discord bot

```bash
export DISCORD_BOT_TOKEN=<your-bot-token>
source venv/bin/activate && python3 clients/discord-bot.py
```

See [docs/setup-guide.md](docs/setup-guide.md) for creating your own bot.

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

- **Whiteboard → README**: draw a system diagram, show it in video mode, say "convert this into a markdown README."
- **Architecture review**: show a diagram, ask "what's missing from this design?"
- **Fashion advisor**: "am I dressed appropriately for a board meeting?"
- **Face recognition**: say "remember my face as Alex," end the call, start a new one — the bot greets you by name.

---

## Acknowledgements

- [llama.cpp](https://github.com/ggml-org/llama.cpp) — local model serving
- [Qwen3.6](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) — joint VL + reasoning (Alibaba)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — ASR
- [Kokoro](https://github.com/hexgrad/kokoro) — TTS
- [DeepFace](https://github.com/serengil/deepface) — face recognition
- [Silero VAD](https://github.com/ricky0123/vad) — voice activity detection
