#!/usr/bin/env python3
"""Generate a simple block diagram of realtime2 <-> Claw architecture.

Output: docs/claw_architecture.png
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from pathlib import Path

OUT = Path(__file__).resolve().parent / "claw_architecture.png"

fig, ax = plt.subplots(figsize=(11, 8.5))
ax.set_xlim(0, 11)
ax.set_ylim(0, 8.5)
ax.set_aspect("equal")
ax.axis("off")


def box(x, y, w, h, text, *, fg="#1f2937", bg="#ffffff", edge="#334155",
        lw=1.6, fontsize=11, weight="normal"):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.06,rounding_size=0.18",
        linewidth=lw, edgecolor=edge, facecolor=bg,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fontsize, color=fg, weight=weight, wrap=True)


def arrow(x1, y1, x2, y2, *, color="#334155", lw=2.0, style="-|>", linestyle="-",
          label=None, label_xy=None):
    a = FancyArrowPatch((x1, y1), (x2, y2),
                        arrowstyle=style, mutation_scale=18,
                        color=color, linewidth=lw, zorder=3,
                        linestyle=linestyle)
    ax.add_patch(a)
    if label and label_xy:
        ax.text(label_xy[0], label_xy[1], label,
                ha="center", va="center", fontsize=9, color=color, style="italic",
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.9))


# Palette
BLUE   = "#2563eb"
GREEN  = "#16a34a"
ORANGE = "#ea580c"
GREY   = "#475569"

# 1. Phone
box(4.4, 7.0, 2.2, 0.8, "Phone\nvoice + camera",
    edge=GREY, fg=GREY, fontsize=11, weight="bold")

# 2. realtime2
box(3.3, 4.6, 4.4, 1.2,
    "realtime2\nvoice + vision + TTS   ·   agent loop",
    edge=BLUE, fg=BLUE, lw=2.2, fontsize=12, weight="bold")

# Ollama side-note (shared by both agents) — use a dashed line, single link
box(0.2, 4.85, 2.7, 0.7,
    "Ollama :11434\nqwen3.6-35B-A3B  (shared)",
    edge=GREY, fg=GREY, bg="#f8fafc", fontsize=9)

# 3a. Fast path
box(0.6, 2.9, 3.6, 1.1,
    "Fast-path tool call\nadd_todo · list_todos · send_telegram …",
    edge=GREEN, fg=GREEN, lw=2.0, fontsize=11, weight="bold")

# 3b. ask_claw bridge
box(6.8, 2.9, 3.6, 1.1,
    "ask_claw\nopenclaw agent --local …",
    edge=ORANGE, fg=ORANGE, lw=2.0, fontsize=11, weight="bold")

# 4. OpenClaw Claw agent
box(6.8, 1.3, 3.6, 1.1,
    "OpenClaw — Claw agent\nfull agent turn · ~50 skills · memory",
    edge=ORANGE, fg=ORANGE, lw=2.0, fontsize=11, weight="bold")

# 5. Shared state
box(3.2, 0.1, 4.6, 0.95,
    "Skill CLI  →  todos.md  (one file, both paths)",
    edge=GREY, fg=GREY, bg="#f8fafc", lw=2.0, fontsize=11, weight="bold")

# Arrows
arrow(5.5, 7.0, 5.5, 5.85, color=GREY)                              # phone arrow
# (note: phone box top edge at 7.0+0.8=7.8; title at 8.2 so plenty of clearance)
arrow(4.4, 4.6, 2.4, 4.0, color=GREEN,
      label="~2 s",  label_xy=(3.15, 4.45))                         # realtime2 → fast
arrow(6.6, 4.6, 8.6, 4.0, color=ORANGE,
      label="~20 s", label_xy=(7.85, 4.45))                         # realtime2 → ask_claw
arrow(8.6, 2.9, 8.6, 2.4, color=ORANGE)                             # ask_claw → Claw
arrow(8.0, 1.3, 6.3, 1.05, color=ORANGE)                            # Claw → todos.md
arrow(2.8, 2.9, 4.7, 1.05, color=GREEN)                             # fast → todos.md

# Short dashed link from Ollama to realtime2. Both agents use it, but the
# "(shared)" label on the Ollama box says that clearly enough — no need for a
# second long diagonal that clutters the middle of the diagram.
arrow(2.9, 5.2, 3.3, 5.2, color=GREY, lw=1.0, style="-", linestyle="--")

# Title — placed well above the phone box to avoid em-dash rendering
# artifacts where matplotlib stretches characters across the top border
# of any box that sits too close.
ax.text(5.5, 8.2, "Claw x realtime2: one model, two paths, shared state",
        ha="center", va="center", fontsize=14, weight="bold", color="#111827")

plt.tight_layout()
plt.savefig(OUT, dpi=170, bbox_inches="tight", facecolor="white")
print(f"wrote {OUT}")
