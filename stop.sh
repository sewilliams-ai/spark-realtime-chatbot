#!/bin/bash
# Stop the three spark-realtime-chatbot servers started by setup.sh
# (llama.cpp :30000, HTTPS :8443, Discord bot), leaving all build/download
# artifacts — venv, llama.cpp build, downloaded models — intact.
#
# Targets the PID files setup.sh writes to logs/, and falls back to matching by
# listening port / process name if a PID file is missing or stale.

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
LOG_DIR="${LOG_DIR:-$REPO_DIR/logs}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RESET=$'\033[0m'
else
    C_GREEN=''; C_YELLOW=''; C_RESET=''
fi
log_ok()   { printf '%s[OK]%s %s\n'   "$C_GREEN"  "$C_RESET" "$*"; }
log_info() { printf '%s[INFO]%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }

# Stop a process recorded in a PID file. Returns 0 if it stopped something.
stop_pidfile() { # pidfile name
    local pidfile="$1" name="$2" pid
    if [ -f "$pidfile" ]; then
        pid="$(cat "$pidfile" 2>/dev/null)"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            rm -f "$pidfile"
            log_ok "Stopped $name (pid $pid)."
            return 0
        fi
        rm -f "$pidfile"   # stale file
    fi
    return 1
}

# Fallback: stop whatever is listening on a port.
stop_port() { # port name
    local port="$1" name="$2" pid
    pid="$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -oP 'pid=\K[0-9]+' | head -1)"
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null
        log_ok "Stopped $name on :$port (pid $pid)."
        return 0
    fi
    return 1
}

log_info "Stopping spark-realtime-chatbot servers (artifacts are left intact)..."

stop_pidfile "$LOG_DIR/llama.pid" "llama.cpp server" || stop_port 30000 "llama.cpp server" \
    || log_info "llama.cpp server not running."

stop_pidfile "$LOG_DIR/https.pid" "HTTPS server" || stop_port 8443 "HTTPS server" \
    || log_info "HTTPS server not running."

if stop_pidfile "$LOG_DIR/discord.pid" "Discord bot"; then
    :
elif pkill -f "clients/discord-bot.py" 2>/dev/null; then
    log_ok "Stopped Discord bot."
else
    log_info "Discord bot not running."
fi

log_ok "Done. Models, venv, and llama.cpp build are untouched — re-run ./setup.sh to restart."
