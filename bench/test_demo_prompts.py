#!/usr/bin/env python3
"""Live demo prompt regression against the local OpenAI-compatible LLM.

Run:
  .venv-gpu/bin/python bench/test_demo_prompts.py
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompts import DEFAULT_SYSTEM_PROMPT, VIDEO_CALL_PROMPT  # noqa: E402
from tools import ALL_TOOLS  # noqa: E402


DEFAULT_URL = os.getenv("LLM_SERVER_URL", "http://localhost:11434/v1/chat/completions")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen3.6:35b-a3b")


def post_chat(url, payload, timeout):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def tool_defs(names):
    return [ALL_TOOLS[name] for name in names]


def tool_call(message):
    calls = message.get("tool_calls") or []
    if not calls:
        return None, {}
    call = calls[0]
    name = call.get("function", {}).get("name", "")
    raw_args = call.get("function", {}).get("arguments") or "{}"
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        args = {}
    return name, args


def text(message):
    return (message.get("content") or "").strip()


def ask(url, model, messages, tools=None, timeout=90):
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "max_tokens": 800,
        "reasoning_effort": "none",
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    started = time.perf_counter()
    response = post_chat(url, payload, timeout)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return response["choices"][0]["message"], elapsed_ms


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def contains_all(haystack, needles):
    haystack = haystack.lower()
    return all(needle.lower() in haystack for needle in needles)


def test_cold_open(url, model):
    message, elapsed = ask(url, model, [
        {"role": "system", "content": VIDEO_CALL_PROMPT},
        {
            "role": "user",
            "content": (
                "Current video frame: the user is centered and visible, and the microphone is working. "
                "User asks: Can you see me and hear me?"
            ),
        },
    ])
    reply = text(message)
    require(not message.get("tool_calls"), f"unexpected tool call: {message}")
    require(
        ("camera" in reply.lower() or "see" in reply.lower() or "visible" in reply.lower())
        and ("ready" in reply.lower() or "audio" in reply.lower() or "hear" in reply.lower()),
        f"cold open reply missed camera/audio readiness: {reply!r}",
    )
    print(f"Cold open: PASS :: {reply} ({elapsed:.0f}ms)")


def test_readme_tool(url, model):
    message, elapsed = ask(url, model, [
        {"role": "system", "content": VIDEO_CALL_PROMPT},
        {
            "role": "user",
            "content": (
                "Visible whiteboard: React frontend -> FastAPI backend -> MySQL database. "
                "Convert this hand-drawn architecture into a Markdown README."
            ),
        },
    ], tools=tool_defs(["markdown_assistant", "reasoning_assistant", "workspace_update_assistant"]))
    name, args = tool_call(message)
    require(name == "markdown_assistant", f"expected markdown_assistant, got {name}: {message}")
    require("readme" in (args.get("output_path", "") + args.get("task", "")).lower(), f"missing README target: {args}")
    require(
        contains_all(args.get("context", ""), ["React", "FastAPI", "MySQL"]),
        f"missing visible architecture context: {args}",
    )
    print(f"Beat 1 README tool: PASS :: {args} ({elapsed:.0f}ms)")


def test_architecture_improvement(url, model):
    message, elapsed = ask(url, model, [
        {"role": "system", "content": VIDEO_CALL_PROMPT},
        {
            "role": "user",
            "content": "Visible whiteboard: React Dashboard -> FastAPI -> MySQL. What would you improve?",
        },
    ], tools=tool_defs(["markdown_assistant", "reasoning_assistant", "workspace_update_assistant"]))
    reply = text(message)
    require(not message.get("tool_calls"), f"expected direct answer, got tool call: {message}")
    require("redis" in reply.lower() and ("pub/sub" in reply.lower() or "pubsub" in reply.lower()), reply)
    require("mysql" in reply.lower(), reply)
    print(f"Beat 1 improvement: PASS :: {reply} ({elapsed:.0f}ms)")


def test_realtime_design_followup(url, model):
    message, elapsed = ask(url, model, [
        {"role": "system", "content": VIDEO_CALL_PROMPT},
        {
            "role": "user",
            "content": "Visible whiteboard: React Dashboard -> FastAPI -> MySQL. What would you improve?",
        },
        {
            "role": "assistant",
            "content": (
                "Polling MySQL for dashboard updates won't scale. I'd keep MySQL as the source of truth, "
                "but add Redis pub/sub between FastAPI instances for realtime fanout. I can sketch that design."
            ),
        },
        {"role": "user", "content": "Yeah, do it."},
    ], tools=tool_defs(["markdown_assistant", "reasoning_assistant", "workspace_update_assistant"]))
    name, args = tool_call(message)
    require(name == "markdown_assistant", f"expected markdown_assistant, got {name}: {message}")
    target = (args.get("output_path", "") + args.get("task", "")).lower()
    require("realtime" in target or "real-time" in target, f"missing realtime target: {args}")
    require("redis" in (args.get("context", "") + args.get("task", "")).lower(), f"missing Redis context: {args}")
    print(f"Beat 1 realtime design tool: PASS :: {args} ({elapsed:.0f}ms)")


def test_fashion(url, model):
    message, elapsed = ask(url, model, [
        {"role": "system", "content": VIDEO_CALL_PROMPT},
        {
            "role": "user",
            "content": (
                "Current video frame: I am wearing a dark navy top and jacket after late-night coding. "
                "Does this outfit work for video calls?"
            ),
        },
    ])
    reply = text(message)
    require(not message.get("tool_calls"), f"unexpected tool call: {message}")
    lower = reply.lower()
    require(("professional" in lower or "put together" in lower) and ("navy" in lower or "dark" in lower), reply)
    print(f"Beat 2 fashion: PASS :: {reply} ({elapsed:.0f}ms)")


def test_private_menu(url, model):
    message, elapsed = ask(url, model, [
        {"role": "system", "content": VIDEO_CALL_PROMPT},
        {
            "role": "user",
            "content": (
                "Visible menu items: braised vegetables listed as steamed and light, steamed rice, "
                "beef noodle soup listed as salty broth, and fried pork chops listed as fried. "
                "What should I order for a lighter lunch today?"
            ),
        },
    ])
    reply = text(message)
    lower = reply.lower()
    forbidden = [
        "blood pressure",
        "cholesterol",
        "hypertension",
        "diagnosis",
        "medication",
    ]
    require(not message.get("tool_calls"), f"unexpected tool call: {message}")
    require(("braised" in lower or "vegetable" in lower or "rice" in lower), reply)
    require(("beef noodle" in lower or "fried pork" in lower), reply)
    require(("salty" in lower or "fried" in lower or "heavy" in lower or "lighter" in lower), reply)
    require(not any(term in lower for term in forbidden), f"privacy term leaked: {reply}")
    require(not re.search(r"\d", reply), f"raw digit leaked: {reply}")
    print(f"Beat 3 menu: PASS :: {reply} ({elapsed:.0f}ms)")


def test_workspace_todos(url, model):
    items = [
        "add streaming updates",
        "Redis pub/sub",
        "write events table",
        "React hook",
        "test reconnect",
        "buy umbrella",
    ]
    message, elapsed = ask(url, model, [
        {"role": "system", "content": VIDEO_CALL_PROMPT},
        {
            "role": "user",
            "content": (
                "Visible handwritten note lists: add streaming updates; Redis pub/sub; write events table; "
                "React hook; test reconnect; buy umbrella. Add these to the project."
            ),
        },
    ], tools=tool_defs(["markdown_assistant", "workspace_update_assistant", "reasoning_assistant"]))
    name, args = tool_call(message)
    require(name == "workspace_update_assistant", f"expected workspace_update_assistant, got {name}: {message}")
    joined = " ".join(args.get("items") or []) + " " + args.get("context", "") + " " + args.get("task", "")
    for item in items:
        require(item.lower() in joined.lower(), f"missing item {item!r}: {args}")
    print(f"Beat 4 todo routing tool: PASS :: {args} ({elapsed:.0f}ms)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    print(f"demo prompt e2e: url={args.url} model={args.model}")
    tests = [
        test_cold_open,
        test_readme_tool,
        test_architecture_improvement,
        test_realtime_design_followup,
        test_fashion,
        test_private_menu,
        test_workspace_todos,
    ]
    failures = []
    for test in tests:
        try:
            test(args.url, args.model)
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f"{test.__name__}: FAIL :: {exc}", file=sys.stderr)

    if failures:
        print("\nFailures:", file=sys.stderr)
        for name, exc in failures:
            print(f"- {name}: {exc}", file=sys.stderr)
        return 1

    print("demo prompt e2e: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
