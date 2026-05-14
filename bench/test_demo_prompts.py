#!/usr/bin/env python3
"""Live Computex demo prompt regression against the local OpenAI-compatible LLM.

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

from prompts import VIDEO_CALL_PROMPT  # noqa: E402
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
        "max_tokens": 900,
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


def contains_any(haystack, needles):
    haystack = haystack.lower()
    return any(needle.lower() in haystack for needle in needles)


def joined_tool_items(args):
    items = args.get("items") or []
    if isinstance(items, str):
        try:
            parsed = json.loads(items)
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [items]
        except json.JSONDecodeError:
            items = [items]
    return " ".join(str(item) for item in items)


def check_no_private_health_leak(reply):
    lower = reply.lower()
    forbidden = [
        "blood pressure",
        "cholesterol",
        "hypertension",
        "diagnosis",
        "medication",
        "lisinopril",
    ]
    require(not any(term in lower for term in forbidden), f"privacy term leaked: {reply}")
    require(not re.search(r"\d", reply), f"raw digit leaked: {reply}")


def check_static_prompt_absence():
    stale = [
        "Polling MySQL for dashboard updates",
        "despite the late-night coding",
        "buy umbrella",
        "React/FastAPI/MySQL project dashboard we started",
        "add streaming updates",
        "write events table",
        "test reconnect",
        "spark-beat4",
        # Beat 1 now routes to html_assistant; the codebase_assistant tool stays
        # in tools.py but must not appear in the demo prompt's routing rules.
        "codebase_assistant",
        "WHEN TO USE codebase_assistant",
    ]
    for term in stale:
        require(term not in VIDEO_CALL_PROMPT, f"stale prompt term still active: {term}")
    require("html_assistant" in VIDEO_CALL_PROMPT, "missing html_assistant routing")
    require("WHEN TO USE html_assistant" in VIDEO_CALL_PROMPT, "missing WHEN TO USE html_assistant block")
    require("Turn this sketch into an MVP" in VIDEO_CALL_PROMPT, "missing sketch-to-MVP routing keyword")
    require("high mountain oolong tea" in VIDEO_CALL_PROMPT, "missing Computex gift memory")
    print("Static prompt absence: PASS")


def test_cold_open_variants(url, model):
    variants = [
        "Current video frame: the user is centered and visible, and the microphone is working. User asks: Hey, am I on camera?",
        "Current video frame: the user is visible at the laptop, and audio input is active. User asks: Can you see me and hear me?",
        "Current video frame: face is in frame and mic levels are moving. User asks: Are we live?",
    ]
    for idx, prompt in enumerate(variants, 1):
        message, elapsed = ask(url, model, [
            {"role": "system", "content": VIDEO_CALL_PROMPT},
            {"role": "user", "content": prompt},
        ])
        reply = text(message)
        require(not message.get("tool_calls"), f"unexpected tool call: {message}")
        require(
            contains_any(reply, ["camera", "see", "visible", "live", "frame"])
            and contains_any(reply, ["ready", "audio", "hear"]),
            f"cold open variant {idx} missed readiness: {reply!r}",
        )
        print(f"Cold open variant {idx}: PASS :: {reply} ({elapsed:.0f}ms)")


def test_codebase_build_variants(url, model):
    variants = [
        (
            "Hey Claw, please turn this sketch into an MVP. "
            "I'm going to dinner, write me a brief to review for when I get back."
        ),
        (
            "Please convert this sketch to an MVP. "
            "I'm going to dinner, write me a briefer review when I get back."
        ),
        (
            "Visible sketch: Agent Workbench dashboard with Project Brief, Agent Status, "
            "Action Items, and Activity Feed panels. Turn this sketch into an MVP. "
            "I'm going to dinner; write me a brief for when I get back."
        ),
        (
            "Visible whiteboard: Agent Monitor UI sends commands to an Agent Dashboard FastAPI server, "
            "which writes runs to Task History and streams an Activity Feed. Build this as a working local MVP."
        ),
        (
            "This diagram shows an Agent Monitoring system with dashboard cards, agent list, task history, "
            "and activity feed. Implement it as a runnable app with UI, API, persistence, and a brief."
        ),
    ]
    tools = tool_defs([
        "markdown_assistant",
        "html_assistant",
        "codebase_assistant",
        "reasoning_assistant",
        "workspace_update_assistant",
    ])
    for idx, prompt in enumerate(variants, 1):
        message, elapsed = ask(url, model, [
            {"role": "system", "content": VIDEO_CALL_PROMPT},
            {"role": "user", "content": prompt},
        ], tools=tools)
        name, args = tool_call(message)
        require(name == "codebase_assistant", f"variant {idx}: expected codebase_assistant, got {name}: {message}")
        joined = (args.get("task", "") + " " + args.get("context", "") + " " + args.get("output_dir", "")).lower()
        require(contains_any(joined, ["mvp", "app", "codebase", "fastapi", "dashboard"]), args)
        require(contains_any(joined, ["agent", "monitor", "history", "activity", "dashboard"]), args)
        print(f"Beat 1 codebase build variant {idx}: PASS :: {args} ({elapsed:.0f}ms)")


def test_mvp_brief_variants(url, model):
    variants = [
        (
            "I uploaded a simple Agent Workbench wireframe: left panel project brief, "
            "right panel agent status, lower action items and activity feed. Create an "
            "MVP brief I can review after dinner."
        ),
        (
            "This whiteboard shows an Agent Workbench dashboard for tracking agent status, "
            "action items, and recent activity. Create project scaffolding notes from it."
        ),
        (
            "Visible Agent Monitor diagram: Dashboard UI talks to a FastAPI Agent Service, "
            "which writes Task History and streams an Activity Feed. Document this as a README "
            "with architecture notes. Do not build it yet."
        ),
    ]
    tools = tool_defs([
        "markdown_assistant",
        "html_assistant",
        "codebase_assistant",
        "reasoning_assistant",
        "workspace_update_assistant",
    ])
    for idx, prompt in enumerate(variants, 1):
        message, elapsed = ask(url, model, [
            {"role": "system", "content": VIDEO_CALL_PROMPT},
            {"role": "user", "content": prompt},
        ], tools=tools)
        name, args = tool_call(message)
        require(name == "markdown_assistant", f"variant {idx}: expected markdown_assistant, got {name}: {message}")
        target = (args.get("output_path", "") + " " + args.get("task", "")).lower()
        context = (args.get("context", "") + " " + args.get("task", "")).lower()
        require(
            "brief" in target
            or "mvp" in target
            or "scaffold" in target
            or "readme" in target
            or args.get("output_path") in {"mvp_brief.md", "README.md"},
            args,
        )
        require(
            contains_any(
                context,
                [
                    "agent workbench",
                    "agent monitor",
                    "project brief",
                    "agent status",
                    "task history",
                    "activity feed",
                    "dashboard",
                ],
            ),
            args,
        )
        print(f"Beat 1 MVP brief variant {idx}: PASS :: {args} ({elapsed:.0f}ms)")


def test_html_prototype_trigger(url, model):
    message, elapsed = ask(url, model, [
        {"role": "system", "content": VIDEO_CALL_PROMPT},
        {
            "role": "user",
            "content": (
                "Visible sketch: Agent Workbench dashboard with Project Brief, Agent Status, "
                "Action Items, and Activity Feed. Build a single-page HTML prototype from this."
            ),
        },
    ], tools=tool_defs(["markdown_assistant", "html_assistant", "codebase_assistant", "workspace_update_assistant"]))
    name, args = tool_call(message)
    require(name == "html_assistant", f"expected html_assistant, got {name}: {message}")
    joined = (args.get("task", "") + " " + args.get("context", "")).lower()
    require(contains_any(joined, ["agent workbench", "dashboard", "prototype", "html"]), args)
    print(f"Beat 1 HTML prototype trigger: PASS :: {args} ({elapsed:.0f}ms)")


def test_private_menu_variants(url, model):
    variants = [
        (
            "Visible Chinese menu translations: braised beef, steamed vegetables, fried rice, "
            "beef noodle soup, and milk tea. Hey Claw, what should I order?",
            ["steamed", "vegetables", "braised beef"],
            ["beef", "fried", "rice", "noodle", "milk tea"],
        ),
        (
            "I'm at dinner in Taipei. The visible menu has steamed fish, braised vegetables, "
            "fried chicken cutlet, salty beef noodles, and sweet milk tea. Based on what you "
            "remember, pick something for me.",
            ["steamed", "fish", "braised", "vegetables"],
            ["fried", "cutlet", "noodle", "milk tea"],
        ),
        (
            "Menu in frame: steamed greens, rice, braised tofu, fried pork chop, and milk tea. "
            "What is the smart order tonight?",
            ["steamed", "greens", "braised", "tofu"],
            ["fried", "pork chop", "milk tea"],
        ),
    ]
    for idx, (prompt, preferred_terms, contrast_terms) in enumerate(variants, 1):
        message, elapsed = ask(url, model, [
            {"role": "system", "content": VIDEO_CALL_PROMPT},
            {"role": "user", "content": prompt},
        ])
        reply = text(message)
        lower = reply.lower()
        require(not message.get("tool_calls"), f"unexpected tool call: {message}")
        require(contains_any(lower, preferred_terms), reply)
        require(contains_any(lower, contrast_terms), reply)
        require(contains_any(lower, ["lighter", "salty", "saltier", "fried", "heavy", "heavier", "sweet"]), reply)
        check_no_private_health_leak(reply)
        print(f"Beat 2 private menu variant {idx}: PASS :: {reply} ({elapsed:.0f}ms)")


def test_executive_update_variants(url, model):
    variants = [
        (
            "Claw, update my team: the strategic alignment meeting went amazing. "
            "Our hardware partners agreed to invest if we prioritize the partner-facing MVP. "
            "Assign action items based on my team org chart. Also save a todo to buy pineapple cakes for my husband."
        ),
        (
            "Dinner went well. Send my team a concise update that the hardware partners are aligned "
            "if we focus the Agent Workbench MVP, assign next steps, and remind me to get pineapple cakes for my husband."
        ),
        (
            "We are in the Uber back. Draft the team update from dinner: partners are excited, "
            "investment depends on prioritizing the MVP path. Add action items and a souvenir todo for my husband."
        ),
    ]
    tools = tool_defs(["markdown_assistant", "html_assistant", "workspace_update_assistant", "reasoning_assistant"])
    for idx, prompt in enumerate(variants, 1):
        message, elapsed = ask(url, model, [
            {"role": "system", "content": VIDEO_CALL_PROMPT},
            {"role": "user", "content": prompt},
        ], tools=tools)
        name, args = tool_call(message)
        require(name == "workspace_update_assistant", f"variant {idx}: expected workspace_update_assistant, got {name}: {message}")
        joined = joined_tool_items(args) + " " + args.get("context", "") + " " + args.get("task", "")
        lower = joined.lower()
        require(contains_any(lower, ["team", "dinner", "strategic", "hardware", "partner", "mvp"]), args)
        require(contains_any(lower, ["pineapple", "souvenir", "husband", "oolong"]), args)
        print(f"Beat 3 executive update variant {idx}: PASS :: {args} ({elapsed:.0f}ms)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    print(f"computex demo prompt e2e: url={args.url} model={args.model}")
    tests = [
        lambda _url, _model: check_static_prompt_absence(),
        test_cold_open_variants,
        test_codebase_build_variants,
        test_mvp_brief_variants,
        test_html_prototype_trigger,
        test_private_menu_variants,
        test_executive_update_variants,
    ]
    failures = []
    for test in tests:
        try:
            test(args.url, args.model)
        except Exception as exc:
            name = getattr(test, "__name__", "static_check")
            failures.append((name, exc))
            print(f"{name}: FAIL :: {exc}", file=sys.stderr)

    if failures:
        print("\nFailures:", file=sys.stderr)
        for name, exc in failures:
            print(f"- {name}: {exc}", file=sys.stderr)
        return 1

    print("computex demo prompt e2e: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
