#!/usr/bin/env python3
"""Process-local smoke test for bidirectional conversation handoff.

Run:
  .venv-gpu/bin/python bench/test_handoff.py
"""
import asyncio
import sys
from pathlib import Path

from starlette.websockets import WebSocketState

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


class FakeWebSocket:
    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.sent = []
        self.closed = None

    async def send_json(self, payload):
        self.sent.append(payload)

    async def send_bytes(self, data):
        self.sent.append({"type": "bytes", "size": len(data)})

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)
        self.client_state = WebSocketState.DISCONNECTED


class FakeRequest:
    def __init__(self, **query_params):
        self.query_params = query_params


async def main():
    server.conversation_states.clear()
    server.active_conversation_sessions.clear()

    empty_ws = FakeWebSocket()
    empty_desktop = server.VoiceSession(
        empty_ws,
        chat_id="empty_desktop",
        conversation_id="conv_empty",
        device_type="desktop",
    )
    empty_desktop.call_mode = "video"
    empty_desktop.publish_handoff_state(include_empty=True)
    server.active_conversation_sessions["conv_empty"] = empty_desktop
    empty_status = await server.handoff_status(FakeRequest(device="mobile"))
    assert empty_status["available"] is True
    assert empty_status["conversation_id"] == "conv_empty"
    assert empty_status["call_mode"] == "video"

    server.conversation_states.clear()
    server.active_conversation_sessions.clear()

    desktop_ws = FakeWebSocket()
    desktop = server.VoiceSession(
        desktop_ws,
        chat_id="desktop_chat",
        conversation_id="conv_test",
        device_type="desktop",
    )
    desktop.system_prompt = "system prompt"
    desktop.selected_voice = "af_heart"
    desktop.enabled_tools = ["calculator"]
    desktop.conversation_history = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "first question"},
        {"role": "assistant", "content": "first answer"},
        {"role": "assistant", "content": None, "tool_calls": []},
        {"role": "tool", "content": "hidden"},
    ]
    desktop.publish_handoff_state()
    server.active_conversation_sessions["conv_test"] = desktop

    state = server._get_handoff_candidate("conv_test", "mobile")
    assert state, "mobile should see active desktop candidate"
    assert server._get_handoff_candidate("conv_unknown", "mobile") is state
    assert server._get_handoff_candidate("conv_test", "desktop") is None
    assert [msg["role"] for msg in state["conversation_history"]] == [
        "system",
        "user",
        "assistant",
    ]
    assert state["enabled_tools"] == ["calculator"]
    assert state["selected_voice"] == "af_heart"

    mobile_ws = FakeWebSocket()
    mobile = server.VoiceSession(
        mobile_ws,
        chat_id="mobile_chat",
        conversation_id="conv_test",
        device_type="mobile",
    )
    await server.send_handoff_resumed(mobile, state)
    old_session = server.active_conversation_sessions["conv_test"]
    server.active_conversation_sessions["conv_test"] = mobile
    await server.transfer_conversation_control(mobile, old_session)

    assert mobile_ws.sent[-1]["type"] == "handoff_resumed"
    assert mobile.conversation_history[-1]["content"] == "first answer"
    assert desktop_ws.sent[-1]["type"] == "handoff_transferred"
    assert desktop_ws.closed and "phone" in desktop_ws.closed[1]

    mobile.conversation_history.extend([
        {"role": "user", "content": "follow up"},
        {"role": "assistant", "content": "second answer"},
    ])
    mobile.publish_handoff_state()

    back_state = server._get_handoff_candidate("conv_test", "desktop")
    assert back_state, "desktop should see active mobile candidate"
    new_desktop_ws = FakeWebSocket()
    new_desktop = server.VoiceSession(
        new_desktop_ws,
        chat_id="desktop_chat",
        conversation_id="conv_test",
        device_type="desktop",
    )
    await server.send_handoff_resumed(new_desktop, back_state)
    assert new_desktop_ws.sent[-1]["type"] == "handoff_resumed"
    assert new_desktop.conversation_history[-1]["content"] == "second answer"

    server.conversation_states["conv_old"] = {"updated_at": 0}
    server._prune_conversation_states()
    assert "conv_old" not in server.conversation_states

    print("handoff helper smoke: PASS")


if __name__ == "__main__":
    asyncio.run(main())
