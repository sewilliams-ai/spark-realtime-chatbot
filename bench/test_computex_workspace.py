#!/usr/bin/env python3
"""Deterministic Computex workspace routing checks.

Run:
  .venv-gpu/bin/python bench/test_computex_workspace.py
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server
from tools import ALL_TOOLS, is_agent_tool


def main() -> int:
    assert "html_assistant" in ALL_TOOLS
    assert is_agent_tool("html_assistant")
    assert is_agent_tool("workspace_update_assistant")

    with TemporaryDirectory() as tmp:
        server.WORKSPACE_ROOT = Path(tmp).resolve()
        session = server.VoiceSession.__new__(server.VoiceSession)

        assert session.infer_markdown_output_path(
            "Turn this Agent Workbench sketch into an MVP brief"
        ) == "mvp_brief.md"
        assert session.infer_markdown_output_path(
            "Draft the team update from dinner"
        ) == "team_update.md"

        request = (
            "Update my team: the strategic alignment dinner went amazing. "
            "Hardware partners agreed to invest if we prioritize the partner-facing MVP. "
            "Assign action items and save a todo to buy pineapple cakes for my husband."
        )
        assert session.is_workspace_update_request(request)
        assert not session.is_workspace_update_request("Add these to the project")

        todos = session.extract_workspace_todos("Update my team", request, [])
        assert any("Avery" in item for item in todos), todos
        assert any("Morgan" in item for item in todos), todos
        assert any("Riley" in item for item in todos), todos
        assert any("oolong" in item.lower() for item in todos), todos

        result = session.apply_workspace_todo_updates(todos, "Update my team", request)
        root = Path(tmp)
        team = (root / result["files"]["team_update"]).read_text()
        brief = (root / result["files"]["executive_brief"]).read_text()
        personal = (root / result["files"]["personal_todos"]).read_text()
        joined = team + brief + personal

        assert "Hardware partners" in team
        assert "Agent Workbench" in brief
        assert "high mountain oolong tea" in personal
        assert "spark-computex-team-update" in team
        assert "spark-computex-executive-brief" in brief
        assert "spark-computex-personal-todos" in personal
        for stale in ("spark-beat4", "Buy umbrella", "Redis pub/sub"):
            assert stale not in joined, stale

    print("computex workspace routing: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
