# Setup Guide

## Overview

Setting up this demo has a few components. While running the demo, three servers are running:

1. A **llama.cpp server** which serves the local model
2. An **HTTPS server** which serves the frontend
3. A **Discord bot server** which enables a user to talk to the AI backend on Discord

Setup steps:

- **Part 1.** Set up the llama.cpp server
  - Download HF models
  - Download (and build) llama.cpp
  - Run the llama.cpp server
- **Part 2.** Set up the demo repo
  - Clone the demo repo
  - Run the HTTPS server
- **Part 3.** Set up Discord
  - Create your own Discord bot
  - Join the community Discord server (optional)
  - Run the Discord bot server
  - Send a sample message to the bot in Discord

---

## Prerequisites

Before you begin, make sure the host has:

- **DGX Spark (GB10)** with the **CUDA 13 toolchain and driver** installed (`nvcc --version` works).
- **Python 3.10+** and `git`.
- System packages: `ffmpeg` (audio decoding — the server checks for it at startup), `jq` (used by the sanity check), and a C++ build toolchain (`cmake`, `make`, a compiler) for building CTranslate2 and llama.cpp.
- The **Hugging Face CLI**, which provides the `hf` command used to download models:
  ```bash
  pipx install huggingface_hub   # PEP 668-safe; run `sudo apt install pipx` first if needed
  ```

---

## Part 1. Set up the llama.cpp server

### Download the Qwen3.6 HF GGUF models

```bash
hf download unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q4_K_M.gguf && \
hf download unsloth/Qwen3.6-35B-A3B-GGUF mmproj-BF16.gguf && \
hf download unsloth/Qwen3.5-0.8B-GGUF Qwen3.5-0.8B-Q4_K_M.gguf
```

### Install llama.cpp by building from source

```bash
git clone https://github.com/ggml-org/llama.cpp.git
```

Visit https://github.com/ggml-org/llama.cpp and follow the README and `docs/` for build instructions.

### Start the llama.cpp server with Qwen3.6 and speculative decoding

`hf download --quiet` prints just the local cache path for each file, so capture those into variables instead of hardcoding snapshot-hash paths (the hash changes whenever a model is re-downloaded). If a file is already downloaded, this just prints its path — no re-download. (Without `--quiet`, the CLI prints a decorated `✓ Downloaded … path:` message that would pollute the captured variable.)

```bash
MODEL=$(hf download --quiet unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q4_K_M.gguf)
MMPROJ=$(hf download --quiet unsloth/Qwen3.6-35B-A3B-GGUF mmproj-BF16.gguf)
DRAFT=$(hf download --quiet unsloth/Qwen3.5-0.8B-GGUF Qwen3.5-0.8B-Q4_K_M.gguf)

cd ~/llama.cpp && \
./build/bin/llama-server \
  --model "$MODEL" \
  --mmproj "$MMPROJ" \
  -md "$DRAFT" \
  --spec-draft-ngl 99 \
  --spec-draft-n-max 16 \
  --spec-draft-n-min 0 \
  --spec-draft-p-min 0.75 \
  --host 0.0.0.0 \
  --port 30000 \
  --n-gpu-layers 99 \
  --ctx-size 16384 \
  --chat-template-kwargs '{"enable_thinking": false}' \
  --threads 8
```

> **Important: keep `--ctx-size` at 16384 or higher.** The html_assistant needs ≥16k of context; llama.cpp's default (4096) silently truncates long prompts and destabilizes generation.

---

## Part 2. Set up the demo repo and run the HTTPS server

### Clone the demo repo and install dependencies

```bash
git clone https://github.com/sewilliams-ai/spark-realtime-chatbot.git
cd spark-realtime-chatbot
python3 -m venv venv && source venv/bin/activate
./setup.sh   # builds CUDA-enabled CTranslate2 (for local ASR) + installs requirements
```

### Launch the HTTPS server

The defaults in `launch-https.sh` and `config.py` already point at the llama.cpp backend (`localhost:30000`, `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`), so no environment variables are needed.

```bash
source venv/bin/activate && \
./launch-https.sh --local-asr
```

Then open **https://localhost:8443**, accept the self-signed certificate, and allow the microphone.

---

## Part 3. Set up Discord

### Create your own Discord server

In the Discord app, click the **+** in the server list and choose **Create My Own** → **For me and my friends**. You'll invite your bot here, so you need a server where you have **Manage Server** permission — your own server gives you that. For step-by-step help, see Discord's [How do I create a server?](https://support.discord.com/hc/en-us/articles/204849977-How-do-I-create-a-server).

### Create your own Discord bot

Each developer should run their own bot — sharing a token causes the bot to send duplicate responses (see FAQ) and is a security risk.

1. Visit https://discord.com/developers/applications and click **New Application**.
2. In your application, open the **Bot** tab — a bot user is created automatically with the application.
3. Under **Token**, click **Reset Token** and copy the new token. (You can only view it once — save it somewhere safe.)
4. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
5. Go to **OAuth2 → URL Generator**. Select scopes: `bot`. Select bot permissions: `View Channels`, `Send Messages`, `Read Message History`. Copy the generated URL.
6. Complete the installation instructions at [this youtube video (00:2:57)](https://youtu.be/hpegsgOmjgs?si=eNTFtz1l3MHdwoOh). Instead of saving the TOKEN in a .env file, save it as an environment variable (`DISCORD_BOT_TOKEN`), which we'll cover below. 

### Run the Discord bot server

```bash
# cd path/to/spark-realtime-chatbot
DISCORD_BOT_TOKEN=<TOKEN HERE>

source venv/bin/activate && \
python3 clients/discord-bot.py
```

Send a sample message to the bot in your Discord server to confirm it responds.

---

## FAQs / Gotchas

**Q: The Discord bot sends two responses.**
**A:** That means two instances of the bot are running with the same token — one on this device, one elsewhere. Stop the duplicate (e.g. `pkill -f discord-bot.py` on the other machine) and rerun. Long-term fix: each developer should use their own bot token, not a shared one.

**Q: Discord bot says integration requires code grant when joining the server.**
**A**: If you are receiving an "Integration requires code grant" error when trying to invite your Discord bot, it means the bot's settings are incorrectly configured. You can fix this instantly by turning off the OAuth2 Code Grant option in your application settings.

---

## Issues, feedback, contributions

Please feel free to raise a github issue or PR. 

---

## Appendix: Running via Ollama instead of llama.cpp

Ollama is the simplest backend to stand up — no building from source, no manual GGUF paths — but it does not use the tuned speculative-decoding config above. Since the defaults now expect llama.cpp on `:30000`, point the app at Ollama's `:11434` with env vars.

```bash
# Install Ollama (if needed): https://ollama.com/download
ollama pull qwen3.6:35b-a3b
ollama serve   # serves http://localhost:11434

# Launch the frontend pointed at Ollama:
source venv/bin/activate && \
LLM_SERVER_URL=http://localhost:11434/v1/chat/completions \
VLM_SERVER_URL=http://localhost:11434/v1/chat/completions \
REASONING_SERVER_URL=http://localhost:11434/v1/chat/completions \
HTML_SERVER_URL=http://localhost:11434/v1/chat/completions \
LLM_MODEL=qwen3.6:35b-a3b VLM_MODEL=qwen3.6:35b-a3b \
HTML_MODEL=qwen3.6:35b-a3b REASONING_MODEL=qwen3.6:35b-a3b \
./launch-https.sh --local-asr
```
