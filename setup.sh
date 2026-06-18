#!/bin/bash
# Unified setup for spark-realtime-chatbot.
#
# After `git clone`, this single script walks you through configuration,
# downloads the models, builds the CUDA dependencies (llama.cpp + CTranslate2),
# and launches all three servers (llama.cpp :30000, HTTPS frontend :8443,
# Discord bot). Re-running it is safe: completed steps are skipped.
#
# The phases below are plain functions so they can be sourced and exercised
# individually by tests/test_setup.sh. `main` only runs when the script is
# executed directly (not when sourced).

# ----------------------------------------------------------------------------
# Configuration (override via environment for testing / non-default layouts)
# ----------------------------------------------------------------------------
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$HOME/llama.cpp}"
VENV_DIR="${VENV_DIR:-$REPO_DIR/venv}"
LOG_DIR="${LOG_DIR:-$REPO_DIR/logs}"

# Pinned to the merge commit of ggml-org/llama.cpp#22673 ("llama + spec: MTP
# Support", merged 2026-05-16) — the first commit with multi-token prediction.
# It also contains all prior draft-model speculative-decoding infrastructure,
# so the --spec-draft-* launch flags below work against it. Do not use HEAD.
LLAMA_CPP_COMMIT="${LLAMA_CPP_COMMIT:-255582687b8dd211fdbc582e43ab842491554e94}"

# How long launch steps wait for a server port to come up.
SETUP_PORT_TIMEOUT="${SETUP_PORT_TIMEOUT:-90}"

# ----------------------------------------------------------------------------
# Logging helpers (ANSI colors auto-disabled when stdout is not a TTY)
# ----------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'
    C_RED=$'\033[31m'; C_RESET=$'\033[0m'
else
    C_GREEN=''; C_YELLOW=''; C_CYAN=''; C_RED=''; C_RESET=''
fi

log_ok()       { printf '%s[OK]%s %s\n'       "$C_GREEN"  "$C_RESET" "$*"; }
log_info()     { printf '%s[INFO]%s %s\n'     "$C_YELLOW" "$C_RESET" "$*"; }
log_install()  { printf '%s[INSTALL]%s %s\n'  "$C_CYAN"   "$C_RESET" "$*"; }
log_download() { printf '%s[DOWNLOAD]%s %s\n' "$C_CYAN"   "$C_RESET" "$*"; }
log_error()    { printf '%s[ERROR]%s %s\n'    "$C_RED"    "$C_RESET" "$*" >&2; }

die() { log_error "$*"; exit 1; }

# ----------------------------------------------------------------------------
# Phase 1: Pre-flight & configuration
# ----------------------------------------------------------------------------

prompt_discord_account() {
    cat <<'EOF'

==========================================================================
 Before we begin, make sure you have a Discord account ready and are
 logged into the Discord Developer Portal:

     https://discord.com/developers/applications

 You'll create a bot there in a later step (we can't script that part).
==========================================================================
EOF
    printf "Press Enter once you're logged in, or Ctrl+C to exit "
    read -r _
}

configure_demo_partner() {
    while true; do
        printf 'Is the demo partner a husband or wife? [husband/wife] '
        read -r ans
        ans="$(printf '%s' "$ans" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
        case "$ans" in
            husband|wife)
                export DEMO_PARTNER="$ans"
                log_ok "Demo partner set to: $DEMO_PARTNER"
                return 0
                ;;
            *)
                log_info "Please type 'husband' or 'wife'."
                ;;
        esac
    done
}

configure_hf_token() {
    if [ -n "${HF_TOKEN:-}" ]; then
        log_info "Using HF_TOKEN ending in ...${HF_TOKEN: -6}"
    else
        printf 'Paste your Hugging Face token: '
        read -r HF_TOKEN
        export HF_TOKEN
        log_ok "Hugging Face token captured."
    fi
}

print_discord_instructions() {
    cat <<'EOF'

--------------------------------------------------------------------------
 Create your Discord bot (browser-only — cannot be scripted):

   1. Visit https://discord.com/developers/applications -> New Application
   2. Open the "Bot" tab -> Reset Token -> copy the token
   3. Under Privileged Gateway Intents, enable "Message Content Intent"
   4. OAuth2 -> URL Generator:
        scopes:      bot
        permissions: View Channels, Send Messages, Read Message History
      Copy the generated invite URL and use it to invite the bot to your
      server.
--------------------------------------------------------------------------
EOF
}

configure_discord_token() {
    print_discord_instructions
    printf 'Paste your Discord Bot Token (see instructions above): '
    read -r DISCORD_BOT_TOKEN
    export DISCORD_BOT_TOKEN
    log_ok "Discord bot token captured."
}

# ----------------------------------------------------------------------------
# Phase 2: Installation
# ----------------------------------------------------------------------------

install_venv() {
    if [ -x "$VENV_DIR/bin/python" ]; then
        log_ok "Python virtual environment already exists, skipping creation."
    else
        log_install "Creating Python virtual environment..."
        python3 -m venv "$VENV_DIR" || die "failed: python3 -m venv $VENV_DIR"
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate" || die "failed to activate venv"
    log_install "Installing Python requirements..."
    pip install -r "$REPO_DIR/requirements.txt" || die "failed: pip install -r requirements.txt"
    log_ok "Python dependencies installed."
}

install_llama_cpp() {
    if [ -x "$LLAMA_CPP_DIR/build/bin/llama-server" ]; then
        log_ok "llama.cpp already built, skipping."
        return 0
    fi
    log_install "Building llama.cpp @ $LLAMA_CPP_COMMIT..."
    if [ ! -d "$LLAMA_CPP_DIR/.git" ]; then
        git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_CPP_DIR" \
            || die "failed: git clone llama.cpp"
    fi
    git -C "$LLAMA_CPP_DIR" fetch --quiet origin "$LLAMA_CPP_COMMIT" 2>/dev/null || true
    git -C "$LLAMA_CPP_DIR" checkout "$LLAMA_CPP_COMMIT" \
        || die "failed: git checkout $LLAMA_CPP_COMMIT"
    cmake -S "$LLAMA_CPP_DIR" -B "$LLAMA_CPP_DIR/build" -DGGML_CUDA=ON \
        || die "failed: cmake configure (llama.cpp)"
    cmake --build "$LLAMA_CPP_DIR/build" --config Release -j --target llama-server \
        || die "failed: cmake build (llama.cpp)"
    log_ok "llama.cpp built @ $LLAMA_CPP_COMMIT."
}

download_models() {
    log_download "Fetching Qwen3.6-35B-A3B (main model)..."
    MODEL="$(hf download --quiet unsloth/Qwen3.6-35B-A3B-GGUF Qwen3.6-35B-A3B-UD-Q4_K_M.gguf)" \
        || die "failed to download main model"
    log_download "Fetching Qwen3.6-35B-A3B (mmproj / vision)..."
    MMPROJ="$(hf download --quiet unsloth/Qwen3.6-35B-A3B-GGUF mmproj-BF16.gguf)" \
        || die "failed to download mmproj"
    log_download "Fetching Qwen3.5-0.8B (draft model)..."
    DRAFT="$(hf download --quiet unsloth/Qwen3.5-0.8B-GGUF Qwen3.5-0.8B-Q4_K_M.gguf)" \
        || die "failed to download draft model"
    export MODEL MMPROJ DRAFT
    [ -n "$MODEL" ] && [ -n "$MMPROJ" ] && [ -n "$DRAFT" ] \
        || die "model download returned an empty path"
    log_ok "Models ready."
}

install_ctranslate2() {
    if compgen -G "$VENV_DIR"/lib/python*/site-packages/ctranslate2 >/dev/null; then
        log_ok "CTranslate2 already installed, skipping build."
        return 0
    fi
    log_install "Building CUDA-enabled CTranslate2 for local ASR..."
    export CUDAARCHS=121
    mkdir -p "$REPO_DIR/build"
    local ct2="$REPO_DIR/build/CTranslate2"
    [ -d "$ct2/.git" ] || git clone --recursive \
        https://github.com/OpenNMT/CTranslate2.git "$ct2" || die "failed: git clone CTranslate2"

    # CMake doesn't know Blackwell (sm_121): comment out the arch autodetect and
    # hard-code the gencode flag. (No-op if already patched on a re-run.)
    sed -i 's/cuda_select_nvcc_arch_flags/#cuda_select_nvcc_arch_flags/' "$ct2/CMakeLists.txt"
    sed -i 's/list(APPEND CUDA_NVCC_FLAGS ${CUDA_NVCC_FLAGS_READABLE})/list(APPEND CUDA_NVCC_FLAGS "-gencode=arch=compute_121,code=sm_121")/' "$ct2/CMakeLists.txt"

    mkdir -p "$ct2/build"
    ( cd "$ct2/build" && cmake .. \
        -DCMAKE_BUILD_TYPE=Release -DWITH_CUDA=ON -DWITH_CUDNN=OFF \
        -DWITH_MKL=OFF -DOPENMP_RUNTIME=NONE -DCMAKE_INSTALL_PREFIX=/usr/local \
        && make -j"$(nproc)" ) || die "failed to build CTranslate2"
    ( cd "$ct2/build" && sudo make install && sudo ldconfig ) \
        || die "failed to install CTranslate2"
    pip install "$ct2/python" || die "failed: pip install CTranslate2 python bindings"
    log_ok "CTranslate2 installed."
}

# ----------------------------------------------------------------------------
# Phase 3: Launch servers
# ----------------------------------------------------------------------------

wait_for_port() {
    local port="$1" name="$2" waited=0
    while ! nc -z -w 2 localhost "$port" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
        if [ "$waited" -ge "$SETUP_PORT_TIMEOUT" ]; then
            die "$name did not start listening on port $port within ${SETUP_PORT_TIMEOUT}s (see $LOG_DIR)"
        fi
    done
    log_ok "$name is listening on port $port."
}

launch_llama() {
    mkdir -p "$LOG_DIR"
    log_install "Starting llama.cpp server on :30000 (logs -> $LOG_DIR/llama.log)..."
    ( cd "$LLAMA_CPP_DIR" && exec ./build/bin/llama-server \
        --model "$MODEL" --mmproj "$MMPROJ" -md "$DRAFT" \
        --spec-draft-ngl 99 --spec-draft-n-max 16 --spec-draft-n-min 0 \
        --spec-draft-p-min 0.75 --host 0.0.0.0 --port 30000 \
        --n-gpu-layers 99 --ctx-size 16384 \
        --chat-template-kwargs '{"enable_thinking": false}' --threads 8 \
    ) >"$LOG_DIR/llama.log" 2>&1 &
    wait_for_port 30000 "llama.cpp server"
}

launch_https() {
    mkdir -p "$LOG_DIR"
    log_install "Starting HTTPS frontend on :8443 (logs -> $LOG_DIR/https.log)..."
    ( cd "$REPO_DIR" && DEMO_PARTNER="$DEMO_PARTNER" exec ./launch-https.sh --local-asr \
    ) >"$LOG_DIR/https.log" 2>&1 &
    wait_for_port 8443 "HTTPS server"
}

launch_discord() {
    mkdir -p "$LOG_DIR"
    log_install "Starting Discord bot (logs -> $LOG_DIR/discord.log)..."
    ( cd "$REPO_DIR" && DISCORD_BOT_TOKEN="$DISCORD_BOT_TOKEN" exec python3 clients/discord-bot.py \
    ) >"$LOG_DIR/discord.log" 2>&1 &
    sleep 2
    pgrep -f discord-bot.py >/dev/null \
        || die "Discord bot failed to start (see $LOG_DIR/discord.log)"
    log_ok "Discord bot is running."
}

print_ready() {
    printf '\n%s[READY]%s Setup complete!\n' "$C_GREEN" "$C_RESET"
    echo "  -> Open https://localhost:8443 in your browser (accept the self-signed cert)"
    echo "  -> Allow microphone access when prompted"
    echo "  -> Discord bot is running — send it a message to confirm"
}

# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------

main() {
    log_info "spark-realtime-chatbot setup starting..."

    # Phase 1: configuration
    prompt_discord_account
    configure_demo_partner
    configure_hf_token
    configure_discord_token

    # Phase 2: installation
    install_venv
    install_llama_cpp
    download_models
    install_ctranslate2

    # Phase 3: launch
    launch_llama
    launch_https
    launch_discord

    print_ready
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -euo pipefail
    trap 'log_error "command failed: ${BASH_COMMAND}"; exit 1' ERR
    main "$@"
fi
