#!/usr/bin/env python3
"""Live VLM prompt test for the Computex whiteboard MVP beat.

Run:
  .venv-gpu/bin/python bench/test_whiteboard_image_prompt.py
"""
import argparse
import base64
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prompts import VIDEO_CALL_PROMPT  # noqa: E402
from tools import ALL_TOOLS  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE_PATH = REPO_ROOT / "test_assets" / "agent_workbench_whiteboard.png"
DEFAULT_URL = os.getenv("LLM_SERVER_URL", "http://localhost:11434/v1/chat/completions")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "qwen3.6:35b-a3b")


def font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def jittered_line(draw, points, color, width=4, repeats=2, jitter=3):
    rng = random.Random(42 + len(points) + width)
    for _ in range(repeats):
        shifted = [(x + rng.randint(-jitter, jitter), y + rng.randint(-jitter, jitter)) for x, y in points]
        draw.line(shifted, fill=color, width=width, joint="curve")


def jittered_rect(draw, box, color, width=5):
    x1, y1, x2, y2 = box
    jittered_line(draw, [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)], color, width=width)


def arrow(draw, start, end, color=(45, 68, 110), width=5):
    jittered_line(draw, [start, end], color, width=width)
    sx, sy = start
    ex, ey = end
    dx = ex - sx
    dy = ey - sy
    length = max((dx * dx + dy * dy) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    size = 24
    left = (ex - ux * size + px * size * 0.55, ey - uy * size + py * size * 0.55)
    right = (ex - ux * size - px * size * 0.55, ey - uy * size - py * size * 0.55)
    jittered_line(draw, [left, (ex, ey), right], color, width=width)


def draw_note(draw, box, title, lines, accent):
    x1, y1, x2, y2 = box
    jittered_rect(draw, box, accent, width=5)
    draw.text((x1 + 28, y1 + 22), title, fill=(25, 34, 52), font=font(38, bold=True))
    y = y1 + 86
    for line in lines:
        draw.text((x1 + 34, y), line, fill=(34, 48, 70), font=font(29))
        y += 48


def create_whiteboard_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (1500, 950), (247, 246, 239))
    draw = ImageDraw.Draw(img)

    for y in range(40, 930, 92):
        jittered_line(draw, [(40, y), (1460, y + 4)], (231, 229, 220), width=1, repeats=1, jitter=1)

    draw.text((365, 52), "AGENT MONITORING MVP", fill=(20, 31, 48), font=font(54, bold=True))
    draw.text((465, 118), "whiteboard sketch -> buildable dashboard", fill=(82, 91, 110), font=font(28))

    monitor = (90, 260, 475, 535)
    dashboard = (555, 230, 955, 565)
    history = (1040, 260, 1415, 535)
    activity = (555, 640, 955, 900)

    draw_note(
        draw,
        monitor,
        "Agent Monitor",
        ["UI: React dashboard", "start / pause agents", "live status cards"],
        (51, 112, 176),
    )
    draw_note(
        draw,
        dashboard,
        "Agent Dashboard",
        ["FastAPI backend", "WebSocket updates", "agent task router"],
        (207, 87, 60),
    )
    draw_note(
        draw,
        history,
        "Task History",
        ["database", "events + runs", "audit trail"],
        (50, 137, 92),
    )
    draw_note(
        draw,
        activity,
        "Activity Feed",
        ["recent events", "errors / retries", "completed tasks"],
        (126, 87, 169),
    )

    arrow(draw, (475, 395), (555, 395))
    draw.text((490, 350), "commands", fill=(45, 68, 110), font=font(23))

    arrow(draw, (955, 395), (1040, 395))
    draw.text((968, 350), "write runs", fill=(45, 68, 110), font=font(23))

    arrow(draw, (760, 565), (760, 640))
    draw.text((780, 588), "stream", fill=(45, 68, 110), font=font(23))

    draw.text((120, 720), "MVP should include:", fill=(25, 34, 52), font=font(34, bold=True))
    for idx, item in enumerate(["overview cards", "agent list", "run history", "activity feed"]):
        y = 778 + idx * 40
        draw.text((135, y), f"[ ] {item}", fill=(34, 48, 70), font=font(28))

    img.save(path)
    return path


def post_chat(url, payload, timeout):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def ask(url, model, image_path, text, tools=None, timeout=180):
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": VIDEO_CALL_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            },
        ],
        "stream": False,
        "max_tokens": 900,
        "reasoning_effort": "none",
    }
    if tools:
        payload["tools"] = [ALL_TOOLS[name] for name in tools]
        payload["tool_choice"] = "auto"
    started = time.perf_counter()
    response = post_chat(url, payload, timeout)
    return response["choices"][0]["message"], (time.perf_counter() - started) * 1000


def message_text(message):
    return (message.get("content") or "").strip()


def tool_call(message):
    calls = message.get("tool_calls") or []
    if not calls:
        return None, {}
    call = calls[0]
    raw_args = call.get("function", {}).get("arguments") or "{}"
    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError:
        args = {}
    return call.get("function", {}).get("name", ""), args


def contains_any(text, terms):
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE_PATH)
    args = parser.parse_args()

    image_path = create_whiteboard_image(args.image)
    print(f"whiteboard image prompt e2e: image={image_path}")

    readback_text = ""
    elapsed = 0.0
    readback_prompts = [
        "Read this whiteboard sketch. In one short paragraph, describe the app components you see.",
        "Visual recognition test only. Do not build, do not document, and do not say 'on it'. List the visible component labels and arrows in this whiteboard image.",
    ]
    for prompt in readback_prompts:
        readback, elapsed = ask(args.url, args.model, image_path, prompt)
        readback_text = message_text(readback)
        if (
            contains_any(readback_text, ["Agent Monitor", "monitor"])
            and contains_any(readback_text, ["FastAPI", "backend", "dashboard"])
            and contains_any(readback_text, ["database", "Task History", "history"])
        ):
            break
    require(contains_any(readback_text, ["Agent Monitor", "monitor"]), readback_text)
    require(contains_any(readback_text, ["FastAPI", "backend", "dashboard"]), readback_text)
    require(contains_any(readback_text, ["database", "Task History", "history"]), readback_text)
    print(f"Visual readback: PASS :: {readback_text} ({elapsed:.0f}ms)")

    routed, elapsed = ask(
        args.url,
        args.model,
        image_path,
        "Hey Claw, please turn this sketch into an MVP. I'm going to dinner; write me a brief to review for when I get back.",
        tools=["markdown_assistant", "html_assistant", "codebase_assistant", "workspace_update_assistant", "reasoning_assistant"],
    )
    name, tool_args = tool_call(routed)
    require(name == "codebase_assistant", f"expected codebase_assistant, got {name}: {routed}")
    joined = (
        tool_args.get("task", "")
        + " "
        + tool_args.get("context", "")
        + " "
        + tool_args.get("output_dir", "")
    )
    require(contains_any(joined, ["mvp", "app", "codebase", "fastapi", "dashboard"]), tool_args)
    require(contains_any(joined, ["Agent Monitor", "FastAPI", "Task History", "database", "Activity Feed"]), tool_args)
    print(f"MVP codebase routing: PASS :: {tool_args} ({elapsed:.0f}ms)")

    brief, elapsed = ask(
        args.url,
        args.model,
        image_path,
        "Create a concise MVP brief from this diagram for me to review later. Do not build the app yet.",
        tools=["markdown_assistant", "html_assistant", "codebase_assistant", "workspace_update_assistant", "reasoning_assistant"],
    )
    name, tool_args = tool_call(brief)
    require(name == "markdown_assistant", f"expected markdown_assistant for brief-only request, got {name}: {brief}")
    joined = (
        tool_args.get("task", "")
        + " "
        + tool_args.get("context", "")
        + " "
        + tool_args.get("output_path", "")
    )
    require(contains_any(joined, ["mvp", "brief", "mvp_brief.md"]), tool_args)
    print(f"MVP brief-only routing: PASS :: {tool_args} ({elapsed:.0f}ms)")
    print("whiteboard image prompt e2e: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
