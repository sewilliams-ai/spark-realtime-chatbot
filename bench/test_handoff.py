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
    assert server._should_auto_resume_handoff(mobile, state)
    await server.send_handoff_resumed(mobile, state)
    old_session = server.active_conversation_sessions["conv_test"]
    server.active_conversation_sessions["conv_test"] = mobile
    await server.transfer_conversation_control(mobile, old_session)

    assert mobile_ws.sent[-1]["type"] == "handoff_resumed"
    assert mobile.conversation_history[-1]["content"] == "first answer"
    assert desktop_ws.sent[-1]["type"] == "handoff_transferred"
    assert desktop_ws.closed and "phone" in desktop_ws.closed[1]
    assert desktop._ws_closed

    stale_ws = FakeWebSocket()
    stale_desktop = server.VoiceSession(
        stale_ws,
        chat_id="stale_desktop_chat",
        conversation_id="conv_test",
        device_type="desktop",
    )
    await server.close_stale_handoff_session(stale_desktop)
    assert stale_ws.sent[-1]["type"] == "handoff_transferred"
    assert stale_ws.closed and "another device" in stale_ws.closed[1]

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

    server.conversation_states.clear()
    server.active_conversation_sessions.clear()
    old_a_ws = FakeWebSocket()
    old_a = server.VoiceSession(old_a_ws, chat_id="old_a", conversation_id="conv_old_a", device_type="desktop")
    old_b_ws = FakeWebSocket()
    old_b = server.VoiceSession(old_b_ws, chat_id="old_b", conversation_id="conv_old_b", device_type="desktop")
    keep_mobile_ws = FakeWebSocket()
    keep_mobile = server.VoiceSession(keep_mobile_ws, chat_id="keep_mobile", conversation_id="conv_keep", device_type="mobile")
    server.active_conversation_sessions["conv_old_a"] = old_a
    server.active_conversation_sessions["conv_old_b"] = old_b
    server.active_conversation_sessions["conv_keep"] = keep_mobile
    old_a.publish_handoff_state(include_empty=True)
    old_b.publish_handoff_state(include_empty=True)
    keep_mobile.publish_handoff_state(include_empty=True)
    replacement_ws = FakeWebSocket()
    replacement = server.VoiceSession(
        replacement_ws,
        chat_id="replacement",
        conversation_id="conv_new_desktop",
        device_type="desktop",
    )
    await server.close_replaced_same_device_sessions(replacement)
    assert "conv_old_a" not in server.active_conversation_sessions
    assert "conv_old_b" not in server.active_conversation_sessions
    assert server.active_conversation_sessions["conv_keep"] is keep_mobile
    assert old_a_ws.sent[-1]["type"] == "session_replaced"
    assert old_b_ws.sent[-1]["type"] == "session_replaced"
    assert old_a_ws.closed and old_b_ws.closed

    server.conversation_states["conv_old"] = {"updated_at": 0}
    server._prune_conversation_states()
    assert "conv_old" not in server.conversation_states

    print("handoff helper smoke: PASS")


if __name__ == "__main__":
    asyncio.run(main())
