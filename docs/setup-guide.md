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

`hf download` prints the local cache path for each file, so capture those into variables instead of hardcoding snapshot-hash paths (the hash changes whenever a model is re-downloaded). If a file is already downloaded, this just prints its path — no re-download.

```bash
MODEL=$(hf download unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q4_K_M.gguf)
MMPROJ=$(hf download unsloth/Qwen3.6-35B-A3B-GGUF mmproj-BF16.gguf)
DRAFT=$(hf download unsloth/Qwen3.5-0.8B-GGUF Qwen3.5-0.8B-Q4_K_M.gguf)

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

### Create your own Discord bot

Each developer should run their own bot — sharing a token causes the bot to send duplicate responses (see FAQ) and is a security risk.

1. Visit https://discord.com/developers/applications and click **New Application**.
2. In your application, go to the **Bot** tab and click **Add Bot**.
3. Under **Token**, click **Reset Token** and copy the new token. (You can only view it once — save it somewhere safe.)
4. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
5. Go to **OAuth2 → URL Generator**. Select scopes: `bot`. Select bot permissions: `Send Messages`, `Read Message History`. Copy the generated URL.
6. Open the URL in a browser and invite the bot to a Discord server where you have **Manage Server** permission (typically your own test server).

### (Optional) Join the community Discord server

To chat alongside the team:

https://discord.gg/PbHDZVMT

This invite only adds you as a user — it does not let you add bots to that server.

### Set the bot token as an env variable

Add to `~/.bashrc` (or export per-session):

```bash
export DISCORD_BOT_TOKEN=<your-discord-bot-token>
```

### Run the Discord bot server

```bash
# cd path/to/spark-realtime-chatbot
source venv/bin/activate && \
python3 clients/discord-bot.py
```

Send a sample message to the bot in your Discord server to confirm it responds.

---

## FAQs / Gotchas

**Q: The Discord bot sends two responses.**
A: That means two instances of the bot are running with the same token — one on this device, one elsewhere. Stop the duplicate (e.g. `pkill -f discord-bot.py` on the other machine) and rerun. Long-term fix: each developer should use their own bot token, not a shared one.

---

## Issues or feedback?

Slack Selena Williams US (`sewilliams`) or text +1 702-503-3462 for urgent issues.

---

## Appendix: Running via vLLM instead of llama.cpp

```bash
# B12x env vars
export VLLM_NVFP4_GEMM_BACKEND=flashinfer-b12x
export VLLM_USE_FLASHINFER_MOE_FP4=1
export VLLM_FP8_MOE_BACKEND=flashinfer_cutlass   # route FP8 experts via cutlass; b12x is FP4-only
export FLASHINFER_DISABLE_VERSION_CHECK=1
export CUTE_DSL_ARCH=sm_121a                     # Spark GB10
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

vllm serve nvidia/Qwen3.6-35B-A3B-2.06GB-per-token \
    --host 0.0.0.0 --port 30000 \
    --tensor-parallel-size 1 --trust-remote-code --dtype auto \
    --kv-cache-dtype fp8 --attention-backend FLASHINFER \
    --gpu-memory-utilization 0.85 --max-model-len 65536 \
    --max-num-seqs 4 --max-num-batched-tokens 8192 \
    --enable-chunked-prefill --async-scheduling \
    --moe-backend=flashinfer_b12x --quantization=modelopt \
    --enable-prefix-caching \
    --reasoning-parser qwen3 \
    --compilation-config '{"pass_config":{"fuse_norm_quant":true,"fuse_act_quant":true,"fuse_attn_quant":false}}' \
    --speculative-config '{"method":"mtp","num_speculative_tokens":3,"rejection_sample_method":"synthetic","synthetic_acceptance_length":3.12,"moe_backend":"triton"}'
```

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
