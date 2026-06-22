#!/usr/bin/env bash
# Test suite for setup.sh — TDD coverage of every phase.
#
# Uses bats if available, otherwise plain-bash assertions (the path taken here).
# Everything runs against an isolated sandbox with mocked external commands
# (git, cmake, pip, hf, python3, make, sudo) so the suite is fast and offline:
# no real builds, downloads, or GPU required.
#
#   Run:  bash tests/test_setup.sh
#
set -uo pipefail

SCRIPT_UNDER_TEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/setup.sh"

# --------------------------------------------------------------------------
# Tiny assertion framework
# --------------------------------------------------------------------------
TESTS_PASS=0
TESTS_FAIL=0

pass() { printf '    ok   - %s\n' "$1"; TESTS_PASS=$((TESTS_PASS + 1)); }
fail() { printf '    FAIL - %s\n        %s\n' "$1" "$2"; TESTS_FAIL=$((TESTS_FAIL + 1)); }

assert_contains() { # haystack needle name
    if printf '%s' "$1" | grep -qF -- "$2"; then pass "$3"
    else fail "$3" "expected to contain [$2], got: $1"; fi
}
assert_file() { # path name
    if [ -e "$1" ]; then pass "$2"; else fail "$2" "missing path: $1"; fi
}
assert_port() { # port name
    if nc -z -w 2 localhost "$1" 2>/dev/null; then pass "$2"
    else fail "$2" "nothing listening on port $1"; fi
}
assert_pgrep() { # pattern name
    if pgrep -f "$1" >/dev/null; then pass "$2"
    else fail "$2" "no process matching: $1"; fi
}

# --------------------------------------------------------------------------
# Sandbox + mocks
# --------------------------------------------------------------------------
new_sandbox() {
    SANDBOX="$(mktemp -d)"
    export HOME="$SANDBOX/home";          mkdir -p "$HOME"
    export REPO_DIR="$SANDBOX/repo";       mkdir -p "$REPO_DIR/clients"
    export VENV_DIR="$REPO_DIR/venv"
    export LOG_DIR="$REPO_DIR/logs"
    export LLAMA_CPP_DIR="$HOME/llama.cpp"
    export SETUP_PORT_TIMEOUT=20
    export NO_COLOR=1

    # Repo files the script references.
    printf 'fastapi\n' > "$REPO_DIR/requirements.txt"
    printf 'import time\ntime.sleep(300)\n' > "$REPO_DIR/clients/discord-bot.py"
    # Stub HTTPS launcher: bind :8443 and stay up.
    cat > "$REPO_DIR/launch-https.sh" <<'EOF'
#!/usr/bin/env bash
exec python3 -c "import socket
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('0.0.0.0',8443)); s.listen(16)
while True:
    c,_=s.accept(); c.close()"
EOF
    chmod +x "$REPO_DIR/launch-https.sh"

    local bin="$SANDBOX/bin"
    mkdir -p "$bin"

    # git: clone makes a .git dir; CTranslate2 clone seeds a patchable CMakeLists.
    cat > "$bin/git" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "clone" ]; then
    dest="${@: -1}"; url="${@: -2:1}"
    mkdir -p "$dest/.git"
    if [[ "$url" == *CTranslate2* ]]; then
        printf 'cuda_select_nvcc_arch_flags\nlist(APPEND CUDA_NVCC_FLAGS ${CUDA_NVCC_FLAGS_READABLE})\n' > "$dest/CMakeLists.txt"
    fi
fi
exit 0
EOF

    # cmake: a `--build <dir>` that targets llama-server drops a port-binding stub.
    cat > "$bin/cmake" <<'EOF'
#!/usr/bin/env bash
build=""; mode="configure"
while [ $# -gt 0 ]; do
    case "$1" in
        --build) mode="build"; build="$2"; shift 2;;
        -B) build="$2"; shift 2;;
        *) shift;;
    esac
done
if [ "$mode" = "build" ] && [ -n "$build" ]; then
    mkdir -p "$build/bin"
    cat > "$build/bin/llama-server" <<'STUB'
#!/usr/bin/env bash
port=30000
while [ $# -gt 0 ]; do [ "$1" = "--port" ] && port="$2"; shift; done
exec python3 -c "import socket
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('0.0.0.0',$port)); s.listen(16)
while True:
    c,_=s.accept(); c.close()"
STUB
    chmod +x "$build/bin/llama-server"
fi
exit 0
EOF

    # hf: echo a deterministic fake cache path for the requested file.
    cat > "$bin/hf" <<'EOF'
#!/usr/bin/env bash
echo "/tmp/fakehf/${@: -1}"
EOF

    # curl: stand in for the Discord /users/@me lookup with a fake application id.
    cat > "$bin/curl" <<'EOF'
#!/usr/bin/env bash
echo '{"id":"123456789012345678","username":"test-bot","bot":true}'
EOF

    # pip: installing the CTranslate2 python bindings drops a site-packages dir.
    cat > "$bin/pip" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do
    case "$a" in
        */python)
            sp="$(ls -d "$VENV_DIR"/lib/python*/site-packages 2>/dev/null | head -1)"
            [ -n "$sp" ] && mkdir -p "$sp/ctranslate2";;
    esac
done
exit 0
EOF

    # python3: `-m venv` builds a fake venv; `discord-bot.py` lingers (so pgrep
    # matches); everything else (the -c listeners) falls through to real python3.
    cat > "$bin/python3" <<'EOF'
#!/usr/bin/env bash
case "$*" in
    *"-m venv"*)
        d="${@: -1}"; mkdir -p "$d/bin" "$d/lib/python3.11/site-packages"
        printf '#!/bin/bash\n' > "$d/bin/python"; chmod +x "$d/bin/python"
        cp "$d/bin/python" "$d/bin/python3"
        printf ':\n' > "$d/bin/activate"; exit 0;;
    *discord-bot.py*)               # keep discord-bot.py in argv for pgrep -f
        echo "Logged in as test-bot#0001"   # setup.sh waits for this line
        trap 'kill $(jobs -p) 2>/dev/null; exit 0' TERM INT
        sleep 300 & wait;;
    *)
        exec /usr/bin/python3 "$@";;
esac
EOF

    # make / sudo / ldconfig: succeed without doing anything.
    for noop in make sudo ldconfig; do
        printf '#!/usr/bin/env bash\nexit 0\n' > "$bin/$noop"
    done

    chmod +x "$bin"/*
    export PATH="$bin:$PATH"
}

cleanup_servers() {
    # Kill listeners by port (the python -c arg spans newlines, which defeats a
    # pkill -f pattern match), then the discord stub by its argv.
    local port pid
    for port in 30000 8443; do
        pid="$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)"
        [ -n "$pid" ] && kill "$pid" 2>/dev/null
    done
    pkill -f "discord-bot.py" 2>/dev/null || true
    sleep 1
}
teardown() { cleanup_servers; [ -n "${SANDBOX:-}" ] && rm -rf "$SANDBOX"; }
trap 'cleanup_servers' EXIT

# ==========================================================================
# Phase 1: Pre-flight & configuration
# ==========================================================================
echo "Phase 1: pre-flight & configuration"

new_sandbox
out="$(printf '\n' | ( source "$SCRIPT_UNDER_TEST"; prompt_discord_account ) 2>&1)"
assert_contains "$out" "Discord Developer Portal" "discord account: shows portal instructions"
assert_contains "$out" "Press Enter once you're logged in" "discord account: pauses for Enter"
teardown

new_sandbox
out="$(printf 'wife\n' | ( source "$SCRIPT_UNDER_TEST"; configure_demo_partner; echo "DP=$DEMO_PARTNER" ) 2>&1)"
assert_contains "$out" "DP=wife" "demo partner: 'wife' exported"
out="$(printf 'foo\nwife\n' | ( source "$SCRIPT_UNDER_TEST"; configure_demo_partner; echo "DP=$DEMO_PARTNER" ) 2>&1)"
assert_contains "$out" "Please type 'husband' or 'wife'." "demo partner: re-prompts on invalid input"
assert_contains "$out" "DP=wife" "demo partner: accepts valid input after re-prompt"
teardown

new_sandbox
out="$(( export HF_TOKEN=abc123456789; source "$SCRIPT_UNDER_TEST"; configure_hf_token ) 2>&1)"
assert_contains "$out" "[INFO] Using HF_TOKEN" "hf token: logs INFO when preset"
assert_contains "$out" "456789" "hf token: logs last 6 chars only"
out="$(printf 'hf_pasted_value\n' | ( unset HF_TOKEN; source "$SCRIPT_UNDER_TEST"; configure_hf_token; echo "TOK=$HF_TOKEN" ) 2>&1)"
assert_contains "$out" "Paste your Hugging Face token" "hf token: prompts when unset"
assert_contains "$out" "TOK=hf_pasted_value" "hf token: exports pasted value"
teardown

new_sandbox
out="$(printf 'my-bot-token\n' | ( source "$SCRIPT_UNDER_TEST"; configure_discord_token; echo "DT=$DISCORD_BOT_TOKEN"; echo "URL=$DISCORD_INVITE_URL" ) 2>&1)"
assert_contains "$out" "New Application" "discord token: prints bot-creation instructions"
assert_contains "$out" "Message Content Intent" "discord token: mentions required intent"
assert_contains "$out" "DT=my-bot-token" "discord token: exports pasted token"
assert_contains "$out" "client_id=123456789012345678" "discord token: builds invite URL from the bot's client id"
assert_contains "$out" "URL=https://discord.com/oauth2/authorize" "discord token: exports DISCORD_INVITE_URL"
teardown

# ==========================================================================
# Phase 2: Installation
# ==========================================================================
echo "Phase 2: installation"

new_sandbox
( source "$SCRIPT_UNDER_TEST"; install_venv ) >/dev/null 2>&1
assert_file "$VENV_DIR/bin/python" "venv: venv/bin/python created"
teardown

new_sandbox
out="$(( source "$SCRIPT_UNDER_TEST"; install_llama_cpp ) 2>&1)"
assert_file "$LLAMA_CPP_DIR/build/bin/llama-server" "llama.cpp: llama-server binary built"
assert_contains "$out" "255582687b8dd211fdbc582e43ab842491554e94" "llama.cpp: logs the pinned commit SHA"
# Idempotency: a second run skips the build.
out="$(( source "$SCRIPT_UNDER_TEST"; install_llama_cpp ) 2>&1)"
assert_contains "$out" "already built" "llama.cpp: re-run skips an existing build"
teardown

new_sandbox
out="$(( source "$SCRIPT_UNDER_TEST"; download_models; echo "M=[$MODEL] MM=[$MMPROJ] D=[$DRAFT]" ) 2>&1)"
assert_contains "$out" "M=[/tmp/fakehf/" "models: MODEL path captured"
assert_contains "$out" "MM=[/tmp/fakehf/" "models: MMPROJ path captured"
assert_contains "$out" "D=[/tmp/fakehf/" "models: DRAFT path captured"
teardown

new_sandbox
( source "$SCRIPT_UNDER_TEST"; install_venv; install_ctranslate2 ) >/dev/null 2>&1
if compgen -G "$VENV_DIR"/lib/python*/site-packages/ctranslate2 >/dev/null; then
    pass "ctranslate2: bindings present in site-packages"
else
    fail "ctranslate2: bindings present in site-packages" "ctranslate2 dir not created"
fi
teardown

# ==========================================================================
# Phase 3: Launch servers
# ==========================================================================
echo "Phase 3: launch servers"

new_sandbox
( source "$SCRIPT_UNDER_TEST"; install_llama_cpp; download_models; launch_llama ) >/dev/null 2>&1
assert_port 30000 "launch: llama.cpp listening on :30000"
assert_file "$LOG_DIR/llama.log" "launch: llama.log written"
cleanup_servers
teardown

new_sandbox
( source "$SCRIPT_UNDER_TEST"; export DEMO_PARTNER=wife; launch_https ) >/dev/null 2>&1
assert_port 8443 "launch: HTTPS server listening on :8443"
assert_file "$LOG_DIR/https.log" "launch: https.log written"
cleanup_servers
teardown

new_sandbox
out="$(( source "$SCRIPT_UNDER_TEST"; export DISCORD_BOT_TOKEN=tok; launch_discord ) 2>&1)"
assert_pgrep "discord-bot.py" "launch: discord bot process running"
assert_file "$LOG_DIR/discord.log" "launch: discord.log written"
assert_contains "$out" "logged in and running" "launch: discord readiness waits for actual login"
cleanup_servers
teardown

# ==========================================================================
# Phase 3b: idempotency & teardown
# ==========================================================================
echo "Phase 3b: idempotency & teardown"

# A second launch_llama skips when something is already serving the port.
new_sandbox
( source "$SCRIPT_UNDER_TEST"; install_llama_cpp; download_models; launch_llama ) >/dev/null 2>&1
out="$(( source "$SCRIPT_UNDER_TEST"; install_llama_cpp; download_models; launch_llama ) 2>&1)"
assert_contains "$out" "already serving on :30000" "idempotency: re-run skips launch when port is up"
cleanup_servers
teardown

# stop.sh stops all three servers (artifacts untouched).
new_sandbox
STOP_SH="$(dirname "$SCRIPT_UNDER_TEST")/stop.sh"
( source "$SCRIPT_UNDER_TEST"; install_llama_cpp; download_models; launch_llama
  export DEMO_PARTNER=wife; launch_https
  export DISCORD_BOT_TOKEN=tok; launch_discord ) >/dev/null 2>&1
assert_port 30000 "stop: llama up before stop"
bash "$STOP_SH" >/dev/null 2>&1
sleep 1
nc -z -w 2 localhost 30000 2>/dev/null && fail "stop: llama stopped" "still listening" || pass "stop: llama stopped"
nc -z -w 2 localhost 8443  2>/dev/null && fail "stop: HTTPS stopped" "still listening" || pass "stop: HTTPS stopped"
pgrep -f discord-bot.py >/dev/null && fail "stop: discord stopped" "still running" || pass "stop: discord stopped"
teardown

# ==========================================================================
# End-to-end: full script against mocks prints [READY]
# ==========================================================================
echo "End-to-end"

new_sandbox
out="$(printf '\nwife\nmy-hf-token\nmy-discord-token\n' \
    | env -u HF_TOKEN bash "$SCRIPT_UNDER_TEST" 2>&1)"
assert_contains "$out" "Final step - add discord bot to server" "e2e: shows final Discord step before READY"
assert_contains "$out" "[READY] Setup complete!" "e2e: prints [READY] after all servers up"
assert_contains "$out" "https://localhost:8443" "e2e: tells user where to open the browser"
assert_contains "$out" "client_id=123456789012345678" "e2e: prints personalized invite URL"
assert_contains "$out" "If accessing this machine remotely" "e2e: includes remote-IP note"
assert_contains "$out" "discord.com/channels/@me" "e2e: prints general Discord servers link for testing"
assert_contains "$out" "./stop.sh" "e2e: mentions stop.sh"
assert_port 30000 "e2e: llama.cpp up"
assert_port 8443  "e2e: HTTPS up"
assert_pgrep "discord-bot.py" "e2e: discord bot up"
cleanup_servers
teardown

# --------------------------------------------------------------------------
echo
echo "================================================="
printf 'Passed: %d   Failed: %d\n' "$TESTS_PASS" "$TESTS_FAIL"
echo "================================================="
[ "$TESTS_FAIL" -eq 0 ]
