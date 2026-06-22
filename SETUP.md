# Detailed Setup

`./setup.sh` (see the [README](README.md#quick-start)) automates everything on
this page: it walks you through configuration, downloads the models, builds the
CUDA dependencies, and launches all three servers. This document is the manual
fallback and reference — useful if you want to run a single step by hand, debug
a failure, or run a different backend.

## Overview

While running, the demo has three servers:

1. A **llama.cpp server** (`:30000`) which serves the local model
2. An **HTTPS server** (`:8443`) which serves the frontend
3. A **Discord bot server** which lets a user talk to the AI backend on Discord

Manual setup mirrors what `setup.sh` does:

- **Part 1.** Set up the llama.cpp server — download HF models, build llama.cpp, run the server
- **Part 2.** Set up the demo repo — install dependencies, run the HTTPS server
- **Part 3.** Set up Discord — create your own server + bot, invite it (setup.sh prints a personalized URL), run the bot

## Prerequisites

- **DGX Spark (GB10)** with the **CUDA 13 toolchain + driver** (`nvcc --version` works), **Python 3.10+**, and `git`, `ffmpeg`, `jq`, plus a C++ build toolchain (`cmake`, `make`, a compiler) for building llama.cpp and the local-ASR CTranslate2.
- The **Hugging Face CLI** (provides the `hf` command used below):
  ```bash
  pipx install huggingface_hub   # PEP 668-safe; run `sudo apt install pipx` first if needed
  ```
- A [Hugging Face account](https://huggingface.co) with a token, and a [Discord account](https://discord.com).

---

## Part 1. Set up the llama.cpp server

### Download the Qwen3.6 HF GGUF models

```bash
hf download unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q4_K_M.gguf && \
hf download unsloth/Qwen3.6-35B-A3B-GGUF mmproj-BF16.gguf && \
hf download unsloth/Qwen3.5-0.8B-GGUF Qwen3.5-0.8B-Q4_K_M.gguf
```

### Install llama.cpp by building from source

Pin a commit with multi-token prediction support rather than building `HEAD`.
`setup.sh` pins [`255582687b8dd211fdbc582e43ab842491554e94`](https://github.com/ggml-org/llama.cpp/commit/255582687b8dd211fdbc582e43ab842491554e94)
(the merge of [ggml-org/llama.cpp#22673](https://github.com/ggml-org/llama.cpp/pull/22673),
"llama + spec: MTP Support", merged 2026-05-16):

```bash
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
git checkout 255582687b8dd211fdbc582e43ab842491554e94
cmake -S . -B build -DGGML_CUDA=ON
cmake --build build --config Release -j --target llama-server
cd ..
```

See https://github.com/ggml-org/llama.cpp and its `docs/` for full build options.

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

This setup is portable: each developer creates **their own** server and **their own** bot. Nothing here hardcodes a specific server or bot — `setup.sh` derives everything from the token you paste.

### Create your own Discord server

Go to https://discord.com/channels/@me, click **Add a Server** (the **+** in the left sidebar), and choose **Create My Own** → **For me and my friends**. You'll invite your bot here, so you need a server where you have **Manage Server** permission — your own server gives you that.

### Create your own Discord bot

Each developer runs their **own** bot — sharing a token causes the bot to send duplicate responses (see FAQ) and is a security risk. These steps are browser-only and cannot be scripted.

1. Visit https://discord.com/developers/applications and click **New Application**.
2. Open the **Bot** tab — a bot user is created automatically with the application.
3. Under **Token**, click **Reset Token** and copy the new token. (You can only view it once.) You'll paste it into `setup.sh`.
4. In the **Bot** tab under **Privileged Gateway Intents**, enable **Message Content Intent**, then **Save Changes**. **Required:** the bot reads message text; without this toggle it crashes on startup with `PrivilegedIntentsRequired`. It's free to enable for bots in fewer than 100 servers.
5. In the **Bot** tab under **Bot Permissions**, enable **Send Messages**.

You do **not** need the OAuth2 URL Generator. When you paste the token, `setup.sh` validates it, derives your bot's client ID, and prints a personalized invite URL with exactly the permissions this bot needs (View Channels + Send Messages + Read Message History).

### Add your bot to your server

1. `setup.sh` prints an invite URL like:
   ```
   https://discord.com/oauth2/authorize?client_id=<your-bot>&permissions=68608&scope=bot
   ```
   (To build it by hand instead: take your **Application ID** from the **General Information** tab and substitute it for `<your-bot>`.)
2. Open the URL, select the server you created above, click **Authorize**, and finish the captcha.
3. Send the bot a message in that server to confirm it replies. The `--- [guilds] ...` line in `logs/discord.log` lists which servers the bot joined.

### Run the Discord bot server (manual)

```bash
# cd path/to/spark-realtime-chatbot
DISCORD_BOT_TOKEN=<TOKEN HERE>

source venv/bin/activate && \
python3 clients/discord-bot.py
```

Send a sample message to the bot in your Discord server to confirm it responds.

---

## Stopping and restarting

Stop all three servers without deleting any artifacts — downloaded models, the venv, and the llama.cpp build are left intact:

```bash
./stop.sh
```

It stops the processes recorded in `logs/*.pid` (falling back to matching by listening port / process name). To restart, just run `./setup.sh` again.

`setup.sh` is **idempotent** — re-running it is safe:

- The venv, llama.cpp build, and downloaded models are reused if already present (no re-download, no rebuild).
- `pip install -r requirements.txt` re-runs, but is a fast no-op once dependencies are satisfied.
- Each server is skipped if it's already up (port already listening, or the bot process already running), so re-running won't spawn duplicates.

---

## Troubleshooting

- **`--ctx-size` too small** — keep llama.cpp's `--ctx-size` at 16384 or higher. The default (4096) silently truncates long prompts and destabilizes generation.
- **Server didn't come up** — `setup.sh` writes per-server logs to `logs/llama.log`, `logs/https.log`, and `logs/discord.log`. Check those first.
- **Discord bot crashes instantly / missing from `nvidia-smi` / never replies** — almost always **Message Content Intent** is not enabled in the Developer Portal; the log shows `PrivilegedIntentsRequired`. Enable it (Bot tab → Privileged Gateway Intents → Message Content Intent → Save Changes) and restart. No token reset is needed.
- **Bot is online but silent in one server** — a bot only receives messages from servers it has been *invited* to. Re-open the invite URL `setup.sh` printed and authorize the bot into that specific server. The `--- [guilds] ...` line in `logs/discord.log` shows which servers it actually joined.
- **Self-signed certificate warning** — expected on first load of https://localhost:8443. Accept it in the browser.
- **Microphone blocked** — the browser must be granted microphone access; reload and allow when prompted.

## FAQ

- **The bot replies twice in Discord.** Two bot instances are connected with the same token. Each developer should create and run their own bot (Part 3) rather than sharing a token.
- **Do I need a GPU build of CTranslate2?** Only for local ASR (`--local-asr`). `setup.sh` builds it CUDA-enabled for GB10 (`sm_121`).

## Running with Ollama (simpler backend)

llama.cpp is the default and recommended backend. If you prefer Ollama for a
simpler model-serving setup, point the demo at an OpenAI-compatible Ollama
endpoint via the environment variables documented in the
[Configuration](README.md#configuration) table (`LLM_SERVER_URL`, `LLM_MODEL`,
and the matching `VLM_*` / `REASONING_*` / `HTML_*` variables). Note that
speculative decoding and the multi-token-prediction draft model are
llama.cpp-specific and won't apply to an Ollama backend.
