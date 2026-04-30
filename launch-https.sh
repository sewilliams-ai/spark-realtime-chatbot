#!/bin/bash
# Launch script for spark-realtime-chatbot

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer the local CUDA-ready environment when it exists. This keeps the demo
# path off the host/user Python, which may have CPU-only torch/ctranslate2.
if [ -d "$SCRIPT_DIR/.venv-gpu" ]; then
    export VIRTUAL_ENV="$SCRIPT_DIR/.venv-gpu"
    export PATH="$VIRTUAL_ENV/bin:$PATH"
    export LD_LIBRARY_PATH="$VIRTUAL_ENV/lib:${LD_LIBRARY_PATH:-}"
fi

if [ -z "${FFMPEG_PATH:-}" ]; then
    if command -v ffmpeg >/dev/null 2>&1; then
        export FFMPEG_PATH="$(command -v ffmpeg)"
    else
        IMAGEIO_FFMPEG="$(
            python - <<'PY' 2>/dev/null
try:
    import imageio_ffmpeg
except Exception:
    raise SystemExit(0)

print(imageio_ffmpeg.get_ffmpeg_exe())
PY
        )"
        if [ -n "$IMAGEIO_FFMPEG" ] && [ -x "$IMAGEIO_FFMPEG" ]; then
            export FFMPEG_PATH="$IMAGEIO_FFMPEG"
        fi
    fi
fi

# Default configuration - override with environment variables
export ASR_MODE="${ASR_MODE:-api}"  # "api" for server, "local" for in-process
export ASR_API_URL="${ASR_API_URL:-http://localhost:8000/v1/audio/transcriptions}"
export ASR_API_KEY="${ASR_API_KEY:-dummy-key}"
export ASR_MODEL="${ASR_MODEL:-Systran/faster-whisper-small.en}"
export ASR_DEVICE="${ASR_DEVICE:-cuda}"
export ASR_COMPUTE_TYPE="${ASR_COMPUTE_TYPE:-float16}"

# Unified model — Qwen3.6-35B-A3B (vision + text + reasoning) served by Ollama
export LLM_SERVER_URL="${LLM_SERVER_URL:-http://localhost:11434/v1/chat/completions}"
export LLM_MODEL="${LLM_MODEL:-qwen3.6:35b-a3b}"
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-4096}"
export LLM_REASONING_EFFORT="${LLM_REASONING_EFFORT:-none}"  # "none" = no <think>, fastest voice path

# VLM shares the same endpoint and model
export VLM_SERVER_URL="${VLM_SERVER_URL:-http://localhost:11434/v1/chat/completions}"
export VLM_MODEL="${VLM_MODEL:-qwen3.6:35b-a3b}"
export VLM_MAX_TOKENS="${VLM_MAX_TOKENS:-150}"
export VLM_REASONING_EFFORT="${VLM_REASONING_EFFORT:-none}"

# Deep-reasoning agent uses the same model with reasoning_effort=high
export REASONING_SERVER_URL="${REASONING_SERVER_URL:-http://localhost:11434/v1/chat/completions}"
export REASONING_MODEL="${REASONING_MODEL:-qwen3.6:35b-a3b}"
export REASONING_EFFORT="${REASONING_EFFORT:-high}"

export TTS_ENGINE="${TTS_ENGINE:-kokoro}"         # kokoro | chatterbox
export TTS_DEVICE="${TTS_DEVICE:-cuda}"           # cuda (default, 70× RT on GB10 w/ cu130) | cpu
export KOKORO_LANG="${KOKORO_LANG:-a}"
export KOKORO_VOICE="${KOKORO_VOICE:-af_bella}"
export TTS_OVERLAP="${TTS_OVERLAP:-false}"  # Overlap TTS with LLM streaming
export UVICORN_RELOAD="${UVICORN_RELOAD:-false}"

# HuggingFace cache directory (defaults to /home/nvidia/hfcache if not set)
# Set HF_HOME to override the default ~/.cache/huggingface location
export HF_HOME="${HF_HOME:-/home/nvidia/hfcache}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}"
# Create cache directory if it doesn't exist
mkdir -p "$HUGGINGFACE_HUB_CACHE"

# Parse command line flags before printing the effective configuration.
for arg in "$@"; do
    case $arg in
        --local-asr)
            export ASR_MODE="local"
            ;;
        --tts-overlap)
            export TTS_OVERLAP="true"
            ;;
        --trtllm)
            export LLM_BACKEND="trtllm"
            ;;
        --dev|--reload)
            export UVICORN_RELOAD="true"
            ;;
    esac
done

# SSL certificate paths
SSL_KEY="${SSL_KEY:-key.pem}"
SSL_CERT="${SSL_CERT:-cert.pem}"

# Port for HTTPS server (default 8443)
PORT="${PORT:-8443}"

# Check if certificates exist
if [ ! -f "$SSL_KEY" ] || [ ! -f "$SSL_CERT" ]; then
    echo "=========================================="
    echo "SSL certificates not found!"
    echo "=========================================="
    echo "Generating self-signed certificate..."
    echo ""
    openssl req -x509 -newkey rsa:4096 \
        -keyout "$SSL_KEY" -out "$SSL_CERT" \
        -days 365 -nodes \
        -subj "/CN=localhost" 2>/dev/null
    
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to generate certificates. Install openssl or provide certificates manually."
        echo ""
        echo "To generate manually:"
        echo "  openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes"
        exit 1
    fi
    echo "✅ Certificates generated: $SSL_KEY, $SSL_CERT"
    echo ""
fi

echo "=========================================="
echo "Launching spark-realtime-chatbot (HTTPS)"
echo "=========================================="
echo "ASR Mode: $ASR_MODE"
if [ "$ASR_MODE" == "local" ]; then
    echo "ASR Device: $ASR_DEVICE"
    echo "ASR Compute Type: $ASR_COMPUTE_TYPE"
else
    echo "ASR API URL: $ASR_API_URL"
fi
echo "ASR Model: $ASR_MODEL"
echo "LLM URL: $LLM_SERVER_URL"
echo "LLM Model: $LLM_MODEL"
echo "LLM Max Tokens: $LLM_MAX_TOKENS"
echo "VLM URL: $VLM_SERVER_URL"
echo "VLM Model: $VLM_MODEL"
echo "VLM Max Tokens: $VLM_MAX_TOKENS"
echo "TTS Overlap: $TTS_OVERLAP"
echo "Dev Reload: $UVICORN_RELOAD"
echo "HF Cache: $HUGGINGFACE_HUB_CACHE"
echo "Port: $PORT (HTTPS)"
echo "SSL Key: $SSL_KEY"
echo "SSL Cert: $SSL_CERT"
echo "FFmpeg: ${FFMPEG_PATH:-ffmpeg}"
echo "=========================================="
echo ""
echo "⚠️  Note: If using self-signed certificate,"
echo "   you'll need to accept browser security warning"
echo ""

for arg in "$@"; do
    case $arg in
        --local-asr)
            echo "✅ Local ASR enabled (in-process faster-whisper)"
            ;;
        --tts-overlap)
            echo "✅ TTS/LLM overlap enabled (parallel TTS generation)"
            ;;
        --trtllm)
            echo "✅ TensorRT-LLM backend enabled"
            ;;
        --dev|--reload)
            echo "✅ Uvicorn reload enabled"
            ;;
    esac
done

if ! command -v uvicorn >/dev/null 2>&1; then
    echo "ERROR: uvicorn not found. Activate the virtualenv and install dependencies first:"
    echo "  source venv/bin/activate"
    echo "  pip install -r requirements.txt"
    exit 1
fi

if [ "$ASR_MODE" == "local" ]; then
    python - <<'PY'
import os
import sys

try:
    import ctranslate2
    import faster_whisper  # noqa: F401
except ModuleNotFoundError as exc:
    print(f"ERROR: local ASR dependency missing: {exc.name}")
    print("Install dependencies with: pip install -r requirements.txt")
    sys.exit(1)

if os.getenv("ASR_DEVICE", "cuda") == "cuda":
    try:
        cuda_types = ctranslate2.get_supported_compute_types("cuda")
    except Exception as exc:
        print(f"ERROR: CTranslate2 CUDA unavailable ({exc}).")
        print("Local ASR was requested on CUDA, so refusing to start on CPU.")
        sys.exit(1)
    else:
        if "float16" not in cuda_types:
            print(f"ERROR: CTranslate2 CUDA compute types are {cuda_types}; expected float16.")
            print("Local ASR was requested on CUDA, so refusing to start on CPU.")
            sys.exit(1)
        print(f"✅ CTranslate2 CUDA compute types: {sorted(cuda_types)}")
PY
fi

if [ "$TTS_DEVICE" == "cuda" ]; then
    python - <<'PY'
import sys

try:
    import torch
    from kokoro import KPipeline  # noqa: F401
except ModuleNotFoundError as exc:
    print(f"ERROR: TTS dependency missing: {exc.name}")
    sys.exit(1)

if not torch.cuda.is_available():
    print("ERROR: Torch CUDA unavailable.")
    print("TTS_DEVICE=cuda was requested, so refusing to start on CPU.")
    sys.exit(1)

print(f"✅ Torch CUDA device for TTS: {torch.cuda.get_device_name(0)}")
PY
fi

check_tcp_url() {
    local label="$1"
    local url="$2"

    python - "$label" "$url" <<'PY'
import socket
import sys
from urllib.parse import urlparse

label, url = sys.argv[1], sys.argv[2]
parsed = urlparse(url)
host = parsed.hostname
port = parsed.port or (443 if parsed.scheme == "https" else 80)

if not host:
    sys.exit(0)

try:
    with socket.create_connection((host, port), timeout=1.0):
        pass
except OSError as exc:
    print(f"WARNING: {label} is not reachable at {host}:{port} ({exc}).")
    sys.exit(1)
PY
}

if ! check_tcp_url "LLM/VLM server" "$LLM_SERVER_URL"; then
    echo "WARNING: Start the README llama.cpp server before using chat or video calls."
fi
if [ "$VLM_SERVER_URL" != "$LLM_SERVER_URL" ]; then
    if ! check_tcp_url "VLM server" "$VLM_SERVER_URL"; then
        echo "WARNING: Start the README VLM llama.cpp server before using video calls."
    fi
fi
if [ "$ASR_MODE" != "local" ]; then
    if ! check_tcp_url "ASR server" "$ASR_API_URL"; then
        echo "WARNING: Start the ASR server or relaunch with --local-asr."
    fi
fi

# Launch server with SSL.
# Use exec to replace shell process so signals (SIGTERM, SIGINT) go directly to uvicorn.
UVICORN_ARGS=(
    server:app
    --host 0.0.0.0
    --port "$PORT"
    --ssl-keyfile "$SSL_KEY"
    --ssl-certfile "$SSL_CERT"
)

if [ "$UVICORN_RELOAD" == "true" ]; then
    UVICORN_ARGS+=(--reload --reload-exclude ".venv-gpu/*" --reload-exclude "audio_cache/*")
fi

exec uvicorn "${UVICORN_ARGS[@]}"
