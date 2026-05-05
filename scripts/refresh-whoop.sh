#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -f "$HOME/.bashrc" ]; then
    # shellcheck disable=SC1090
    source "$HOME/.bashrc"
fi

mkdir -p logs

LOCK_FILE="${WHOOP_REFRESH_LOCK:-/tmp/spark-realtime-chatbot-whoop-refresh.lock}"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "$(date -Is) WHOOP refresh already running; exiting."
    exit 0
fi

PYTHON_BIN="${WHOOP_REFRESH_PYTHON:-$REPO_ROOT/.venv-gpu/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

"$PYTHON_BIN" -m clients.whoop --refresh

if [ "${TOUCH_PROMPTS_ON_WHOOP_REFRESH:-1}" != "0" ]; then
    touch prompts.py
fi
