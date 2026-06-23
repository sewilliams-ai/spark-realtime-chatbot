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

# How long to wait for the Discord bot to log in before declaring failure.
SETUP_DISCORD_TIMEOUT="${SETUP_DISCORD_TIMEOUT:-120}"

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
 Discord setup (browser-only — these steps cannot be scripted):

 A. Create a server to host the bot:
    1. Go to https://discord.com/channels/@me
    2. Click "Add a Server" (the + button in the left sidebar)
    3. Choose "Create My Own" -> "For me and my friends"

 B. Create your own bot application:
    1. Visit https://discord.com/developers/applications -> New Application
    2. Open the "Bot" tab -> Reset Token -> copy the token (paste it below)
    3. In the bot tab under "Privileged Gateway Intents", enable
       "Message Content Intent", then Save Changes.
       REQUIRED: this bot reads message text. Without this toggle the bot
       crashes on startup with PrivilegedIntentsRequired. It is free to
       enable for bots in fewer than 100 servers.
    4. In the bot tab, scroll down to "Bot Permissions" and enable
       "Send Messages".

 C. Add YOUR bot to YOUR server:
    1. After you paste the token below, this script validates it and prints a
       personalized invite URL for your bot (no manual OAuth2 URL Generator
       step needed).
    2. Open that URL, select the server you created in step A, click
       "Authorize", and finish the captcha.
    3. Send the bot a message in that server to confirm it replies.
--------------------------------------------------------------------------
EOF
}

configure_discord_token() {
    print_discord_instructions
    printf 'Paste your Discord Bot Token (see instructions above): '
    read -r DISCORD_BOT_TOKEN
    export DISCORD_BOT_TOKEN
    log_ok "Discord bot token captured."
    build_discord_invite_url
}

# Derive the bot's application (client) ID from its own token and build a
# ready-to-use invite URL with exactly the permissions this bot needs. Each
# operator gets a URL for THEIR bot, so the setup is fully portable — nothing
# server- or bot-specific is hardcoded. Also validates the token (a bad token
# returns no id).
build_discord_invite_url() {
    # View Channels(1024) + Send Messages(2048) + Read Message History(65536)
    local perms=68608 appid
    appid="$(curl -fsS -H "Authorization: Bot $DISCORD_BOT_TOKEN" \
        https://discord.com/api/v10/users/@me 2>/dev/null \
        | grep -oE '"id"[[:space:]]*:[[:space:]]*"[0-9]+"' \
        | grep -oE '[0-9]+' | head -1)"
    [ -n "$appid" ] || die "Could not validate the Discord bot token (check the token and your network connection — the Discord API returned no application id)."
    DISCORD_INVITE_URL="https://discord.com/oauth2/authorize?client_id=${appid}&permissions=${perms}&scope=bot"
    export DISCORD_INVITE_URL
    log_ok "Validated token — your bot's application id is ${appid}."
    printf '\n%s[ACTION]%s Invite YOUR bot to YOUR server by opening this URL:\n  %s\n\n' \
        "$C_YELLOW" "$C_RESET" "$DISCORD_INVITE_URL"
}

# ----------------------------------------------------------------------------
# Phase 2: Installation
# ----------------------------------------------------------------------------

install_venv() {
    if [ -x "$VENV_DIR/bin/python" ]; then
        log_ok "Python virtual environment already exists, skipping creation."
    else
        log_install "Creating Python virtual environment..."
        # The dependency set (kokoro, pandas, deepface, ...) only ships prebuilt
        # wheels for Python 3.10-3.12. On 3.13 pip falls back to source builds
        # that fail to compile, so prefer a 3.12 interpreter when available.
        local py
        for py in python3.12 python3.11 python3.10 python3; do
            if command -v "$py" >/dev/null 2>&1; then
                "$py" -m venv "$VENV_DIR" && break
            fi
        done
        [ -x "$VENV_DIR/bin/python" ] || die "failed to create venv $VENV_DIR"
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate" || die "failed to activate venv"
    log_install "Installing Python requirements..."
    pip install -r "$REPO_DIR/requirements.txt" || die "failed: pip install -r requirements.txt"
    log_ok "Python dependencies installed."
}

install_llama_cpp() {
    # The launch flags below (--spec-draft-*) and MTP speculative decoding only
    # exist at $LLAMA_CPP_COMMIT. A pre-existing llama.cpp checkout/build at any
    # other revision (common on a machine that's already used llama.cpp) would
    # be silently reused and reject those flags, so gate the "skip" on the build
    # actually being at the pinned commit — not merely on a binary existing.
    local head=""
    if [ -d "$LLAMA_CPP_DIR/.git" ]; then
        head="$(git -C "$LLAMA_CPP_DIR" rev-parse HEAD 2>/dev/null || true)"
    fi
    if [ -x "$LLAMA_CPP_DIR/build/bin/llama-server" ] && [ "$head" = "$LLAMA_CPP_COMMIT" ]; then
        log_ok "llama.cpp already built at pinned commit, skipping."
        return 0
    fi
    if [ -x "$LLAMA_CPP_DIR/build/bin/llama-server" ]; then
        log_info "Existing llama.cpp is at ${head:-unknown}, not the pinned commit — rebuilding."
    fi
    log_install "Building llama.cpp @ $LLAMA_CPP_COMMIT..."
    if [ ! -d "$LLAMA_CPP_DIR/.git" ]; then
        git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_CPP_DIR" \
            || die "failed: git clone llama.cpp"
    fi
    git -C "$LLAMA_CPP_DIR" fetch --quiet origin "$LLAMA_CPP_COMMIT" 2>/dev/null || true
    git -C "$LLAMA_CPP_DIR" checkout "$LLAMA_CPP_COMMIT" \
        || die "failed: git checkout $LLAMA_CPP_COMMIT (could not fetch the pinned llama.cpp commit — check your network)"
    # Configure from scratch so a build dir left over from a different commit
    # can't poison the new build with stale CMake cache entries.
    rm -rf "$LLAMA_CPP_DIR/build"
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
    # faster-whisper (a requirements.txt dep) installs the PyPI ctranslate2
    # wheel, which on ARM (all DGX Sparks) is built WITHOUT CUDA. Skipping just
    # because *some* ctranslate2 is importable leaves that CPU-only build in
    # place, and the ASR model load then crashes with "not compiled with CUDA
    # support". So skip only when the installed build actually has CUDA — probe
    # it directly rather than checking for the package's mere presence.
    if "$VENV_DIR/bin/python" -c \
        'import ctranslate2; ctranslate2.get_supported_compute_types("cuda")' \
        >/dev/null 2>&1; then
        log_ok "CUDA-enabled CTranslate2 already installed, skipping build."
        return 0
    fi
    log_install "Building CUDA-enabled CTranslate2 for local ASR..."
    export CUDAARCHS=121
    mkdir -p "$REPO_DIR/build"
    local ct2="$REPO_DIR/build/CTranslate2"
    # Pin to v4.8.0: it's the same version as the PyPI ctranslate2 that
    # faster-whisper resolves to (so a later `pip install -r requirements.txt`
    # won't pull the CPU wheel back over this build), it satisfies
    # faster-whisper's ctranslate2<5 constraint, and it makes the CMake patch
    # below deterministic instead of tracking a moving master branch.
    if [ ! -d "$ct2/.git" ]; then
        git clone https://github.com/OpenNMT/CTranslate2.git "$ct2" \
            || die "failed: git clone CTranslate2"
    fi
    git -C "$ct2" fetch --quiet --tags origin 2>/dev/null || true
    # -f so a CMakeLists.txt left patched by a previous failed run is reset,
    # keeping the sed below idempotent.
    git -C "$ct2" checkout -f v4.8.0 || die "failed: git checkout CTranslate2 v4.8.0"
    git -C "$ct2" submodule update --init --recursive \
        || die "failed: CTranslate2 submodules"

    # CTranslate2's bundled cuda_select_nvcc_arch_flags() doesn't know Blackwell
    # (sm_121, the GB10 in DGX Spark), so replace the arch autodetect with a
    # hard-coded gencode. The downstream `list(APPEND CUDA_NVCC_FLAGS
    # ${ARCH_FLAGS})` then picks it up.
    sed -i 's|cuda_select_nvcc_arch_flags(ARCH_FLAGS ${CUDA_ARCH_LIST})|set(ARCH_FLAGS "-gencode=arch=compute_121,code=sm_121")|' \
        "$ct2/CMakeLists.txt"
    grep -q 'arch=compute_121,code=sm_121' "$ct2/CMakeLists.txt" \
        || die "CTranslate2 CMake arch patch did not apply (upstream CMakeLists.txt changed)"

    # Configure from scratch so a build dir from a prior attempt can't reuse a
    # stale CMake cache.
    rm -rf "$ct2/build"
    mkdir -p "$ct2/build"
    ( cd "$ct2/build" && cmake .. \
        -DCMAKE_BUILD_TYPE=Release -DWITH_CUDA=ON -DWITH_CUDNN=OFF \
        -DWITH_MKL=OFF -DOPENMP_RUNTIME=NONE -DCMAKE_INSTALL_PREFIX=/usr/local \
        && make -j"$(nproc)" ) || die "failed to build CTranslate2"
    ( cd "$ct2/build" && sudo make install && sudo ldconfig ) \
        || die "failed to install CTranslate2"
    # --force-reinstall --no-deps so this CUDA build replaces the CPU-only PyPI
    # wheel even though they share the version number 4.8.0.
    pip install --force-reinstall --no-deps "$ct2/python" \
        || die "failed: pip install CTranslate2 python bindings"
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
    if nc -z -w 2 localhost 30000 2>/dev/null; then
        log_ok "llama.cpp already serving on :30000, skipping launch."
        return 0
    fi
    mkdir -p "$LOG_DIR"
    log_install "Starting llama.cpp server on :30000 (logs -> $LOG_DIR/llama.log)..."
    ( cd "$LLAMA_CPP_DIR" && exec ./build/bin/llama-server \
        --model "$MODEL" --mmproj "$MMPROJ" -md "$DRAFT" \
        --spec-draft-ngl 99 --spec-draft-n-max 16 --spec-draft-n-min 0 \
        --spec-draft-p-min 0.75 --host 0.0.0.0 --port 30000 \
        --n-gpu-layers 99 --ctx-size 16384 \
        --chat-template-kwargs '{"enable_thinking": false}' --threads 8 \
    ) >"$LOG_DIR/llama.log" 2>&1 &
    echo $! > "$LOG_DIR/llama.pid"
    wait_for_port 30000 "llama.cpp server"
}

launch_https() {
    if nc -z -w 2 localhost 8443 2>/dev/null; then
        log_ok "HTTPS server already serving on :8443, skipping launch."
        return 0
    fi
    mkdir -p "$LOG_DIR"
    log_install "Starting HTTPS frontend on :8443 (logs -> $LOG_DIR/https.log)..."
    ( cd "$REPO_DIR" && DEMO_PARTNER="$DEMO_PARTNER" exec ./launch-https.sh --local-asr \
    ) >"$LOG_DIR/https.log" 2>&1 &
    echo $! > "$LOG_DIR/https.pid"
    wait_for_port 8443 "HTTPS server"
}

launch_discord() {
    if pgrep -f "clients/discord-bot.py" >/dev/null; then
        log_ok "Discord bot already running, skipping launch."
        return 0
    fi
    mkdir -p "$LOG_DIR"
    log_install "Starting Discord bot (logs -> $LOG_DIR/discord.log)..."
    : > "$LOG_DIR/discord.log"
    # PYTHONUNBUFFERED so the bot's log (incl. "Logged in as") flushes promptly.
    ( cd "$REPO_DIR" && DISCORD_BOT_TOKEN="$DISCORD_BOT_TOKEN" PYTHONUNBUFFERED=1 \
        exec python3 clients/discord-bot.py \
    ) >"$LOG_DIR/discord.log" 2>&1 &
    local pid=$!
    echo "$pid" > "$LOG_DIR/discord.pid"

    # The process exists long before it connects (heavy imports + Whisper load),
    # so a bare pgrep would report a false success. Wait until it actually logs
    # in, and surface the real error from the log if it dies or never connects.
    local waited=0
    until grep -q "Logged in as" "$LOG_DIR/discord.log" 2>/dev/null; do
        if ! kill -0 "$pid" 2>/dev/null; then
            log_error "Discord bot exited during startup — last log lines:"
            tail -n 20 "$LOG_DIR/discord.log" >&2
            die "Discord bot failed to start (common causes: bad DISCORD_BOT_TOKEN, or Message Content Intent not enabled in the developer portal)"
        fi
        sleep 2
        waited=$((waited + 2))
        if [ "$waited" -ge "$SETUP_DISCORD_TIMEOUT" ]; then
            log_error "Discord bot did not log in within ${SETUP_DISCORD_TIMEOUT}s — last log lines:"
            tail -n 20 "$LOG_DIR/discord.log" >&2
            die "Discord bot failed to connect (check the token, network, and Message Content Intent)"
        fi
    done
    log_ok "Discord bot logged in and running."
}

print_ready() {
    local ip
    ip="$(hostname -I 2>/dev/null | awk '{print $1}')"

    printf '\nFinal step - add discord bot to server:\n'
    if [ -n "${DISCORD_INVITE_URL:-}" ]; then
        echo "  -> If the bot isn't in your server yet, invite it: $DISCORD_INVITE_URL"
    fi
    echo "  -> Discord bot is running — send it a message in your server to confirm"
    echo "     Access your Discord servers here: https://discord.com/channels/@me"

    printf '\n%s[READY]%s Setup complete!\n' "$C_GREEN" "$C_RESET"
    echo "  -> Open https://localhost:8443 in your browser to access the web app (accept the self-signed cert)"
    if [ -n "$ip" ]; then
        echo "     If accessing this machine remotely, use https://$ip:8443 instead"
    else
        echo "     If accessing this machine remotely, replace 'localhost' with the machine's local IP"
    fi
    echo "  -> Allow microphone access when prompted"
    echo "  -> To stop all servers (keeping models/build): ./stop.sh"
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
