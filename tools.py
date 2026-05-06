"""Tool definitions and execution for OpenAI-compatible tool calling.

Two categories of tools:

1. **Inline tools** — executed server-side, return a string result that is appended
   as a `tool` message and fed back into the LLM. The model decides what to do
   with the output (read_file, write_file, list_files, run_python, web_search,
   remember_fact, recall_fact).

2. **UI agent tools** — return a sentinel JSON `{"agent_type": "...", "status":
   "initiated"}`. server.py detects these and opens the corresponding streaming
   UI panel (markdown editor, reasoning panel). These are kept for back-compat
   with the existing frontend.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote_plus

import aiohttp

from config import WORKSPACE_ROOT


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI format)
# ---------------------------------------------------------------------------

ALL_TOOLS: Dict[str, Dict[str, Any]] = {
    # ----- inline tools -----
    "read_file": {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the workspace. Use for inspecting code, notes, CSVs, or any user file before acting on it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace root."},
                    "max_bytes": {"type": "integer", "description": "Max bytes to read (default 64000).", "default": 64000},
                },
                "required": ["path"],
            },
        },
    },
    "write_file": {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a UTF-8 text file in the workspace. Use when the user asks to save, generate, or modify a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the workspace root."},
                    "content": {"type": "string", "description": "File contents."},
                },
                "required": ["path", "content"],
            },
        },
    },
    "list_files": {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and subdirectories at a workspace path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to workspace root. Defaults to '.'.", "default": "."},
                },
                "required": [],
            },
        },
    },
    "run_python": {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Execute a short Python snippet in a sandboxed interpreter. Use for math, data crunching, quick plots → returned as text (stdout). Do NOT use for persistent file I/O — use write_file instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python source to run. Anything printed to stdout is returned."},
                    "timeout_s": {"type": "integer", "description": "Max run time in seconds (default 15).", "default": 15},
                },
                "required": ["code"],
            },
        },
    },
    "web_search": {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and return the top results (title, URL, snippet). Use for current events, unfamiliar terms, or anything time-sensitive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {"type": "integer", "description": "Number of results to return (default 5).", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    "remember_fact": {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": "Store a small fact about the user or session for later recall (e.g. name, preference, project detail). Persists across sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Short identifier (e.g. 'user_name', 'favorite_lang')."},
                    "value": {"type": "string", "description": "The fact to remember."},
                },
                "required": ["key", "value"],
            },
        },
    },
    "recall_fact": {
        "type": "function",
        "function": {
            "name": "recall_fact",
            "description": "Recall a previously remembered fact by key, or list all stored facts if no key is given.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "The key to recall. If omitted, returns all facts."},
                },
                "required": [],
            },
        },
    },
    # Fast-path Claw tools (skip Claw's LLM and hit the skill CLI directly; ~35 ms).
    # Prefer these for common actions. Fall back to ask_claw only if no fast path fits.
    "add_todo": {
        "type": "function",
        "function": {
            "name": "add_todo",
            "description": (
                "Add a task to Kedar's TODO list (Claw's easy-todo skill) directly, "
                "without going through the Claw agent. Use this when the user says "
                "'add X to my todos', 'remind me to X', 'remember to X', or similar. "
                "Runs in ~35 ms. Prefer this over ask_claw for any todo-adding request."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title for the task."},
                    "notes": {"type": "string", "description": "Optional longer notes / context."},
                    "due":   {"type": "string", "description": "Optional due date (YYYY-MM-DD)."},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"], "description": "Optional priority."},
                    "tags":  {"type": "array", "items": {"type": "string"}, "description": "Optional tags."},
                },
                "required": ["title"],
            },
        },
    },
    "list_todos": {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": (
                "List Kedar's TODO items (Claw's easy-todo skill). Fast path — no Claw "
                "agent hop. Use when the user asks 'what's on my list', 'what's due "
                "today', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {"type": "string", "enum": ["all", "today", "upcoming", "completed", "recurring"],
                               "description": "Which subset to list. Default 'all'."},
                    "days":   {"type": "integer", "description": "For filter=upcoming, how many days out."},
                },
                "required": [],
            },
        },
    },
    "complete_todo": {
        "type": "function",
        "function": {
            "name": "complete_todo",
            "description": (
                "Mark a TODO item complete. Accepts either its id (like 'T17') or the full title. "
                "Fast path — no Claw agent hop."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id_or_title": {"type": "string", "description": "Todo id (T17) or title substring."},
                },
                "required": ["id_or_title"],
            },
        },
    },
    "claw_recall": {
        "type": "function",
        "function": {
            "name": "claw_recall",
            "description": (
                "Search Claw's persona/memory files (MEMORY.md, USER.md, "
                "SOUL.md) for something you don't already know from your "
                "system context. ONLY call this when the answer is not "
                "already in your prompt — most common Kedar facts (github "
                "handle, projects, preferences, identity) are already baked "
                "into your system prompt via persona injection and you "
                "should answer those directly without a tool call. Use this "
                "tool for later additions, deep grep, or when you're not "
                "sure. ~5 ms when you do need it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword(s) or short phrase. Returns matching lines plus 1 line of context above/below.",
                    },
                    "max_lines": {"type": "integer", "description": "Cap on lines returned (default 40).", "default": 40},
                },
                "required": ["query"],
            },
        },
    },
    "claw_remember": {
        "type": "function",
        "function": {
            "name": "claw_remember",
            "description": (
                "Persist a fact about Kedar / a preference / a decision into "
                "Claw's MEMORY.md so it sticks across sessions. Use when the "
                "user says 'remember that…', 'note that…', 'from now on…'. "
                "Appends a timestamped line."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "The thing to remember, phrased as Claw would write it (one short sentence).",
                    },
                    "section": {
                        "type": "string",
                        "description": "Optional H2 section header to file under. Defaults to 'Captured by realtime2'.",
                    },
                },
                "required": ["fact"],
            },
        },
    },
    "send_telegram": {
        "type": "function",
        "function": {
            "name": "send_telegram",
            "description": (
                "Send a Telegram message directly via Kedar's configured Claw bot. Fast "
                "path — no Claw agent hop, no LLM turn. Use for 'text/message/ping <person>' "
                "requests. Requires a Telegram chat_id (numeric) or one of Kedar's saved "
                "contact aliases. If you don't know the chat_id, delegate via ask_claw instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Message body."},
                    "chat_id": {"type": "string",
                                "description": "Telegram chat_id (numeric) or saved alias (e.g. 'kedar')."},
                },
                "required": ["text"],
            },
        },
    },
    "ask_claw": {
        "type": "function",
        "function": {
            "name": "ask_claw",
            "description": (
                "Delegate a real-world action or personal-assistant task to Claw, the local "
                "OpenClaw agent running on this machine. Claw has persistent memory of the "
                "user, access to their TODO list, calendar, messaging apps (Telegram, "
                "iMessage, Slack, Discord, WhatsApp), browser automation, and ~50 other "
                "skills. FALLBACK ONLY — prefer the fast-path tools (add_todo, list_todos, "
                "complete_todo, send_telegram) when they apply. Use ask_claw only if no fast "
                "path fits (e.g. web_search, cron reminders, apple-notes, custom skills). "
                "Claw takes 5-30 seconds."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": (
                            "The instruction for Claw, phrased as you would say it to a "
                            "personal assistant. Include any context from the current "
                            "conversation or what the camera sees — Claw does not see the "
                            "camera. Example: 'add \"buy the basil sauce I saw\" to my todo "
                            "list', or 'text Anja: running 10 minutes late'."
                        ),
                    },
                    "thinking": {
                        "type": "string",
                        "enum": ["off", "minimal", "low", "medium", "high"],
                        "description": "Reasoning effort. Default 'low' is fine; use 'medium' for planning-heavy asks.",
                    },
                },
                "required": ["message"],
            },
        },
    },

    # ----- UI agent tools (kept for back-compat with existing frontend) -----
    "markdown_assistant": {
        "type": "function",
        "function": {
            "name": "markdown_assistant",
            "description": "A markdown documentation assistant that writes README files, MVP briefs, design docs, guides, and other markdown documents into the shared workspace/ scratch folder. Use this when the user asks to convert a diagram, whiteboard, notes, or design into markdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The documentation task description, e.g. 'Write an MVP brief from this sketch' or 'Create API documentation for the user service'"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional context about the project or topic to document"
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional relative markdown path inside workspace/. Use 'mvp_brief.md' for the Computex Agent Workbench brief or 'README.md' for a project README."
                    }
                },
                "required": ["task"]
            }
        }
    },

    "html_assistant": {
        "type": "function",
        "function": {
            "name": "html_assistant",
            "description": "An HTML prototype assistant that creates a self-contained browser mockup from a sketch, dashboard description, or UI request. Use only when the user explicitly asks to build a webpage, HTML prototype, UI mockup, or visual MVP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The prototype task, e.g. 'Build a single-page Agent Workbench dashboard prototype'"
                    },
                    "context": {
                        "type": "string",
                        "description": "Visible sketch details or product requirements to include in the HTML prototype"
                    },
                },
                "required": ["task"],
            },
        },
    },

    "codebase_assistant": {
        "type": "function",
        "function": {
            "name": "codebase_assistant",
            "description": "Starts a local coding-agent workflow to build a runnable MVP codebase in workspace/ from a diagram or sketch. Use when the user asks to build, implement, develop, or create an MVP/app/system from a visible architecture or dashboard sketch, including requests that combine building the MVP with writing a brief for later review. The coding sub-agent should produce a concise FastAPI app, task-history store, and mvp_brief.md architecture brief, then local evaluation saves screenshots/logs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The implementation task, e.g. 'Build the Agent Monitoring MVP from this sketch'"
                    },
                    "context": {
                        "type": "string",
                        "description": "Visible sketch details, components, data flow, UI sections, and requirements to include in the generated MVP"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Optional single directory name under workspace/. Default: agent_monitor_mvp"
                    }
                },
                "required": ["task"],
            },
        },
    },

    "workspace_update_assistant": {
        "type": "function",
        "function": {
            "name": "workspace_update_assistant",
            "description": "Updates multiple files in the shared workspace/ scratch folder from executive updates, dinner debriefs, action items, and personal todos. Use this for Computex team updates and souvenir follow-ups. Do not use markdown_assistant for multi-file update routing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The workspace update request, e.g. 'Draft the team update and assign action items from dinner'"
                    },
                    "context": {
                        "type": "string",
                        "description": "Dinner debrief, team-update details, or visible notes plus any relevant project context"
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional extracted action items or personal todos. Preserve personal souvenir, husband, partner, pineapple-cake, or gift todos as separate items."
                    }
                },
                "required": ["task"],
            },
        },
    },
    "reasoning_assistant": {
        "type": "function",
        "function": {
            "name": "reasoning_assistant",
            "description": "ONLY for customer feedback / feature prioritization questions against local demo_files. Opens the streaming reasoning panel with thinking + conclusion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "problem": {"type": "string", "description": "The question to reason about."},
                    "context": {"type": "string", "description": "Optional extra context (e.g. a whiteboard description)."},
                    "analysis_type": {
                        "type": "string",
                        "enum": ["general", "comparison", "prioritization", "planning"],
                    },
                },
                "required": ["problem"],
            },
        },
    },
}


def get_enabled_tools(enabled_tool_ids: List[str]) -> List[Dict[str, Any]]:
    """Get list of tool definitions for enabled tool IDs."""
    return [ALL_TOOLS[tid] for tid in enabled_tool_ids if tid in ALL_TOOLS]


# ---------------------------------------------------------------------------
# Workspace path safety
# ---------------------------------------------------------------------------

def _resolve_safe(rel_path: str) -> Path:
    """Resolve a path inside WORKSPACE_ROOT, refusing to escape."""
    p = (WORKSPACE_ROOT / rel_path).resolve()
    try:
        p.relative_to(WORKSPACE_ROOT)
    except ValueError as e:
        raise ValueError(f"path escapes workspace root: {rel_path}") from e
    return p


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n\n[...truncated {len(s) - limit} chars...]"


# ---------------------------------------------------------------------------
# Inline tool implementations
# ---------------------------------------------------------------------------

async def _tool_read_file(args: Dict[str, Any]) -> str:
    path = args.get("path", "")
    max_bytes = int(args.get("max_bytes", 64000))
    try:
        p = _resolve_safe(path)
        if not p.exists():
            return json.dumps({"error": f"file not found: {path}"})
        if p.is_dir():
            return json.dumps({"error": f"path is a directory: {path}"})
        data = p.read_bytes()[:max_bytes]
        return json.dumps({
            "path": str(p.relative_to(WORKSPACE_ROOT)),
            "size_bytes": p.stat().st_size,
            "content": _truncate(data.decode("utf-8", errors="replace"), max_bytes),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


async def _tool_write_file(args: Dict[str, Any]) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    try:
        p = _resolve_safe(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return json.dumps({
            "path": str(p.relative_to(WORKSPACE_ROOT)),
            "size_bytes": p.stat().st_size,
            "ok": True,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


async def _tool_list_files(args: Dict[str, Any]) -> str:
    path = args.get("path", ".")
    try:
        p = _resolve_safe(path)
        if not p.exists():
            return json.dumps({"error": f"path not found: {path}"})
        if p.is_file():
            return json.dumps({"error": f"path is a file: {path}"})
        entries = []
        for child in sorted(p.iterdir())[:200]:
            entries.append({
                "name": child.name,
                "type": "dir" if child.is_dir() else "file",
                "size_bytes": child.stat().st_size if child.is_file() else None,
            })
        return json.dumps({"path": str(p.relative_to(WORKSPACE_ROOT)) or ".", "entries": entries})
    except Exception as e:
        return json.dumps({"error": str(e)})


async def _tool_run_python(args: Dict[str, Any]) -> str:
    code = args.get("code", "")
    timeout_s = int(args.get("timeout_s", 15))
    try:
        # Prefer llm-sandbox if available (Docker-backed, safer). Fall back to a
        # subprocess with a short timeout if llm-sandbox isn't importable (dev).
        try:
            from llm_sandbox import SandboxSession
            return await asyncio.to_thread(_run_in_sandbox, code, timeout_s)
        except ImportError:
            return await _run_subprocess_python(code, timeout_s)
    except Exception as e:
        return json.dumps({"error": f"run_python failed: {e}"})


def _run_in_sandbox(code: str, timeout_s: int) -> str:
    from llm_sandbox import SandboxSession
    started = time.perf_counter()
    with SandboxSession(lang="python", verbose=False) as sess:
        result = sess.run(code)
    elapsed_ms = (time.perf_counter() - started) * 1000
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    exit_code = getattr(result, "exit_code", None)
    return json.dumps({
        "stdout": _truncate(stdout, 8000),
        "stderr": _truncate(stderr, 2000),
        "exit_code": exit_code,
        "elapsed_ms": round(elapsed_ms, 1),
        "backend": "llm-sandbox",
    })


async def _run_subprocess_python(code: str, timeout_s: int) -> str:
    proc = await asyncio.create_subprocess_exec(
        "python3", "-I", "-c", code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    started = time.perf_counter()
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        return json.dumps({"error": f"run_python timed out after {timeout_s}s", "backend": "subprocess"})
    return json.dumps({
        "stdout": _truncate(stdout_b.decode("utf-8", errors="replace"), 8000),
        "stderr": _truncate(stderr_b.decode("utf-8", errors="replace"), 2000),
        "exit_code": proc.returncode,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "backend": "subprocess",
    })


async def _tool_web_search(args: Dict[str, Any]) -> str:
    """Web search — DuckDuckGo HTML (POST) with Wikipedia fallback. No API key."""
    query = args.get("query", "")
    max_results = int(args.get("max_results", 5))
    if not query.strip():
        return json.dumps({"error": "empty query"})

    ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/120.0.0.0 Safari/537.36")
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    html = None
    err = None
    try:
        async with aiohttp.ClientSession() as sess:
            # DDG lite endpoint is more forgiving than the main /html/
            async with sess.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "us-en"},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    html = await r.text()
                else:
                    err = f"DDG HTTP {r.status}"
    except Exception as e:
        err = f"DDG failed: {e}"

    if html:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            results = []
            for block in soup.select(".result")[:max_results * 2]:
                a = block.select_one(".result__a")
                snip = block.select_one(".result__snippet")
                if not a:
                    continue
                results.append({
                    "title": a.get_text(strip=True),
                    "url": a.get("href", ""),
                    "snippet": _truncate(snip.get_text(" ", strip=True) if snip else "", 280),
                })
                if len(results) >= max_results:
                    break
            if results:
                return json.dumps({"query": query, "results": results, "source": "duckduckgo"})
        except ImportError:
            pass  # fall through to wikipedia fallback

    # Fallback: Wikipedia REST opensearch — always works, no auth
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": query, "limit": str(max_results), "format": "json"},
                headers={"User-Agent": ua},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    return json.dumps({"error": f"wikipedia HTTP {r.status}", "ddg_error": err})
                data = await r.json()
        titles, descs, urls = data[1], data[2], data[3]
        results = [
            {"title": t, "url": u, "snippet": _truncate(d, 280)}
            for t, d, u in zip(titles, descs, urls)
        ]
        return json.dumps({"query": query, "results": results, "source": "wikipedia", "note": err})
    except Exception as e:
        return json.dumps({"error": f"search failed: ddg={err} wiki={e}"})


# ---------------------------------------------------------------------------
# Memory tool (sqlite)
# ---------------------------------------------------------------------------

_MEMORY_DB_PATH = WORKSPACE_ROOT / "audio_cache" / "memory.db"


def _memory_conn() -> sqlite3.Connection:
    _MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_MEMORY_DB_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS facts (
        key     TEXT PRIMARY KEY,
        value   TEXT NOT NULL,
        updated REAL NOT NULL
    )""")
    return conn


async def _tool_remember_fact(args: Dict[str, Any]) -> str:
    key = (args.get("key") or "").strip()
    value = args.get("value") or ""
    if not key:
        return json.dumps({"error": "key required"})
    def _work():
        with _memory_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO facts(key, value, updated) VALUES (?, ?, ?)",
                (key, value, time.time()),
            )
    await asyncio.to_thread(_work)
    return json.dumps({"ok": True, "key": key})


async def _tool_recall_fact(args: Dict[str, Any]) -> str:
    key = (args.get("key") or "").strip()
    def _work():
        with _memory_conn() as conn:
            if key:
                row = conn.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
                return {"key": key, "value": row[0] if row else None}
            rows = conn.execute("SELECT key, value FROM facts ORDER BY key").fetchall()
            return {"facts": [{"key": k, "value": v} for k, v in rows]}
    out = await asyncio.to_thread(_work)
    return json.dumps(out)


# ---------------------------------------------------------------------------
# Claw fast-path tools — hit the skill CLIs directly, skip the Claw LLM turn
# ---------------------------------------------------------------------------

CLAW_WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", os.path.expanduser("~/.openclaw/workspace")))
CLAW_CONFIG_JSON = Path(os.environ.get("OPENCLAW_CONFIG", os.path.expanduser("~/.openclaw/openclaw.json")))
EASY_TODO_CLI = CLAW_WORKSPACE / "skills" / "easy-todo" / "cli.js"


async def _run_cmd(argv: List[str], timeout_s: int = 15) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try: proc.kill()
        except Exception: pass
        return {"error": f"command timed out after {timeout_s}s", "argv": argv}
    return {
        "stdout": out_b.decode("utf-8", errors="replace").strip(),
        "stderr": err_b.decode("utf-8", errors="replace").strip(),
        "exit_code": proc.returncode,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


async def _tool_add_todo(args: Dict[str, Any]) -> str:
    title = (args.get("title") or "").strip()
    if not title:
        return json.dumps({"error": "title required"})
    if not EASY_TODO_CLI.exists():
        return json.dumps({"error": f"easy-todo cli not found at {EASY_TODO_CLI}"})
    argv = ["node", str(EASY_TODO_CLI), "add", title]
    if args.get("due"):      argv += ["--due", str(args["due"])]
    if args.get("priority"): argv += ["--priority", str(args["priority"])]
    if args.get("notes"):    argv += ["--notes", str(args["notes"])]
    tags = args.get("tags")
    if tags:
        if isinstance(tags, list): tags = ",".join(str(t) for t in tags)
        argv += ["--tags", str(tags)]
    r = await _run_cmd(argv)
    if r.get("error"): return json.dumps(r)
    # Easy-todo prints "Added T<id>: <title> [priority]"
    return json.dumps({
        "ok": r["exit_code"] == 0,
        "message": r["stdout"] or r["stderr"],
        "elapsed_ms": r["elapsed_ms"],
    })


async def _tool_list_todos(args: Dict[str, Any]) -> str:
    if not EASY_TODO_CLI.exists():
        return json.dumps({"error": f"easy-todo cli not found at {EASY_TODO_CLI}"})
    argv = ["node", str(EASY_TODO_CLI), "list"]
    flt = (args.get("filter") or "all").lower()
    if flt == "today":      argv.append("--today")
    elif flt == "upcoming":
        argv.append("--upcoming")
        if args.get("days"): argv += ["--days", str(int(args["days"]))]
    elif flt == "completed": argv.append("--completed")
    elif flt == "recurring": argv.append("--recurring")
    r = await _run_cmd(argv)
    if r.get("error"): return json.dumps(r)
    return json.dumps({
        "ok": r["exit_code"] == 0,
        "list": _truncate(r["stdout"], 3000),
        "elapsed_ms": r["elapsed_ms"],
    })


async def _tool_complete_todo(args: Dict[str, Any]) -> str:
    ref = (args.get("id_or_title") or "").strip()
    if not ref:
        return json.dumps({"error": "id_or_title required"})
    if not EASY_TODO_CLI.exists():
        return json.dumps({"error": f"easy-todo cli not found at {EASY_TODO_CLI}"})
    r = await _run_cmd(["node", str(EASY_TODO_CLI), "complete", ref])
    if r.get("error"): return json.dumps(r)
    return json.dumps({
        "ok": r["exit_code"] == 0,
        "message": r["stdout"] or r["stderr"],
        "elapsed_ms": r["elapsed_ms"],
    })


CLAW_MEMORY_MD = CLAW_WORKSPACE / "MEMORY.md"
CLAW_USER_MD   = CLAW_WORKSPACE / "USER.md"
CLAW_SOUL_MD   = CLAW_WORKSPACE / "SOUL.md"


async def _tool_claw_recall(args: Dict[str, Any]) -> str:
    q = (args.get("query") or "").strip().lower()
    if not q:
        return json.dumps({"error": "query required"})
    max_lines = int(args.get("max_lines") or 40)
    hits: List[Dict[str, Any]] = []
    for src in (CLAW_MEMORY_MD, CLAW_USER_MD, CLAW_SOUL_MD):
        if not src.exists():
            continue
        try:
            lines = src.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            if q in line.lower():
                lo = max(0, i - 1)
                hi = min(len(lines), i + 2)
                snippet = "\n".join(lines[lo:hi]).strip()
                hits.append({"file": src.name, "line": i + 1, "match": snippet})
                if len(hits) >= max_lines:
                    break
        if len(hits) >= max_lines:
            break
    return json.dumps({
        "query": q,
        "hits": hits,
        "n": len(hits),
    })


async def _tool_claw_remember(args: Dict[str, Any]) -> str:
    fact = (args.get("fact") or "").strip()
    if not fact:
        return json.dumps({"error": "fact required"})
    section = (args.get("section") or "Captured by realtime2").strip()
    try:
        CLAW_MEMORY_MD.parent.mkdir(parents=True, exist_ok=True)
        existing = CLAW_MEMORY_MD.read_text(encoding="utf-8") if CLAW_MEMORY_MD.exists() else ""
        ts = time.strftime("%Y-%m-%d")
        header = f"## {section}"
        new_line = f"- {ts}: {fact}"
        if header in existing:
            # append under the section header (just before the next H2 or EOF)
            updated_lines: List[str] = []
            inserted = False
            in_section = False
            for line in existing.splitlines():
                if line.startswith(header):
                    in_section = True
                    updated_lines.append(line)
                    continue
                if in_section and line.startswith("## "):
                    if not inserted:
                        updated_lines.append(new_line)
                        inserted = True
                    in_section = False
                updated_lines.append(line)
            if in_section and not inserted:
                updated_lines.append(new_line)
                inserted = True
            CLAW_MEMORY_MD.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")
        else:
            with CLAW_MEMORY_MD.open("a", encoding="utf-8") as f:
                if existing and not existing.endswith("\n"):
                    f.write("\n")
                f.write(f"\n{header}\n{new_line}\n")
        return json.dumps({"ok": True, "fact": fact, "section": section, "file": str(CLAW_MEMORY_MD)})
    except Exception as e:
        return json.dumps({"error": f"claw_remember failed: {e}"})


def _load_telegram_config() -> Dict[str, Any]:
    try:
        d = json.loads(CLAW_CONFIG_JSON.read_text())
    except Exception:
        return {}
    tg = (d.get("channels") or {}).get("telegram") or {}
    return tg


async def _tool_send_telegram(args: Dict[str, Any]) -> str:
    text = (args.get("text") or "").strip()
    chat_id = (args.get("chat_id") or "").strip()
    if not text:
        return json.dumps({"error": "text required"})
    tg = _load_telegram_config()
    token = tg.get("botToken")
    if not token:
        return json.dumps({"error": "no Telegram bot token configured in openclaw.json"})
    # Resolve alias → chat_id via TOOLS.md / contacts if present
    if chat_id and not chat_id.lstrip("-").isdigit():
        resolved = _resolve_telegram_alias(tg, chat_id)
        if not resolved:
            return json.dumps({
                "error": f"unknown alias '{chat_id}'; pass a numeric chat_id or fall back to ask_claw"
            })
        chat_id = resolved
    if not chat_id:
        # Best guess: first allowFrom entry (usually the owner's DM)
        candidates = tg.get("allowFrom") or tg.get("dmAllowFrom") or []
        if candidates:
            chat_id = str(candidates[0])
    if not chat_id:
        return json.dumps({"error": "chat_id required and no default found in openclaw config"})
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                body = await r.json()
                ok = body.get("ok", False)
                return json.dumps({
                    "ok": ok,
                    "chat_id": chat_id,
                    "error": None if ok else body.get("description", f"HTTP {r.status}"),
                })
    except Exception as e:
        return json.dumps({"error": f"telegram send failed: {e}"})


def _resolve_telegram_alias(tg: Dict[str, Any], alias: str) -> str | None:
    """Look up a saved contact/alias → chat_id in openclaw.json."""
    alias = alias.lower()
    contacts = tg.get("contacts") or tg.get("aliases") or {}
    if isinstance(contacts, dict):
        # direct key lookup
        for k, v in contacts.items():
            if str(k).lower() == alias:
                return str(v)
    pairings = tg.get("pairings") or {}
    if isinstance(pairings, dict):
        for v in pairings.values():
            if isinstance(v, dict) and str(v.get("alias", "")).lower() == alias:
                cid = v.get("chatId") or v.get("chat_id")
                if cid: return str(cid)
    return None


# ---------------------------------------------------------------------------
# OpenClaw bridge (ask_claw)
# ---------------------------------------------------------------------------

# Known openclaw CLI locations. Env override wins; then PATH; then common installs.
_OPENCLAW_CANDIDATES = [
    os.environ.get("OPENCLAW_BIN"),
    "openclaw",
    "/home/nvidia/.nvm/versions/node/v22.22.1/bin/openclaw",
    "/usr/local/bin/openclaw",
]


def _find_openclaw() -> str | None:
    import shutil
    for c in _OPENCLAW_CANDIDATES:
        if not c:
            continue
        if "/" in c and Path(c).exists():
            return c
        p = shutil.which(c)
        if p:
            return p
    return None


async def _tool_ask_claw(args: Dict[str, Any]) -> str:
    message = (args.get("message") or "").strip()
    thinking = args.get("thinking") or "low"
    if not message:
        return json.dumps({"error": "message required"})

    # Primary path: ACP bridge (persistent, streams, ~2 s warm).
    # Fallback: CLI subprocess (~24 s) — only on ACP startup failure.
    if os.environ.get("OPENCLAW_DISABLE_ACP", "").lower() not in ("1", "true", "yes"):
        try:
            claw_acp = sys.modules.get("clients.claw_acp")
            if claw_acp is None:
                # Direct module import — bypass clients/__init__ which pulls in
                # soundfile/torch/etc. just to expose ASR helpers.
                import importlib.util
                _spec = importlib.util.spec_from_file_location(
                    "clients.claw_acp",
                    str(Path(__file__).parent / "clients" / "claw_acp.py"),
                )
                claw_acp = importlib.util.module_from_spec(_spec)
                sys.modules["clients.claw_acp"] = claw_acp
                _spec.loader.exec_module(claw_acp)
            bridge = await claw_acp.get_singleton()
            chunks: List[str] = []
            t0 = time.perf_counter()
            async for chunk in bridge.prompt(message, timeout_s=120.0):
                chunks.append(chunk)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            reply = _truncate("".join(chunks).strip() or "(no reply)", 4000)
            return json.dumps({
                "reply": reply,
                "elapsed_ms": round(elapsed_ms, 1),
                "transport": "acp",
            })
        except Exception as e:
            print(f"[ask_claw] ACP failed ({e}); falling back to CLI")
            # fall through to CLI

    claw = _find_openclaw()
    if not claw:
        return json.dumps({
            "error": "openclaw CLI not found; set OPENCLAW_BIN or install openclaw",
        })
    agent = os.environ.get("OPENCLAW_AGENT", "main")
    timeout_s = int(os.environ.get("OPENCLAW_TIMEOUT", "120"))
    cmd = [
        claw, "agent", "--local", "--agent", agent,
        "--message", message,
        "--thinking", thinking,
        "--json", "--timeout", str(timeout_s),
    ]
    t0 = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s + 10)
    except asyncio.TimeoutError:
        try: proc.kill()
        except Exception: pass
        return json.dumps({"error": f"claw timed out after {timeout_s}s"})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if proc.returncode != 0:
        return json.dumps({
            "error": f"openclaw exit {proc.returncode}",
            "stderr": _truncate(stderr_b.decode("utf-8", errors="replace"), 600),
            "elapsed_ms": round(elapsed_ms, 1),
        })
    # OpenClaw may print ANSI banners to stdout before the JSON; scan for the
    # first '{' that starts a valid top-level object.
    raw = stdout_b.decode("utf-8", errors="replace")
    start = raw.find("{")
    parsed = None
    if start != -1:
        try:
            parsed = json.loads(raw[start:])
        except json.JSONDecodeError:
            pass
    if parsed is None:
        return json.dumps({
            "error": "could not parse openclaw JSON output",
            "tail": _truncate(raw[-400:], 400),
            "elapsed_ms": round(elapsed_ms, 1),
        })
    # Canonical reply lives at payloads[0].text (observed for qwen3.6 via local-proxy)
    reply_parts = []
    for p in parsed.get("payloads") or []:
        t = p.get("text")
        if isinstance(t, str) and t.strip():
            reply_parts.append(t.strip())
    stop = ((parsed.get("agent") or {}).get("result") or {}).get("stopReason")
    return json.dumps({
        "reply": _truncate("\n\n".join(reply_parts) or "(no reply)", 4000),
        "stop_reason": stop,
        "elapsed_ms": round(elapsed_ms, 1),
        "transport": "cli",
    })


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_INLINE_DISPATCH = {
    "read_file":     _tool_read_file,
    "write_file":    _tool_write_file,
    "list_files":    _tool_list_files,
    "run_python":    _tool_run_python,
    "web_search":    _tool_web_search,
    "remember_fact": _tool_remember_fact,
    "recall_fact":   _tool_recall_fact,
    # Claw fast-paths — direct skill CLIs, no Claw LLM hop (~35 ms)
    "add_todo":       _tool_add_todo,
    "list_todos":     _tool_list_todos,
    "complete_todo":  _tool_complete_todo,
    "send_telegram":  _tool_send_telegram,
    # Direct memory access — no LLM hop, no skill CLI, just file I/O
    "claw_recall":    _tool_claw_recall,
    "claw_remember":  _tool_claw_remember,
    # Fallback — goes through Claw's full agent loop (~20 s)
    "ask_claw":      _tool_ask_claw,
}


def is_agent_tool(tool_name: str) -> bool:
    """UI-dispatched agent tools return a sentinel payload; loop should not re-prompt."""
    return tool_name in ("markdown_assistant", "html_assistant", "codebase_assistant", "reasoning_assistant", "workspace_update_assistant")


async def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Execute a tool and return its result as a JSON string."""
    if tool_name in _INLINE_DISPATCH:
        try:
            return await _INLINE_DISPATCH[tool_name](arguments or {})
        except Exception as e:
            return json.dumps({"error": f"{tool_name} failed: {e}"})

    # UI agent tools — sentinel response, server.py opens the UI
    if tool_name == "markdown_assistant":
        task = arguments.get("task", "")
        context = arguments.get("context", "")
        output_path = arguments.get("output_path", "")
        return json.dumps({
            "agent_type": "markdown_assistant",
            "task": task,
            "context": context,
            "output_path": output_path,
            "status": "initiated"
        })
    if tool_name == "html_assistant":
        return json.dumps({
            "agent_type": "html_assistant",
            "task": arguments.get("task", ""),
            "context": arguments.get("context", ""),
            "status": "initiated",
        })
    if tool_name == "codebase_assistant":
        return json.dumps({
            "agent_type": "codebase_assistant",
            "task": arguments.get("task", ""),
            "context": arguments.get("context", ""),
            "output_dir": arguments.get("output_dir", "agent_monitor_mvp"),
            "status": "initiated",
        })
    if tool_name == "reasoning_assistant":
        return json.dumps({
            "agent_type": "reasoning_assistant",
            "problem": arguments.get("problem", ""),
            "context": arguments.get("context", ""),
            "analysis_type": arguments.get("analysis_type", "general"),
            "status": "initiated",
        })

    if tool_name == "workspace_update_assistant":
        task = arguments.get("task", "")
        context = arguments.get("context", "")
        items = arguments.get("items", [])
        return json.dumps({
            "agent_type": "workspace_update_assistant",
            "task": task,
            "context": context,
            "items": items if isinstance(items, list) else [],
            "status": "initiated"
        })

    return json.dumps({"error": f"unknown tool: {tool_name}"})
