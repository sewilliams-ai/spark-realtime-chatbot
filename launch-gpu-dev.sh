#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PORT="${PORT:-8445}"
export ASR_MODE="local"
export ASR_DEVICE="${ASR_DEVICE:-cuda}"
export ASR_COMPUTE_TYPE="${ASR_COMPUTE_TYPE:-float16}"
export TTS_ENGINE="${TTS_ENGINE:-kokoro}"
export TTS_DEVICE="${TTS_DEVICE:-cuda}"
export TTS_OVERLAP="${TTS_OVERLAP:-true}"
export UVICORN_RELOAD="${UVICORN_RELOAD:-true}"

exec ./launch-https.sh --local-asr --tts-overlap --reload "$@"
