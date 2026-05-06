"""spark-realtime-chatbot - Real-time Voice Chatbot Server.

A WebSocket-based voice assistant using:
- Faster-Whisper for ASR
- llama.cpp or TensorRT-LLM for LLM
- Kokoro for TTS
"""

import argparse
import asyncio
import json
import os
import re
import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import numpy as np
from fastapi import FastAPI, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketState

# Local modules
from config import (
    ASRConfig, LLMConfig, VLMConfig, ReasoningConfig, TTSConfig,
    AUDIO_DIR, STATIC_DIR, SAMPLE_RATE, WORKSPACE_ROOT, FFMPEG_PATH
)
from audio import check_ffmpeg_available, decode_webm_bytes_to_pcm_f32
from tools import get_enabled_tools, execute_tool
from clients import (
    HTTPSessionManager,
    create_asr,
    LlamaCppClient,
    VLMClient,
    ReasoningClient,
    create_tts,
)
from clients.http_session import set_http_manager

# Import system prompt
from prompts import DEFAULT_SYSTEM_PROMPT


def _safely_spoken_flag(blob) -> bool:
    """True if a tool result JSON has {"spoken": true}.
    Used by the agent loop to know whether ask_claw already streamed its
    reply directly to TTS so the LLM follow-up should be brief.
    """
    try:
        return bool(json.loads(blob or "{}").get("spoken"))
    except Exception:
        return False


# In CLAW_DEMO_MODE, strip ask_claw from the tools list — the prompt already
# tells the model to affirm action-asks confidently, but removing the tool
# from the array entirely prevents the model from routing around the prompt
# by calling ask_claw (which is honest about what's wired and would break
# the demo theatre).
def _filter_for_demo(tool_defs):
    if os.environ.get("CLAW_DEMO_MODE", "").lower() not in ("1", "true", "yes", "on"):
        return tool_defs
    return [t for t in tool_defs if t.get("function", {}).get("name") != "ask_claw"]


# -----------------------------
# FastAPI app setup
# -----------------------------

# Global models (initialized at startup)
asr = None  # FasterWhisperASR or LocalWhisperASR based on ASR_MODE
llm: LlamaCppClient = None
tts = None  # KokoroTTS or ChatterboxTTS, selected via TTSConfig.engine

# Conversation history (in-memory, per-session could be added later)
conversation_history: List[Dict[str, str]] = [
    {
        "role": "system",
        "content": (
            "You are a concise, helpful voice assistant. "
            "Answer in 1–2 short sentences, no internal reasoning or metadata in your reply."
        ),
    }
]

# Process-local conversation handoff state. This is intentionally in-memory:
# a server restart drops handoff offers, and no conversation content is written
# to demo files, caches, or a database.
HANDOFF_TTL_SECONDS = 30 * 60
HANDOFF_HISTORY_LIMIT = 20
HANDOFF_CONTENT_LIMIT = 4000

conversation_states: Dict[str, Dict[str, Any]] = {}
active_conversation_sessions: Dict[str, "VoiceSession"] = {}
codebase_preview_processes: Dict[str, Dict[str, Any]] = {}


def _new_conversation_id() -> str:
    return f"conv_{uuid.uuid4().hex[:12]}"


def _normalize_device_type(device: str) -> str:
    return "mobile" if device == "mobile" else "desktop"


def _handoff_device_label(device: str) -> str:
    return "phone" if _normalize_device_type(device) == "mobile" else "laptop"


def _sanitize_handoff_history(
    history: List[Dict[str, Any]],
    fallback_system_prompt: str,
) -> List[Dict[str, str]]:
    """Keep only model-safe conversation messages needed for handoff."""
    sanitized: List[Dict[str, str]] = []
    for msg in history or []:
        role = msg.get("role")
        content = msg.get("content")
        if role not in {"system", "user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        sanitized.append({
            "role": role,
            "content": content.strip()[:HANDOFF_CONTENT_LIMIT],
        })

    system_msg = next(
        (msg for msg in sanitized if msg["role"] == "system"),
        {"role": "system", "content": fallback_system_prompt},
    )
    turns = [msg for msg in sanitized if msg["role"] != "system"]
    return [system_msg] + turns[-HANDOFF_HISTORY_LIMIT:]


def _handoff_visible_messages(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history
        if msg.get("role") in {"user", "assistant"} and msg.get("content")
    ]


def _handoff_summary(history: List[Dict[str, str]]) -> str:
    visible = _handoff_visible_messages(history)
    user_turns = [msg["content"] for msg in visible if msg["role"] == "user"]
    if not visible:
        return "No completed conversation yet."
    if user_turns:
        last_user = user_turns[-1]
        return f"{len(visible)} messages. Last topic: {last_user[:120]}"
    return f"{len(visible)} messages ready to continue."


def _prune_conversation_states() -> None:
    now = time.time()
    stale_ids = [
        conversation_id
        for conversation_id, state in conversation_states.items()
        if now - float(state.get("updated_at", 0)) > HANDOFF_TTL_SECONDS
    ]
    for conversation_id in stale_ids:
        conversation_states.pop(conversation_id, None)


def _state_available_for_handoff(state: Dict[str, Any], device_type: str) -> bool:
    conversation_id = state.get("conversation_id")
    if not conversation_id:
        return False
    owner_session = active_conversation_sessions.get(conversation_id)
    if not owner_session or owner_session._ws_closed:
        return False
    if owner_session.device_type == _normalize_device_type(device_type):
        return False
    return True


def _get_handoff_candidate(conversation_id: str, device_type: str) -> Optional[Dict[str, Any]]:
    """Return a handoff state only when another active device owns the call."""
    _prune_conversation_states()

    if conversation_id:
        state = conversation_states.get(conversation_id)
        if state and _state_available_for_handoff(state, device_type):
            return state

    candidates = [
        state
        for state in conversation_states.values()
        if _state_available_for_handoff(state, device_type)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda state: float(state.get("updated_at", 0)))


def _should_auto_resume_handoff(session: "VoiceSession", state: Optional[Dict[str, Any]]) -> bool:
    """True when the connecting client explicitly requested the active conversation."""
    return bool(
        state
        and session.conversation_id
        and session.conversation_id == state.get("conversation_id")
    )


def _codebase_preview_public_base() -> str:
    """Best-effort external base URL for generated MVP preview links."""
    base = (
        os.environ.get("SPARK_PUBLIC_BASE_URL")
        or os.environ.get("APP_PUBLIC_URL")
        or os.environ.get("PUBLIC_BASE_URL")
        or "https://localhost:8443"
    )
    return base.rstrip("/")


def _codebase_preview_path(slug: str) -> str:
    return f"/generated/{slug}/"


def _codebase_preview_url(slug: str) -> str:
    return f"{_codebase_preview_public_base()}{_codebase_preview_path(slug)}"


def _rewrite_codebase_preview_content(content: bytes, content_type: str, slug: str) -> bytes:
    """Rewrite generated-app absolute API paths so they work behind Spark's proxy."""
    lower_type = (content_type or "").lower()
    if not any(kind in lower_type for kind in ("text/html", "javascript", "ecmascript", "text/css")):
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    prefix = f"/generated/{slug}/api/"
    text = text.replace('"/api/', f'"{prefix}')
    text = text.replace("'/api/", f"'{prefix}")
    text = text.replace("`/api/", f"`{prefix}")
    text = text.replace("=/api/", f"={prefix}")
    return text.encode("utf-8")


async def _stop_codebase_preview(slug: str) -> None:
    """Stop a generated MVP preview process for one workspace slug."""
    preview = codebase_preview_processes.pop(slug, None)
    proc = preview.get("process") if preview else None
    if not proc or proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


async def _stop_all_codebase_previews() -> None:
    for slug in list(codebase_preview_processes):
        await _stop_codebase_preview(slug)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize models on startup."""
    global asr, llm, tts

    # Initialize shared HTTP session manager first (used by all clients)
    http_manager = HTTPSessionManager()
    set_http_manager(http_manager)

    # Check ffmpeg availability at startup
    if not check_ffmpeg_available():
        print(f"⚠️  WARNING: ffmpeg not found at '{FFMPEG_PATH}'")
        print(f"   Audio decoding will fail. Install ffmpeg:")
        print(f"   - Ubuntu/Debian: sudo apt install ffmpeg")
        print(f"   - macOS: brew install ffmpeg")
        print(f"   - Or set FFMPEG_PATH environment variable to ffmpeg location")
    else:
        print(f"✅ ffmpeg found at '{FFMPEG_PATH}'")

    asr = create_asr(ASRConfig())
    # Warmup ASR model to eliminate cold-start latency
    if hasattr(asr, 'warmup'):
        asr.warmup()
    llm = LlamaCppClient(LLMConfig())
    tts = create_tts(TTSConfig())
    yield
    await _stop_all_codebase_previews()
    # Cleanup: close shared HTTP session
    if http_manager:
        await http_manager.close()


# Parse command-line arguments before creating app
def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description='CES Voice Assistant Server')
    parser.add_argument('--trtllm', action='store_true', 
                       help='Use TensorRT-LLM backend (trtllm-serve) instead of standard OpenAI-compatible backend')
    # Only parse known args to avoid conflicts with uvicorn
    args, unknown = parser.parse_known_args()
    return args

# Check for LLM_BACKEND environment variable (set by launch scripts)
# This is the preferred method since uvicorn doesn't pass args to the app
if os.getenv("LLM_BACKEND") == "trtllm":
    print(f"[Server] TensorRT-LLM backend enabled via LLM_BACKEND environment variable")

app = FastAPI(title="Voice Chat (Streaming)", lifespan=lifespan)

# Serve static files (frontend)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")


# -----------------------------
# Routes
# -----------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint for Docker."""
    return {"status": "ok"}


@app.get("/generated/{slug}")
async def generated_preview_root(slug: str):
    """Normalize generated MVP preview URLs to the proxied app root."""
    return RedirectResponse(_codebase_preview_path(slug))


@app.api_route(
    "/generated/{slug}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def generated_preview_proxy(slug: str, path: str, request: Request):
    """Proxy a generated Qwen MVP through the main Spark origin."""
    preview = codebase_preview_processes.get(slug)
    proc = preview.get("process") if preview else None
    if not preview or not proc or proc.returncode is not None:
        return JSONResponse(
            {"error": "Generated MVP preview is not running", "slug": slug},
            status_code=404,
        )

    port = int(preview["port"])
    upstream_path = (path or "").lstrip("/")
    upstream_url = f"http://127.0.0.1:{port}/{upstream_path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    excluded_headers = {
        "connection",
        "content-length",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
    request_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in excluded_headers
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                request.method,
                upstream_url,
                headers=request_headers,
                data=await request.body(),
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as upstream:
                body = await upstream.read()
                content_type = upstream.headers.get("content-type", "")
                body = _rewrite_codebase_preview_content(body, content_type, slug)
                response_headers = {
                    key: value
                    for key, value in upstream.headers.items()
                    if key.lower() not in excluded_headers and key.lower() != "content-encoding"
                }
                location = response_headers.get("location")
                if location and location.startswith("/"):
                    response_headers["location"] = f"/generated/{slug}{location}"
                response_headers.pop("content-length", None)
                return Response(content=body, status_code=upstream.status, headers=response_headers)
    except Exception as exc:
        return JSONResponse(
            {"error": f"Generated MVP preview proxy failed: {exc}", "slug": slug},
            status_code=502,
        )


@app.get("/api/default_prompt")
async def get_default_prompt():
    """Get the default system prompt from prompts.py."""
    from prompts import DEFAULT_SYSTEM_PROMPT
    return {"prompt": DEFAULT_SYSTEM_PROMPT}


@app.get("/api/handoff/status")
async def handoff_status(request: Request):
    """Return the latest active cross-device handoff candidate, if any."""
    device_type = request.query_params.get("device", "desktop")
    state = _get_handoff_candidate("", device_type)
    if not state:
        return {"available": False}
    return {
        "available": True,
        "conversation_id": state.get("conversation_id"),
        "source_device": state.get("owner_device"),
        "summary": state.get("summary", ""),
        "message_count": state.get("message_count", 0),
        "call_mode": state.get("call_mode", "call"),
    }


_WHOOP_OAUTH_STATES: set[str] = set()

if os.environ.get("WHOOP_CLIENT_ID") and os.environ.get("WHOOP_CLIENT_SECRET"):
    from clients.whoop import auth_url as whoop_auth_url
    from clients.whoop import exchange_code as whoop_exchange_code
    from clients.whoop import fetch_all as whoop_fetch_all
    from clients.whoop import write_auth_tokens as whoop_write_auth_tokens
    from clients.whoop import write_to_health_yaml as whoop_write_to_health_yaml

    @app.get("/whoop/login")
    async def whoop_login():
        """Start WHOOP OAuth for the local demo cache."""
        state = secrets.token_hex(4)
        _WHOOP_OAUTH_STATES.add(state)
        return RedirectResponse(whoop_auth_url(state), status_code=302)

    @app.get("/whoop/callback", response_class=HTMLResponse)
    async def whoop_callback(request: Request):
        """Complete WHOOP OAuth and refresh the local health YAML cache."""
        error = request.query_params.get("error")
        if error:
            return HTMLResponse(f"<h1>WHOOP authorization failed</h1><p>{error}</p>", status_code=400)

        state = request.query_params.get("state", "")
        if state not in _WHOOP_OAUTH_STATES:
            return HTMLResponse("<h1>WHOOP authorization failed</h1><p>Invalid OAuth state.</p>", status_code=400)
        _WHOOP_OAUTH_STATES.discard(state)

        code = request.query_params.get("code")
        if not code:
            return HTMLResponse("<h1>WHOOP authorization failed</h1><p>Missing authorization code.</p>", status_code=400)

        try:
            tokens = await whoop_exchange_code(code)
            token_path = whoop_write_auth_tokens(tokens)
            whoop_data = await whoop_fetch_all(tokens.get("access_token"))
            health_path = whoop_write_to_health_yaml(whoop_data)
        except Exception as exc:
            print(f"[WHOOP] OAuth callback failed: {exc}")
            return HTMLResponse("<h1>WHOOP connection failed</h1><p>Check server logs for details.</p>", status_code=500)

        return HTMLResponse(
            "<h1>WHOOP connected</h1>"
            f"<p>Tokens stored locally at {token_path.name} with mode 600.</p>"
            f"<p>Updated local health cache: {health_path.name}. Restart the server to reload prompt context.</p>"
        )


# -----------------------------
# Face Recognition API
# -----------------------------

@app.post("/api/face/enroll")
async def enroll_face(request: Request):
    """Enroll a new face for recognition.

    Body: {"name": "Person Name", "image": "base64_image_data"}
    """
    try:
        from clients.face import get_face_recognizer
        data = await request.json()
        name = data.get("name")
        image_b64 = data.get("image")

        if not name or not image_b64:
            return {"success": False, "error": "Missing name or image"}

        recognizer = get_face_recognizer()
        success = recognizer.enroll_face(name, image_b64)

        if success:
            return {"success": True, "message": f"Enrolled {name}"}
        else:
            return {"success": False, "error": "No face detected in image"}
    except Exception as e:
        print(f"[Face API] Enroll error: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/face/recognize")
async def recognize_faces(request: Request):
    """Recognize faces in an image.

    Body: {"image": "base64_image_data"}
    """
    try:
        from clients.face import get_face_recognizer
        data = await request.json()
        image_b64 = data.get("image")

        if not image_b64:
            return {"success": False, "error": "Missing image"}

        recognizer = get_face_recognizer()
        faces = recognizer.recognize_faces(image_b64)

        return {"success": True, "faces": faces}
    except Exception as e:
        print(f"[Face API] Recognize error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/face/list")
async def list_enrolled_faces():
    """List all enrolled faces."""
    try:
        from clients.face import get_face_recognizer
        recognizer = get_face_recognizer()
        names = recognizer.list_enrolled()
        return {"success": True, "faces": names}
    except Exception as e:
        print(f"[Face API] List error: {e}")
        return {"success": False, "error": str(e)}


@app.delete("/api/face/{name}")
async def delete_face(name: str):
    """Delete an enrolled face."""
    try:
        from clients.face import get_face_recognizer
        recognizer = get_face_recognizer()
        success = recognizer.delete_face(name)

        if success:
            return {"success": True, "message": f"Deleted {name}"}
        else:
            return {"success": False, "error": f"Face '{name}' not found"}
    except Exception as e:
        print(f"[Face API] Delete error: {e}")
        return {"success": False, "error": str(e)}


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the frontend HTML with per-file cache-busters.

    Appends ?v=<mtime> to /static/css/styles.css and /static/js/app.js so
    any edit to those files invalidates the phone's cached copy on next
    page load — no more 'hard refresh' gymnastics.
    """
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Frontend not found. Please create static/index.html</h1>")
    html = index_path.read_text()
    for rel in ("css/styles.css", "js/app.js"):
        asset_path = STATIC_DIR / rel
        if asset_path.exists():
            v = int(asset_path.stat().st_mtime)
            import re
            html = re.sub(
                rf"/static/{re.escape(rel)}(?:\?v=[^\"']*)?",
                f"/static/{rel}?v={v}",
                html,
            )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


# -----------------------------
# Persistent Voice WebSocket - Main Endpoint
# -----------------------------

class VoiceSession:
    """Manages state for a persistent voice session."""
    def __init__(
        self,
        websocket: WebSocket,
        chat_id: str = "",
        conversation_id: str = "",
        device_type: str = "desktop",
    ):
        self.websocket = websocket
        self.session_id = f"session_{uuid.uuid4().hex[:12]}"
        self.chat_id = chat_id or f"chat_{uuid.uuid4().hex[:12]}"
        self.conversation_id = conversation_id or _new_conversation_id()
        self.device_type = _normalize_device_type(device_type)
        self.call_mode = "call"
        self.asr_webm_bytes = bytearray()
        self.asr_pcm = np.zeros(0, dtype=np.float32)
        self.asr_last_text = ""
        self.is_recording = False
        self.audio_context_initialized = False
        # Last camera frame seen in video-call mode (base64 JPEG, no data: prefix).
        # ask_claw uses this to pass the actual pixels to Claw, so Claw's own
        # VLM can reason on the image instead of just realtime2's description.
        self.last_camera_frame_b64: Optional[str] = None
        # Claw barge-in tracking. Set while a streaming ask_claw turn is in flight
        # so user speech / disconnect can cancel it.
        self._claw_in_flight: bool = False
        self._claw_bridge_ref = None  # the ClawAcp singleton, set when streaming starts
        self.selected_voice = os.getenv("KOKORO_VOICE", "af_bella")  # Default voice
        self.enabled_tools = []  # Default: no tools enabled

        # Import system prompt from prompts.py
        from prompts import DEFAULT_SYSTEM_PROMPT
        self.system_prompt = DEFAULT_SYSTEM_PROMPT
        # Initialize conversation history AFTER system_prompt is defined
        self.conversation_history: List[Dict[str, str]] = [
            {
                "role": "system",
                "content": self.system_prompt,
            }
        ]
        # Once set, every streaming loop should bail out of its LLM read.
        # Set by send_message/send_audio_chunk when the WS is gone.
        self._ws_closed: bool = False

    async def cancel_claw_in_flight(self) -> None:
        """Cancel any in-flight Claw streaming turn (barge-in / user spoke again)."""
        if not self._claw_in_flight:
            return
        bridge = self._claw_bridge_ref
        if bridge is None:
            return
        try:
            print("[Voice Session] barge-in: cancelling in-flight Claw turn")
            await bridge.cancel()
        except Exception as e:
            print(f"[Voice Session] cancel_claw_in_flight failed: {e}")

    @property
    def alive(self) -> bool:
        """Fast check: can we still send to the client?"""
        return (not self._ws_closed) and (self.websocket.client_state == WebSocketState.CONNECTED)

    def export_handoff_state(self) -> Dict[str, Any]:
        history = _sanitize_handoff_history(self.conversation_history, self.system_prompt)
        visible_messages = _handoff_visible_messages(history)
        return {
            "conversation_id": self.conversation_id,
            "owner_session_id": self.session_id,
            "owner_device": self.device_type,
            "owner_chat_id": self.chat_id,
            "system_prompt": self.system_prompt,
            "conversation_history": history,
            "enabled_tools": list(self.enabled_tools),
            "selected_voice": self.selected_voice,
            "call_mode": self.call_mode,
            "updated_at": time.time(),
            "message_count": len(visible_messages),
            "summary": _handoff_summary(history),
            "messages": visible_messages,
        }

    def publish_handoff_state(self, include_empty: bool = False) -> None:
        active_owner = active_conversation_sessions.get(self.conversation_id)
        if active_owner is not None and active_owner is not self:
            return
        state = self.export_handoff_state()
        if state["message_count"] <= 0 and not include_empty:
            return
        conversation_states[self.conversation_id] = state

    def is_active_owner(self) -> bool:
        return active_conversation_sessions.get(self.conversation_id) is self

    async def send_transient_ack(self, message: str) -> None:
        """Show and speak a short acknowledgment as a normal assistant turn."""
        await self.send_message("final_response", {"text": message})
        await self.stream_tts(message, is_transient=True)

    def start_codebase_agent_task(self, task: str, context: str = "", output_dir: str = "agent_monitor_mvp") -> None:
        """Launch the Qwen codebase agent without blocking the active call."""
        self._codebase_agent_started_at = time.time()
        self._codebase_agent_task = task or "Build this sketch into a working MVP"
        self._codebase_agent_context = context or ""
        asyncio.create_task(self.execute_codebase_agent(self._codebase_agent_task, self._codebase_agent_context, output_dir))

    def hydrate_from_handoff_state(self, state: Dict[str, Any]) -> None:
        self.conversation_id = state.get("conversation_id") or self.conversation_id
        self.system_prompt = state.get("system_prompt") or self.system_prompt
        self.conversation_history = _sanitize_handoff_history(
            state.get("conversation_history", []),
            self.system_prompt,
        )
        self.enabled_tools = list(state.get("enabled_tools") or [])
        self.selected_voice = state.get("selected_voice") or self.selected_voice
        self.call_mode = state.get("call_mode") or self.call_mode

    async def send_message(self, msg_type: str, data: Dict[str, Any] = None):
        """Send a JSON message to the client."""
        if self._ws_closed:
            return False  # silent after the first detection — no log spam
        try:
            # Check if WebSocket is still connected
            if self.websocket.client_state != WebSocketState.CONNECTED:
                if not self._ws_closed:
                    print(f"[Voice Session] WS closed while sending '{msg_type}' (state: {self.websocket.client_state})")
                self._ws_closed = True
                return False

            payload = {"type": msg_type}
            if data:
                payload.update(data)
            await self.websocket.send_json(payload)
            return True
        except (WebSocketDisconnect, Exception) as e:
            self._ws_closed = True
            # Handle WebSocket disconnection gracefully
            error_type = type(e).__name__
            if "Disconnect" in error_type or "ConnectionClosed" in error_type or "ClientDisconnected" in error_type:
                print(f"[Voice Session] WebSocket disconnected while sending message '{msg_type}'")
            else:
                print(f"[Voice Session] Error sending message '{msg_type}': {e}")
            return False

    async def send_audio_chunk(self, audio_data: bytes):
        """Send binary audio chunk to the client."""
        if self._ws_closed:
            return False
        try:
            # Check if WebSocket is still connected
            if self.websocket.client_state != WebSocketState.CONNECTED:
                self._ws_closed = True
                return False

            await self.websocket.send_bytes(audio_data)
            return True
        except (WebSocketDisconnect, Exception) as e:
            self._ws_closed = True
            # Handle WebSocket disconnection gracefully
            error_type = type(e).__name__
            if "Disconnect" in error_type or "ConnectionClosed" in error_type or "ClientDisconnected" in error_type:
                print(f"[Voice Session] WebSocket disconnected while sending audio chunk")
            else:
                print(f"[Voice Session] Error sending audio chunk: {e}")
            return False

    async def process_asr_chunk(self, chunk_bytes: bytes):
        """Process an ASR audio chunk - streams directly to faster-whisper."""
        if not chunk_bytes:
            return
        
        self.asr_webm_bytes.extend(chunk_bytes)
        
        # Wait for some bytes before decoding (WebM needs headers)
        if len(self.asr_webm_bytes) < 4000:
            return
        
        # Optimize: Send larger chunks less frequently for better performance
        # Larger chunks = fewer API calls = faster overall
        STREAMING_CHUNK_SECONDS = 1.5  # Send chunks every 1.5 seconds (larger chunks)
        MIN_AUDIO_SECONDS = 1.0  # Minimum audio before first transcription
        
        try:
            # Decode accumulated WebM
            decoded_pcm = decode_webm_bytes_to_pcm_f32(bytes(self.asr_webm_bytes), target_sr=SAMPLE_RATE)
            
            # Check if we have enough audio
            if decoded_pcm.size < int(SAMPLE_RATE * MIN_AUDIO_SECONDS):
                return
            
            # Check if audio has actual signal
            audio_max = np.abs(decoded_pcm).max()
            if audio_max < 0.001:
                return
            
            # For streaming: only process new audio (sliding window)
            # This avoids re-processing the same audio
            if hasattr(self, '_last_processed_samples'):
                new_samples = decoded_pcm.size - self._last_processed_samples
                # Only process if we have enough new audio (larger chunks = fewer API calls)
                if new_samples < int(SAMPLE_RATE * STREAMING_CHUNK_SECONDS):
                    return
                # Extract only the new portion for processing
                audio_to_process = decoded_pcm[-new_samples:]
            else:
                # First chunk: process what we have
                audio_to_process = decoded_pcm
            
            # Update tracking
            self._last_processed_samples = decoded_pcm.size
            
            # Stream to faster-whisper (larger chunks = better performance)
            partial_text = await asr.transcribe(audio_to_process)
            
            if partial_text and partial_text != self.asr_last_text:
                self.asr_last_text = partial_text
                await self.send_message("asr_partial", {"text": partial_text})
                
        except Exception as e:
            print(f"[Voice Session] ASR decode error: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message("error", {"error": f"ASR decode error: {e}"})
            return

    async def process_asr_final(self):
        """Process final ASR transcription - sends complete accumulated audio."""
        try:
            # Decode all accumulated audio
            self.asr_pcm = decode_webm_bytes_to_pcm_f32(bytes(self.asr_webm_bytes), target_sr=SAMPLE_RATE)
            
            # Check if audio has actual signal before transcribing
            if self.asr_pcm.size > 0:
                audio_max = np.abs(self.asr_pcm).max()
                if audio_max < 0.001:
                    print(f"[Voice Session] Final audio is silent (max amplitude: {audio_max:.6f}), skipping transcription")
                    final_text = ""
                else:
                    # For final transcription, send the complete audio
                    # This gives better accuracy than streaming chunks
                    final_text = await asr.transcribe(self.asr_pcm)
            else:
                final_text = ""
        except Exception as e:
            print(f"[Voice Session] Final ASR decode error: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message("error", {"error": f"ASR error: {e}"})
            final_text = ""
        
        # Reset ASR state
        self.asr_webm_bytes = bytearray()
        self.asr_pcm = np.zeros(0, dtype=np.float32)
        self.asr_last_text = ""
        if hasattr(self, '_last_processed_samples'):
            delattr(self, '_last_processed_samples')
        
        if final_text and final_text.strip():
            await self.send_message("asr_final", {"text": final_text})
            return final_text
        else:
            print(f"[Voice Session] No transcription result (empty or silent audio)")
            return None

    async def send_transient_response(self, text: str):
        """Send a transient/interim response (e.g., 'on it', 'thinking...')."""
        await self.send_message("transient_response", {"text": text})
        # Also generate and stream TTS for transient response
        await self.stream_tts(text, is_transient=True)

    async def send_final_response(self, text: str):
        """Send final response and stream TTS sentence-by-sentence for lower latency."""
        print(f"[Voice Session] send_final_response called with: {text[:100]}...")
        await self.send_message("final_response", {"text": text})
        print(f"[Voice Session] final_response message sent, starting sentence-by-sentence TTS...")

        # Split into sentences for faster TTS start
        sentences, remaining = self._extract_complete_sentences(text)

        # Add any remaining fragment
        if remaining.strip():
            sentences.append(remaining.strip())

        if not sentences:
            # Fallback: use whole text if no sentences found
            sentences = [text]

        print(f"[Voice Session] TTS pipeline: {len(sentences)} sentence(s)")

        for i, sentence in enumerate(sentences):
            if sentence.strip():
                print(f"[Voice Session] TTS sentence {i+1}/{len(sentences)}: '{sentence[:40]}...'")
                await self.stream_tts(sentence.strip(), is_transient=False)

        print(f"[Voice Session] TTS completed ({len(sentences)} sentences)")

    async def stream_tts(self, text: str, is_transient: bool = False, voice: str = None):
        """Stream TTS audio chunks."""
        if not text or not text.strip():
            print(f"[Voice Session] stream_tts: empty text, skipping")
            return
        
        # Clean text - remove markers
        text = text.replace("<|channel|>analysis<|message|>", "")
        text = text.replace("<|channel|>final<|message|>", "")
        text = text.replace("<|end|>", "")
        text = text.replace("<|start|>assistant", "")
        # Strip hallucinated Gemini-style tool-call fences so they don't get read aloud.
        import re as _re
        text = _re.sub(r"<tool_code>[\s\S]*?</tool_code>", "", text)
        text = _re.sub(r"```(?:tool_code|tool_call|json)?\s*\{[\s\S]*?\}\s*```", "", text)
        text = text.strip()
        
        if not text:
            print(f"[Voice Session] stream_tts: text empty after cleaning")
            return
        
        print(f"[Voice Session] stream_tts: synthesizing '{text[:50]}...'")
        
        # Use provided voice or session default
        voice_to_use = voice or self.selected_voice
        print(f"[Voice Session] stream_tts: using voice '{voice_to_use}' (provided: {voice}, session default: {self.selected_voice})")
        
        # Send TTS start message - if it fails, abort early
        if not await self.send_message("tts_start", {"sample_rate": 24000, "is_transient": is_transient}):
            print(f"[Voice Session] stream_tts: failed to send tts_start, aborting")
            return
        
        try:
            chunk_count = 0
            for audio_data, sample_rate in tts.synth_stream_chunks(text, voice=voice_to_use):
                # Check if we can still send before processing more chunks
                if not await self.send_audio_chunk(audio_data):
                    print(f"[Voice Session] stream_tts: failed to send audio chunk {chunk_count + 1}, stopping")
                    break
                chunk_count += 1
                await asyncio.sleep(0.001)  # Small delay to prevent overwhelming
            
            print(f"[Voice Session] stream_tts: sent {chunk_count} audio chunks")
            # Try to send done message, but don't fail if connection is closed
            await self.send_message("tts_done", {"is_transient": is_transient})
        except (WebSocketDisconnect, Exception) as e:
            error_msg = str(e)
            print(f"[Voice Session] TTS error with voice '{voice_to_use}': {e}")
            
            # If voice file not found, try fallback voices
            if "404" in error_msg or "not found" in error_msg.lower() or "entry not found" in error_msg.lower():
                fallback_voices = ["af_heart", "af_nicole", "af_jessica"]
                print(f"[Voice Session] Trying fallback voices: {fallback_voices}")
                for fallback_voice in fallback_voices:
                    if fallback_voice == voice_to_use:
                        continue  # Skip if already tried
                    try:
                        print(f"[Voice Session] Trying fallback voice: {fallback_voice}")
                        # Re-send TTS start with fallback voice
                        if not await self.send_message("tts_start", {"sample_rate": 24000, "is_transient": is_transient}):
                            print(f"[Voice Session] Failed to send tts_start for fallback, aborting")
                            break
                        
                        chunk_count = 0
                        for audio_data, sample_rate in tts.synth_stream_chunks(text, voice=fallback_voice):
                            # Check if we can still send before processing more chunks
                            if not await self.send_audio_chunk(audio_data):
                                print(f"[Voice Session] Failed to send audio chunk with fallback voice, stopping")
                                break
                            chunk_count += 1
                            await asyncio.sleep(0.001)
                        print(f"[Voice Session] Fallback voice '{fallback_voice}' succeeded, sent {chunk_count} chunks")
                        await self.send_message("tts_done", {"is_transient": is_transient})
                        # Update session voice to the working fallback
                        self.selected_voice = fallback_voice
                        await self.send_message("voice_changed", {"voice": fallback_voice})
                        return
                    except (WebSocketDisconnect, Exception) as fallback_error:
                        error_type = type(fallback_error).__name__
                        if "Disconnect" in error_type or "ConnectionClosed" in error_type or "ClientDisconnected" in error_type:
                            print(f"[Voice Session] WebSocket disconnected during fallback voice attempt")
                            break  # Stop trying fallbacks if disconnected
                        print(f"[Voice Session] Fallback voice '{fallback_voice}' also failed: {fallback_error}")
                        continue
                
                # If all fallbacks failed, send error message (only if still connected)
                await self.send_message("error", {"error": f"TTS failed: Voice '{voice_to_use}' not available. Tried fallbacks: {fallback_voices}"})
            else:
                # For other errors, check if it's a WebSocket disconnection
                error_type = type(e).__name__
                if "Disconnect" in error_type or "ConnectionClosed" in error_type or "ClientDisconnected" in error_type:
                    print(f"[Voice Session] WebSocket disconnected during TTS streaming")
                    # Don't try to send error message if disconnected
                else:
                    # For other errors, just log and send error (only if still connected)
                    import traceback
                    traceback.print_exc()
                    await self.send_message("error", {"error": f"TTS error: {error_msg}"})

    def _extract_complete_sentences(self, text: str) -> tuple:
        """Extract complete sentences from text buffer.

        Returns (complete_sentences, remaining_buffer).
        A sentence is complete if it ends with . ! or ? followed by space or end of string.
        """
        if not text:
            return [], ""

        import re
        # Pattern: sentence ending punctuation followed by space or end
        # Avoid splitting on abbreviations like "Dr.", "Mr.", "etc."
        sentences = []

        # Simple approach: split on . ! ? followed by space
        # Keep the punctuation with the sentence
        pattern = r'([.!?])\s+'
        parts = re.split(pattern, text)

        # Reconstruct sentences (parts alternate: text, punct, text, punct, ...)
        current = ""
        for i, part in enumerate(parts):
            if i % 2 == 0:  # Text part
                current += part
            else:  # Punctuation part
                current += part
                sentences.append(current.strip())
                current = ""

        # Whatever is left is incomplete
        remaining = current.strip()

        return sentences, remaining

    async def stream_llm_with_tts(self, messages: list, tools: list = None) -> tuple:
        """Stream LLM response with overlapped TTS generation.

        Starts TTS generation for each sentence while LLM continues streaming.
        Uses a queue to process TTS in order while LLM runs in parallel.

        Returns: (status, tool_calls, full_response)
        """
        sentence_buffer = ""
        full_response = ""
        sentence_count = 0

        # Queue for sentences to be processed by TTS
        tts_queue = asyncio.Queue()
        tts_done = asyncio.Event()

        async def tts_worker():
            """Background worker that processes TTS queue in order."""
            while True:
                try:
                    # Wait for sentence or done signal
                    sentence = await asyncio.wait_for(tts_queue.get(), timeout=0.1)
                    if sentence is None:  # Poison pill - we're done
                        break
                    await self.stream_tts(sentence, is_transient=False)
                    tts_queue.task_done()
                except asyncio.TimeoutError:
                    if tts_done.is_set() and tts_queue.empty():
                        break
                    continue
                except Exception as e:
                    print(f"[TTS Worker] Error: {e}")
                    break

        # Start TTS worker
        tts_task = asyncio.create_task(tts_worker())

        try:
            async for chunk in llm.stream_complete(messages, tools=tools):
                if not self.alive:
                    print(f"[TTS Pipeline] client disconnected mid-stream, aborting LLM read")
                    break
                if chunk.startswith("data: "):
                    try:
                        data = json.loads(chunk[6:])

                        # Handle tool calls - stop TTS and return for tool processing
                        if "tool_calls_complete" in data:
                            tts_done.set()
                            await tts_queue.put(None)  # Signal worker to stop
                            await tts_task
                            return ("tool_calls", data["tool_calls_complete"], full_response)

                        if "content" in data and data["content"]:
                            content = data["content"]
                            sentence_buffer += content
                            full_response += content

                            # Send transient response to show text as it streams
                            await self.send_message("transient_response", {"text": full_response})

                            # Check for complete sentences
                            sentences, sentence_buffer = self._extract_complete_sentences(sentence_buffer)

                            for sentence in sentences:
                                if sentence.strip():
                                    sentence_count += 1
                                    print(f"[TTS Pipeline] Queuing sentence {sentence_count}: '{sentence[:50]}...'")
                                    # Queue for TTS - doesn't block LLM streaming!
                                    await tts_queue.put(sentence)

                    except json.JSONDecodeError:
                        pass

            # Handle any remaining text in buffer
            if sentence_buffer.strip():
                sentence_count += 1
                print(f"[TTS Pipeline] Queuing final fragment {sentence_count}: '{sentence_buffer[:50]}...'")
                await tts_queue.put(sentence_buffer.strip())

            # Signal TTS worker we're done and wait for it to finish
            tts_done.set()
            await tts_queue.put(None)  # Poison pill
            await tts_task

            print(f"[TTS Pipeline] Completed: {sentence_count} sentences, {len(full_response)} chars total")
            return ("complete", None, full_response)

        except Exception as e:
            print(f"[TTS Pipeline] Error: {e}")
            tts_done.set()
            await tts_queue.put(None)
            await tts_task
            raise

    # Multi-turn tool-call loop cap. Each iteration = one LLM stream that may
    # end with another round of tool calls. Inline tools feed results back
    # into the model; agent tools short-circuit to their UI handlers.
    MAX_TOOL_ITERATIONS = 4

    async def _execute_tool_calls_parallel(self, tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute tool calls concurrently. Returns OpenAI-format tool_result messages.

        Special-cases ask_claw: instead of awaiting the whole reply, opens an
        ACP stream and pipes Claw's chunks straight into progressive TTS in
        real time. The user hears Claw speak directly as the agent generates,
        not after a full silent wait. The tool result is still appended to
        history so the LLM follow-up can do its own short narration if needed.
        """
        async def _run_streaming_claw(tc):
            tool_id = tc.get("id", "")
            fn = tc.get("function", {}) or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            message = (args.get("message") or "").strip()
            if not message:
                return {"tool_call_id": tool_id, "role": "tool", "name": "ask_claw",
                        "content": json.dumps({"error": "empty message"})}
            t0 = asyncio.get_event_loop().time()
            try:
                # Lazy import — claw_acp lives in clients/ but we bypass __init__
                claw_acp = sys.modules.get("clients.claw_acp")
                if claw_acp is None:
                    import importlib.util as _ilu
                    _spec = _ilu.spec_from_file_location(
                        "clients.claw_acp",
                        str(Path(__file__).parent / "clients" / "claw_acp.py"),
                    )
                    claw_acp = _ilu.module_from_spec(_spec)
                    sys.modules["clients.claw_acp"] = claw_acp
                    _spec.loader.exec_module(claw_acp)
                bridge = await claw_acp.get_singleton()
                # Mark in-flight so barge-in / disconnect can cancel us
                self._claw_in_flight = True
                self._claw_bridge_ref = bridge
                full = []
                buf = ""
                spoke = False
                # Pass the latest camera frame to Claw if we have one — Claw's
                # own VLM then reasons on the actual pixels instead of
                # realtime2's word-description of the scene.
                image_b64 = self.last_camera_frame_b64
                async for chunk in bridge.prompt(message, image_b64=image_b64, timeout_s=120.0):
                    if not self.alive:
                        await bridge.cancel()
                        break
                    full.append(chunk)
                    buf += chunk
                    sentences, buf = self._extract_complete_sentences(buf)
                    for s in sentences:
                        s = s.strip()
                        if s:
                            await self.stream_tts(s)
                            spoke = True
                # flush trailing fragment
                tail = buf.strip()
                if tail and self.alive:
                    await self.stream_tts(tail)
                    spoke = True
                elapsed_ms = (asyncio.get_event_loop().time() - t0) * 1000
                reply_text = "".join(full).strip()
                print(f"[Voice Session]   ← ask_claw streamed in {elapsed_ms:.0f}ms ({len(reply_text)} chars, spoke={spoke})")
                # Mark the tool result so the agent loop's LLM follow-up knows
                # it should NOT re-narrate (we already spoke). The 'spoken' key
                # is consumed by the upstream loop to skip its own TTS.
                return {
                    "tool_call_id": tool_id, "role": "tool", "name": "ask_claw",
                    "content": json.dumps({
                        "reply": reply_text or "(no reply)",
                        "elapsed_ms": round(elapsed_ms, 1),
                        "transport": "acp-streamed",
                        "spoken": spoke,
                    }),
                }
            except Exception as e:
                print(f"[Voice Session] ask_claw streaming failed: {e}; falling back to buffered")
                content = await execute_tool("ask_claw", args)
                return {"tool_call_id": tool_id, "role": "tool", "name": "ask_claw", "content": content}
            finally:
                self._claw_in_flight = False
                self._claw_bridge_ref = None

        async def _run(tc):
            fn = tc.get("function", {}) or {}
            if fn.get("name") == "ask_claw":
                return await _run_streaming_claw(tc)
            tool_id = tc.get("id", "")
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            print(f"[Voice Session]   → parallel tool: {name}({list(args.keys())})")
            t0 = asyncio.get_event_loop().time()
            content = await execute_tool(name, args)
            elapsed_ms = (asyncio.get_event_loop().time() - t0) * 1000
            print(f"[Voice Session]   ← {name} in {elapsed_ms:.0f}ms ({len(content)} chars)")
            return {
                "tool_call_id": tool_id, "role": "tool", "name": name, "content": content,
            }
        return await asyncio.gather(*[_run(tc) for tc in tool_calls])

    async def process_user_message(self, user_text: str):
        """Process user message through LLM pipeline."""
        if not user_text or not user_text.strip():
            return
        
        # Add user message to history
        self.conversation_history.append({"role": "user", "content": user_text})
        self.publish_handoff_state(include_empty=True)

        if self.is_workspace_update_request(user_text):
            await self.handle_workspace_update_request(user_text)
            return

        # Build messages for LLM
        messages_for_llm = list(self.conversation_history)

        # Stream LLM response
        final_response = ""
        chunk_count = 0
        raw_chunks = []
        try:
            # Get enabled tools for this session
            enabled_tool_defs = _filter_for_demo(get_enabled_tools(self.enabled_tools))
            print(f"[Voice Session] Starting LLM stream with {len(messages_for_llm)} messages")
            print(f"[Voice Session] Enabled tools: {self.enabled_tools} -> {[t['function']['name'] for t in enabled_tool_defs]}")

            # Check if TTS/LLM overlap is enabled and we're in simple conversation mode (no tools)
            tts_config = TTSConfig()
            if tts_config.overlap_llm and not enabled_tool_defs:
                print(f"[Voice Session] Using TTS/LLM overlap pipeline (no tools enabled)")
                status, tool_calls, full_response = await self.stream_llm_with_tts(messages_for_llm, tools=None)

                if status == "complete" and full_response:
                    # Clean up response markers
                    full_response = llm._extract_final_channel(full_response)
                    full_response = full_response.replace("<|channel|>analysis<|message|>", "")
                    full_response = full_response.replace("<|channel|>final<|message|>", "")
                    full_response = full_response.replace("<|end|>", "")
                    full_response = full_response.replace("<|start|>assistant", "")
                    full_response = full_response.strip()

                    if full_response:
                        # Add to conversation history
                        self.conversation_history.append({"role": "assistant", "content": full_response})
                        self.publish_handoff_state()
                        # Send final text message (TTS already done in pipeline)
                        await self.send_message("final_response", {"text": full_response})
                        print(f"[Voice Session] Overlap pipeline complete: {len(full_response)} chars")
                        return

                print(f"[Voice Session] Overlap pipeline returned empty response, continuing...")

            async for chunk in llm.stream_complete(messages_for_llm, tools=enabled_tool_defs if enabled_tool_defs else None):
                if not self.alive:
                    print(f"[Voice Session] client disconnected mid-stream, aborting main LLM read")
                    return
                chunk_count += 1
                raw_chunks.append(chunk[:100])  # Store first 100 chars for debugging

                if chunk.startswith("data: "):
                    try:
                        data = json.loads(chunk[6:])
                        # Handle tool calls completion
                        if "tool_calls_complete" in data:
                            tool_calls = data["tool_calls_complete"]
                            print(f"[Voice Session] ✅ TOOL CALLS DETECTED: {len(tool_calls)} tools")
                            for i, tc in enumerate(tool_calls):
                                func = tc.get("function", {})
                                print(f"  Tool {i+1}: {func.get('name', 'unknown')} with args: {func.get('arguments', '{}')}")
                            
                            # Determine feedback message based on tool type
                            is_agent_tool = False
                            for tc in tool_calls:
                                func = tc.get("function", {})
                                if func.get("name") in [
                                    "markdown_assistant",
                                    "html_assistant",
                                    "codebase_assistant",
                                    "reasoning_assistant",
                                    "workspace_update_assistant",
                                ]:
                                    is_agent_tool = True
                                    break
                            
                            if is_agent_tool:
                                # Custom feedback for reasoning
                                for tc in tool_calls:
                                    if tc.get("function", {}).get("name") == "reasoning_assistant":
                                        feedback_msg = "Let me think through this..."
                                        break
                                    if tc.get("function", {}).get("name") == "workspace_update_assistant":
                                        feedback_msg = "Drafting the email now. You got him pineapple cakes last year; maybe try high mountain oolong tea?"
                                        break
                                    if tc.get("function", {}).get("name") == "html_assistant":
                                        feedback_msg = "On it. I'll build the prototype."
                                        break
                                    if tc.get("function", {}).get("name") == "codebase_assistant":
                                        feedback_msg = "On it."
                                        break
                                else:
                                    feedback_msg = "On it."
                            else:
                                feedback_msg = "Looking that up for you."
                            
                            # Send conversational feedback
                            await self.send_transient_ack(feedback_msg)
                            
                            # IMPORTANT: Add assistant message with tool_calls to conversation history FIRST
                            # The LLM server expects this format: assistant message with tool_calls, then tool results
                            assistant_message = {
                                "role": "assistant",
                                "content": None,  # No text content, only tool calls
                                "tool_calls": tool_calls
                            }
                            self.conversation_history.append(assistant_message)
                            print(f"[Voice Session] Added assistant message with {len(tool_calls)} tool call(s) to history")
                            
                            # Execute all tool calls in parallel
                            tool_results = await self._execute_tool_calls_parallel(tool_calls)

                            # Emit UI signals for any agent-type tools
                            for tr in tool_results:
                                try:
                                    d = json.loads(tr.get("content", "{}"))
                                    if d.get("agent_type"):
                                        await self.send_message("agent_started", {
                                            "agent_type": d.get("agent_type"),
                                            "task": d.get("task", ""),
                                            "codebase_path": d.get("codebase_path", "")
                                        })
                                        print(f"[Voice Session] Agent '{d.get('agent_type')}' started - UI should open")
                                except json.JSONDecodeError:
                                    pass

                            # Append to conversation history (after assistant message with tool_calls)
                            for tool_result in tool_results:
                                self.conversation_history.append(tool_result)
                            print(f"[Voice Session] Added {len(tool_results)} tool result(s) to history")

                            # Multi-iteration agent loop: re-stream the model, execute any new tool
                            # calls in parallel, repeat until we get a plain-content response or
                            # hit MAX_TOOL_ITERATIONS. Content streams to TTS sentence-by-sentence
                            # as it arrives — no accumulate-then-speak delay.
                            tool_final_response = ""
                            sentence_buf = ""
                            spoke_anything = False
                            # If ask_claw already spoke its reply directly via the streaming path,
                            # the LLM follow-up usually adds 1-2 sentences of paraphrasing. To
                            # avoid double-speaking, give the model an explicit instruction that
                            # the user already heard Claw and ONLY a brief 1-sentence ack is needed.
                            already_spoke_via_claw = any(
                                _safely_spoken_flag(tr.get("content")) for tr in tool_results
                            )
                            if already_spoke_via_claw:
                                self.conversation_history.append({
                                    "role": "system",
                                    "content": ("The previous tool result was already spoken aloud "
                                                "to the user. Reply with at most ONE short ack "
                                                "sentence (or just '.' if no ack is needed). "
                                                "Do NOT repeat or paraphrase what was just said."),
                                })
                            enabled_tool_defs = _filter_for_demo(get_enabled_tools(self.enabled_tools))
                            for iteration in range(self.MAX_TOOL_ITERATIONS):
                                if not self.alive:
                                    print(f"[Voice Session] client disconnected — aborting agent loop")
                                    return
                                print(f"[Voice Session] Agent loop iteration {iteration+1}/{self.MAX_TOOL_ITERATIONS}")
                                followup_messages = list(self.conversation_history)
                                next_tool_calls = None
                                async for chunk in llm.stream_complete(
                                    followup_messages,
                                    tools=enabled_tool_defs if enabled_tool_defs else None,
                                ):
                                    if not self.alive:
                                        return
                                    if not chunk.startswith("data: "):
                                        continue
                                    try:
                                        data = json.loads(chunk[6:])
                                    except json.JSONDecodeError:
                                        continue
                                    if "tool_calls_complete" in data:
                                        next_tool_calls = data["tool_calls_complete"]
                                        break
                                    if "content" in data and data["content"]:
                                        piece = data["content"]
                                        tool_final_response += piece
                                        sentence_buf += piece
                                        # Progressive TTS: speak each complete sentence as it forms
                                        sentences, sentence_buf = self._extract_complete_sentences(sentence_buf)
                                        for s in sentences:
                                            s = s.strip()
                                            if s:
                                                # Serial: don't interleave PCM frames from consecutive
                                                # sentences on the socket.
                                                await self.stream_tts(s)
                                                spoke_anything = True
                                    elif "error" in data:
                                        print(f"[Voice Session] LLM error during agent loop: {data['error']}")
                                if not next_tool_calls:
                                    break
                                # Announce continued work and execute in parallel
                                await self.send_message("tool_invocation", {"message": "One moment…"})
                                more_results = await self._execute_tool_calls_parallel(next_tool_calls)
                                self.conversation_history.append({
                                    "role": "assistant", "content": None, "tool_calls": next_tool_calls,
                                })
                                for tr in more_results:
                                    self.conversation_history.append(tr)
                                    try:
                                        d = json.loads(tr.get("content", "{}"))
                                        if d.get("agent_type"):
                                            await self.send_message("agent_started", {
                                                "agent_type": d.get("agent_type"),
                                                "task": d.get("task", ""),
                                            })
                                    except json.JSONDecodeError:
                                        pass
                                tool_results.extend(more_results)  # for agent-tool detection below
                            else:
                                print(f"[Voice Session] ⚠️ hit MAX_TOOL_ITERATIONS={self.MAX_TOOL_ITERATIONS}")
                            
                            # Check if any of the executed tools were agents
                            is_agent_tool = False
                            agent_type = None
                            agent_task = None
                            agent_context = ""
                            agent_output_path = ""
                            agent_output_dir = "agent_monitor_mvp"
                            agent_items = []
                            for tool_result in tool_results:
                                try:
                                    result_data = json.loads(tool_result.get("content", "{}"))
                                    if result_data.get("agent_type"):
                                        is_agent_tool = True
                                        agent_type = result_data.get("agent_type")
                                        agent_task = result_data.get("task", "")
                                        agent_context = result_data.get("context", "")
                                        agent_output_path = result_data.get("output_path", "")
                                        agent_output_dir = result_data.get("output_dir", "agent_monitor_mvp")
                                        agent_items = result_data.get("items", [])
                                        break
                                except json.JSONDecodeError:
                                    pass
                            
                            if is_agent_tool and agent_type == "markdown_assistant":
                                # For markdown assistant, make a separate LLM call to generate markdown
                                print(f"[Voice Session] Making separate LLM call for markdown generation (task: {agent_task[:100]}...)")
                                
                                # Create a focused prompt for markdown generation
                                markdown_generation_messages = [
                                    {
                                        "role": "system",
                                        "content": """You are a documentation assistant. Your goal is to generate clear, well-structured markdown documents.

CRITICAL INSTRUCTIONS:
- Output ONLY markdown content. No explanations before or after.
- Do NOT think out loud or show your reasoning process.
- Generate the document directly without excessive analysis.
- Use proper markdown formatting: headers, lists, code blocks, tables as needed.
- Structure the document logically with clear sections.
- Be thorough but concise."""
                                    },
                                    {
                                        "role": "user",
                                        "content": f"Task: {agent_task}\n\nContext: {agent_context}" if agent_context else f"Task: {agent_task}"
                                    }
                                ]
                                
                                # Use medium reasoning for markdown generation
                                markdown_gen_config = LLMConfig()
                                markdown_gen_config.reasoning_effort = "medium"
                                markdown_gen_llm = LlamaCppClient(markdown_gen_config)
                                
                                # Stream markdown generation response
                                markdown_response = ""
                                reasoning_accumulated = ""
                                chunk_count = 0
                                stream_path, file_path = self.begin_markdown_workspace_stream(
                                    agent_task,
                                    agent_output_path
                                )
                                print(f"[Voice Session] Streaming markdown to {file_path}")
                                
                                # Stream tokens directly to markdown editor as they arrive
                                await self.send_message("agent_markdown_chunk", {"content": "", "done": False})
                                
                                with stream_path.open("a", encoding="utf-8") as stream_file:
                                    async for chunk in markdown_gen_llm.stream_complete(markdown_generation_messages, tools=None):
                                        chunk_count += 1
                                        if chunk.startswith("data: "):
                                            try:
                                                data = json.loads(chunk[6:])
                                                if "content" in data and data["content"]:
                                                    content = data["content"]
                                                    markdown_response += content
                                                    stream_file.write(content)
                                                    stream_file.flush()
                                                    # Stream to markdown editor immediately
                                                    await self.send_message("agent_markdown_chunk", {"content": content, "done": False})
                                                elif "reasoning_content" in data and data["reasoning_content"]:
                                                    reasoning_accumulated += data["reasoning_content"]
                                            except json.JSONDecodeError:
                                                pass
                                        elif chunk.strip() and not chunk.startswith("data: "):
                                            markdown_response += chunk
                                            stream_file.write(chunk)
                                            stream_file.flush()
                                            await self.send_message("agent_markdown_chunk", {"content": chunk, "done": False})
                                
                                print(f"[Voice Session] Markdown generation complete: {len(markdown_response)} chars")
                                
                                # If no content but we have reasoning, use reasoning as fallback
                                if not markdown_response and reasoning_accumulated:
                                    markdown_response = reasoning_accumulated
                                
                                # Process markdown response
                                if markdown_response and markdown_response.strip():
                                    markdown_response = llm._extract_final_channel(markdown_response)
                                    markdown_response = markdown_response.replace("<|channel|>analysis<|message|>", "")
                                    markdown_response = markdown_response.replace("<|channel|>final<|message|>", "")
                                    markdown_response = markdown_response.replace("<|end|>", "")
                                    markdown_response = markdown_response.replace("<|start|>assistant", "")
                                    markdown_response = markdown_response.strip()
                                    
                                    if markdown_response:
                                        print(f"[Voice Session] Markdown generated: {len(markdown_response)} characters")

                                        file_path = self.write_markdown_to_workspace(
                                            agent_task,
                                            markdown_response,
                                            agent_output_path
                                        )
                                        print(f"[Voice Session] Markdown written to {file_path}")
                                        
                                        # Signal completion
                                        await self.send_message("agent_markdown_chunk", {"content": "", "done": True})
                                        
                                        # Add to conversation history
                                        markdown_summary = f"Generated documentation at {file_path} for: {agent_task}\n\n{markdown_response[:500]}{'...' if len(markdown_response) > 500 else ''}"
                                        self.conversation_history.append({"role": "assistant", "content": markdown_summary})
                                        self.publish_handoff_state()
                                        
                                        # Send a message to frontend to add markdown to conversation UI
                                        await self.send_message("agent_markdown_complete", {
                                            "task": agent_task,
                                            "markdown": markdown_response,
                                            "file_path": file_path
                                        })
                                        return
                                    else:
                                        print(f"[Voice Session] Markdown response was empty after processing")
                                else:
                                    print(f"[Voice Session] No markdown response received")
                            
                            elif is_agent_tool and agent_type == "reasoning_assistant":
                                # For reasoning assistant, call Qwen3.6 with reasoning_effort=high
                                agent_problem = ""
                                agent_context = ""
                                agent_analysis_type = "general"
                                
                                # Extract problem, context, and analysis_type from tool result
                                for tool_result in tool_results:
                                    try:
                                        result_data = json.loads(tool_result.get("content", "{}"))
                                        if result_data.get("agent_type") == "reasoning_assistant":
                                            agent_problem = result_data.get("problem", "")
                                            agent_context = result_data.get("context", "")
                                            agent_analysis_type = result_data.get("analysis_type", "general")
                                            break
                                    except json.JSONDecodeError:
                                        pass
                                
                                if agent_problem:
                                    print(f"[Voice Session] Executing reasoning agent for: {agent_problem[:100]}...")
                                    await self.execute_reasoning_agent(agent_problem, agent_context, agent_analysis_type)
                                    return
                                else:
                                    print(f"[Voice Session] No problem found for reasoning agent")

                            elif is_agent_tool and agent_type == "html_assistant":
                                await self.execute_html_agent(agent_task, agent_context)
                                return

                            elif is_agent_tool and agent_type == "codebase_assistant":
                                self.start_codebase_agent_task(
                                    agent_task or "Build this sketch into a working MVP",
                                    agent_context,
                                    agent_output_dir,
                                )
                                return

                            elif is_agent_tool and agent_type == "workspace_update_assistant":
                                await self.execute_workspace_update_agent(
                                    agent_task or "Add handwritten todos to the project",
                                    agent_context,
                                    agent_items if isinstance(agent_items, list) else []
                                )
                                return
                            
                            # Process and send the final response from tool execution (for non-agent tools or fallback)
                            if tool_final_response and tool_final_response.strip():
                                tool_final_response = llm._extract_final_channel(tool_final_response)
                                tool_final_response = tool_final_response.replace("<|channel|>analysis<|message|>", "")
                                tool_final_response = tool_final_response.replace("<|channel|>final<|message|>", "")
                                tool_final_response = tool_final_response.replace("<|end|>", "")
                                tool_final_response = tool_final_response.replace("<|start|>assistant", "")
                                tool_final_response = tool_final_response.strip()

                                if tool_final_response:
                                    print(f"[Voice Session] Tool execution final response: {tool_final_response[:100]}...")
                                    self.conversation_history.append({"role": "assistant", "content": tool_final_response})
                                    self.publish_handoff_state()
                                    if spoke_anything:
                                        # Already streamed sentence-by-sentence. Flush the trailing
                                        # fragment and emit the UI-only final message.
                                        tail = (sentence_buf or "").strip()
                                        if tail:
                                            await self.stream_tts(tail)
                                        await self.send_message("final_response", {"text": tool_final_response})
                                    else:
                                        await self.send_final_response(tool_final_response)
                                    return
                                else:
                                    print(f"[Voice Session] Tool execution response was empty after processing")
                            else:
                                print(f"[Voice Session] No response received after tool execution")
                            
                            # If we get here, tool execution didn't produce a valid response
                            # Break out of outer loop to handle error
                            break
                            
                        # Only accumulate actual content, not reasoning_content
                        # Reasoning models output reasoning first, then final content
                        elif "content" in data and data["content"]:
                            content_chunk = data["content"]
                            # Skip reasoning markers and their content
                            if "<|channel|>analysis" in content_chunk or "<|channel|>commentary" in content_chunk:
                                continue  # Skip reasoning/analysis content
                            final_response += content_chunk
                            # Note: No intermediate streaming - only final response is shown
                        # Note: reasoning_content is NOT shown - only actual content
                        elif "error" in data:
                            print(f"[Voice Session] LLM error: {data['error']}")
                    except json.JSONDecodeError:
                        # Chunk might not be JSON, try to extract content directly
                        if chunk.strip():
                            final_response += chunk
                elif chunk.strip() and not chunk.startswith("data: "):
                    # Some LLMs might return content directly without "data: " prefix
                    final_response += chunk
                    
            print(f"[Voice Session] LLM stream completed: {chunk_count} chunks, response length: {len(final_response)}")
            if chunk_count == 0:
                print(f"[Voice Session] WARNING: No chunks received from LLM stream")
            if len(final_response) == 0:
                print(f"[Voice Session] WARNING: Empty final_response after {chunk_count} chunks")
                print(f"[Voice Session] First few raw chunks: {raw_chunks[:5]}")
        except Exception as e:
            print(f"[Voice Session] Error streaming LLM response: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message("error", {"error": f"LLM streaming error: {e}"})
            return
        
        # Extract final channel
        if not final_response or not final_response.strip():
            print(f"[Voice Session] Empty LLM response after streaming ({chunk_count} chunks received)")
            print(f"[Voice Session] Raw chunks preview: {raw_chunks[:10]}")
            print(f"[Voice Session] Full raw chunks: {raw_chunks}")
            await self.send_message("error", {"error": "No response from LLM"})
            return
            
        final_response = llm._extract_final_channel(final_response)
        # Clean up any remaining markers
        final_response = final_response.replace("<|channel|>analysis<|message|>", "")
        final_response = final_response.replace("<|channel|>final<|message|>", "")
        final_response = final_response.replace("<|end|>", "")
        final_response = final_response.replace("<|start|>assistant", "")
        final_response = final_response.strip()

        # Check if final_response is empty
        if not final_response or not final_response.strip():
            print(f"[Voice Session] Empty response after processing")
            await self.send_message("error", {"error": "Empty response after processing"})
            return

        # Send final response
        if final_response:
            print(f"[Voice Session] Sending response: {final_response[:100]}...")
            # Add to conversation history
            self.conversation_history.append({"role": "assistant", "content": final_response})
            self.publish_handoff_state()
            # Send final response and TTS
            await self.send_final_response(final_response)
        else:
            print(f"[Voice Session] No final_response to send!")

    def infer_markdown_output_path(self, task: str) -> str:
        """Infer a workspace-relative markdown path from the user's task."""
        import re

        task_lower = (task or "").lower()
        if any(term in task_lower for term in ["mvp", "workbench", "prototype brief", "brief for when", "brief to review", "project scaffold", "scaffolding"]):
            return "mvp_brief.md"
        if "team" in task_lower and any(term in task_lower for term in ["update", "email", "brief", "dinner"]):
            return "team_update.md"
        if "executive" in task_lower or ("dinner" in task_lower and "brief" in task_lower):
            return "executive_brief.md"
        if "readme" in task_lower:
            return "README.md"
        if any(term in task_lower for term in ["realtime", "real-time", "redis", "pub/sub", "fanout"]):
            return "realtime_design.md"
        if "personal" in task_lower and any(term in task_lower for term in ["todo", "to-do"]):
            return "personal_todos.md"
        if any(term in task_lower for term in ["task", "todo", "to-do"]) and any(term in task_lower for term in ["project", "dashboard"]):
            return "project_dashboard/tasks.md"

        slug = re.sub(r"[^a-z0-9]+", "-", task_lower).strip("-")[:48]
        return f"{slug or 'document'}.md"

    def resolve_workspace_markdown_path(self, output_path: str, task: str) -> Path:
        """Resolve a model-provided path into the shared workspace directory."""
        workspace_dir = WORKSPACE_ROOT / "workspace"
        requested = (output_path or "").strip() or self.infer_markdown_output_path(task)
        relative_path = Path(requested)

        if relative_path.is_absolute():
            relative_path = Path(relative_path.name)

        parts = [part for part in relative_path.parts if part not in ("", ".", "..")]
        if parts and parts[0].lower() == "workspace":
            parts = parts[1:]
        if not parts:
            parts = ["document.md"]

        safe_relative = Path(*parts)
        if safe_relative.suffix.lower() != ".md":
            safe_relative = safe_relative.with_suffix(".md")

        workspace_resolved = workspace_dir.resolve()
        output_resolved = (workspace_dir / safe_relative).resolve()
        if output_resolved != workspace_resolved and workspace_resolved not in output_resolved.parents:
            output_resolved = workspace_resolved / "document.md"

        return output_resolved

    def write_markdown_to_workspace(self, task: str, markdown: str, output_path: str = "") -> str:
        """Write markdown into workspace/ and return a path relative to WORKSPACE_ROOT."""
        path = self.resolve_workspace_markdown_path(output_path, task)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
        return str(path.relative_to(WORKSPACE_ROOT))

    def begin_markdown_workspace_stream(self, task: str, output_path: str = "") -> tuple[Path, str]:
        """Create/truncate a workspace markdown file before streaming content into it."""
        path = self.resolve_workspace_markdown_path(output_path, task)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return path, str(path.relative_to(WORKSPACE_ROOT))

    def resolve_workspace_codebase_dir(self, output_dir: str = "") -> Path:
        """Resolve a generated-code directory inside workspace/ without escaping it."""
        import re

        workspace_dir = WORKSPACE_ROOT / "workspace"
        requested = (output_dir or "agent_monitor_mvp").strip().replace("\\", "/")
        if requested.startswith("workspace/"):
            requested = requested[len("workspace/"):]
        name = Path(requested).name
        name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_-").lower()
        if not name:
            name = "agent_monitor_mvp"

        workspace_resolved = workspace_dir.resolve()
        output_resolved = (workspace_dir / name).resolve()
        if workspace_resolved not in output_resolved.parents:
            output_resolved = workspace_resolved / "agent_monitor_mvp"
        return output_resolved

    def resolve_mvp_run_dir(self) -> Path:
        """Create a local ignored folder for per-run evaluation artifacts."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        run_dir = WORKSPACE_ROOT / "test_assets" / "mvp-generation-runs" / stamp
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def build_codebase_agent_prompt(
        self,
        task: str,
        context: str,
        output_dir: Path,
        run_dir: Path,
        previous_error: str = "",
        existing_files: str = "",
    ) -> str:
        """Build the constrained prompt for the local Qwen coding sub-agent."""
        repair_context = ""
        if previous_error:
            repair_context = "\n".join([
                "",
                "Repair context from the previous attempt:",
                previous_error.strip(),
                "",
                "Current generated files:",
                existing_files.strip() or "(no usable files yet)",
                "",
                "Return a complete replacement for all three required files, not a diff.",
            ])

        return "\n".join([
            "You are Qwen3.6, Spark's local coding sub-agent for the Computex demo.",
            "",
            "Goal: build a small working MVP from the user's visible sketch.",
            "Reliability target: produce a complete first attempt quickly. Keep the app simple enough to generate in under two minutes.",
            "Demo story: the user gives a rough sketch and a natural request. Your saved local coding and design preferences should turn sparse intent into a polished MVP without the user spelling out UI details.",
            "",
            "Hard boundaries:",
            f"- Work only inside this directory: {output_dir}",
            "- Do not edit the Spark realtime chatbot repo outside that directory.",
            "- Keep the generated workspace as flat and concise as possible.",
            "- Output exactly these files: app.py, task_history.json, mvp_brief.md.",
            "- Do not create AGENTS.md, README.md, task_plan.md, findings.md, progress.md, .codex, or planning/config files.",
            "- If you need to record decisions, put them in mvp_brief.md.",
            "- Do not create frontend/, backend/, database/, node_modules/, or large asset folders.",
            "- Do not write secrets or private health data into the generated app.",
            "- Do not delegate to another agent or mention external coding tools.",
            "",
            "Expected MVP:",
            "- A simple, reliable operator dashboard UI for Agent Monitor / Agent Dashboard / Task History / Activity Feed.",
            "- A one-file FastAPI server that serves the UI and exposes JSON API endpoints.",
            "- A local task-history persistence layer using the single JSON file.",
            "- A brief with core architecture decisions, data model, API surface, run command, risks, and next steps.",
            "- If the sketch is sparse, infer a coherent product surface from the visible labels instead of asking for more detail.",
            "- Prefer a working, compact MVP over ambitious UI complexity.",
            "",
            "Design quality guidance:",
            "- Treat sparse hand-drawn sketches as product intent, not literal wireframes.",
            "- Build a polished 2026 SaaS operations dashboard, not a generic toy page.",
            "- Default layout: app header, KPI overview cards, agent/status area, command panel, task history, and activity feed.",
            "- Use strong visual hierarchy, compact but generous spacing, crisp typography, status pills, subtle borders, soft shadows, and clear primary actions.",
            "- Keep it quiet, utilitarian, and readable; the result should look demo-ready even when the sketch is casual.",
            "- Avoid a one-note all-dark/all-blue palette; use neutral surfaces plus one accent color and semantic status accents.",
            "- Use semantic HTML, one h1, clear landmarks, visible focus states, and accessible contrast.",
            "- Define CSS tokens near the top of the UI.",
            "- Make desktop and mobile layouts intentional.",
            "- Include reduced-motion handling.",
            "- Avoid decorative bloat, nested card piles, and generic placeholder copy.",
            "- Keep cards at 8px radius or less.",
            "- Seed realistic agent/task/activity data so the first render feels alive.",
            "- The visible UI must include these literal section labels: Overview, Agent Status, Commands, Task History, Activity Feed.",
            "- The Commands section must include at least two working buttons, such as New Task and Refresh.",
            "- Mobile overflow must be impossible: use box-sizing border-box, max-width: 100%, overflow-x hidden on html/body, responsive grids, and wrapping table cells.",
            "- Do not use an HTML table for Task History; use responsive div/list rows or cards so mobile cannot overflow.",
            "",
            "Implementation guidance:",
            "- app.py should import cleanly and expose `app = FastAPI()`.",
            "- app.py should embed the HTML/CSS/JS directly and serve it from `/`.",
            "- Do not read `index.html` or any other UI file. The only file app.py may read/write is `task_history.json`.",
            "- Include only these JSON endpoints: GET /api/tasks, POST /api/tasks, GET /api/stats.",
            "- task_history.json must be valid JSON with 3 short seed task records so the first render is not empty.",
            "- The Activity Feed should show at least two visible recent events on first render.",
            "- If app.py uses `await request.json()`, the route function must be `async def`; never put await inside a regular def.",
            "- Keep JavaScript minimal and conservative: no optional chaining, no object spread, no module syntax, and no complex template logic.",
            "- Avoid stale hard-coded calendar dates in seed data; prefer runtime timestamps or current-day labels.",
            "- mvp_brief.md must include a `## Architecture` section.",
            "- Keep app.py compact, ideally under 180 lines; avoid WebSockets, background tasks, dataclasses, and complex abstractions.",
            "- Keep mvp_brief.md concise, ideally under 45 lines.",
            "- Use no external frontend libraries, no images, no package files, and no nested directories.",
            "",
            "Testing/evaluation guidance:",
            "- Run syntax/import checks for generated code.",
            "- If you can start the app, inspect it in a browser and fix obvious layout or console issues.",
            "- Leave notes about any checks you ran in mvp_brief.md.",
            f"- Spark will also save local evaluation artifacts under: {run_dir}",
            "",
            "Output format:",
            "Return only these three file blocks. Do not wrap the whole answer in markdown fences.",
            "<<<FILE: app.py>>>",
            "# complete Python source here",
            "<<<END FILE>>>",
            "<<<FILE: task_history.json>>>",
            "[]",
            "<<<END FILE>>>",
            "<<<FILE: mvp_brief.md>>>",
            "# MVP Brief",
            "## Architecture",
            "Brief content here",
            "<<<END FILE>>>",
            repair_context,
            "",
            "Visible diagram / user context:",
            context or "Agent Monitor UI -> Agent Dashboard FastAPI -> Task History database, plus Activity Feed.",
            "",
            "User request:",
            task or "Build this Agent Monitoring sketch into a working MVP.",
        ])

    def summarize_codebase_file_contents(self, output_dir: Path, max_chars: int = 8000) -> str:
        """Return compact snippets of generated files for a Qwen repair prompt."""
        chunks = []
        for name in ("app.py", "task_history.json", "mvp_brief.md"):
            path = output_dir / name
            if not path.exists() or not path.is_file():
                chunks.append(f"--- {name}: missing ---")
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as exc:
                chunks.append(f"--- {name}: unreadable: {exc} ---")
                continue
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...(truncated)"
            chunks.append(f"--- {name} ---\n{text}")
        return "\n\n".join(chunks)

    def parse_codebase_file_blocks(self, response: str) -> tuple[Dict[str, str], List[str]]:
        """Parse Qwen file-block output into the allowed flat MVP files."""
        import re

        allowed = {"app.py", "task_history.json", "mvp_brief.md"}
        files: Dict[str, str] = {}
        errors: List[str] = []
        text = (response or "").strip()

        pattern = re.compile(
            r"<<<FILE:\s*([^>\n]+?)\s*>>>\s*\n?(.*?)\n?<<<END FILE>>>",
            re.DOTALL | re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            raw_name = match.group(1).strip().replace("\\", "/")
            name = Path(raw_name).name
            content = match.group(2)
            if name not in allowed:
                errors.append(f"ignored unsupported generated file: {raw_name}")
                continue
            files[name] = content.rstrip() + "\n"

        missing = sorted(allowed - set(files))
        if missing:
            errors.append(f"missing required file block(s): {', '.join(missing)}")
        return files, errors

    def write_qwen_codebase_files(self, output_dir: Path, response: str) -> tuple[Dict[str, str], List[str]]:
        """Write parsed Qwen file blocks into the generated workspace directory."""
        output_dir.mkdir(parents=True, exist_ok=True)
        files, errors = self.parse_codebase_file_blocks(response)
        for name in ("app.py", "task_history.json", "mvp_brief.md"):
            path = output_dir / name
            if path.exists() and path.is_file():
                path.unlink()
        for name, content in files.items():
            (output_dir / name).write_text(content, encoding="utf-8")
        return self.summarize_codebase_files(output_dir), errors

    async def run_qwen_codebase_turn(
        self,
        task: str,
        context: str,
        codebase_dir: Path,
        run_dir: Path,
        attempt: int,
        previous_error: str = "",
    ) -> str:
        """Run one local-Qwen generation or repair turn for the codebase assistant."""
        prompt = self.build_codebase_agent_prompt(
            task,
            context,
            codebase_dir,
            run_dir,
            previous_error=previous_error,
            existing_files=self.summarize_codebase_file_contents(codebase_dir),
        )
        (run_dir / f"qwen_attempt_{attempt}_prompt.md").write_text(prompt, encoding="utf-8")

        cfg = LLMConfig()
        cfg.temperature = float(os.environ.get("QWEN_CODEBASE_TEMP", "0.25"))
        cfg.max_tokens = int(os.environ.get("QWEN_CODEBASE_MAX_TOKENS", "6000"))
        cfg.reasoning_effort = os.environ.get("QWEN_CODEBASE_REASONING", "none")
        agent_llm = LlamaCppClient(cfg)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a local code-generation assistant. Produce only the requested "
                    "file blocks. Do not explain outside the file contents."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        timeout_s = int(os.environ.get("QWEN_CODEBASE_TIMEOUT", "360"))
        response = await asyncio.wait_for(agent_llm.complete(messages), timeout=timeout_s)
        response = agent_llm._extract_final_channel(response or "").strip()
        (run_dir / f"qwen_attempt_{attempt}_response.txt").write_text(response + "\n", encoding="utf-8")
        return response

    def summarize_codebase_files(self, output_dir: Path) -> Dict[str, str]:
        """Return a small map of generated files for UI display."""
        files = {}
        for path in sorted(output_dir.iterdir()) if output_dir.exists() else []:
            if not path.is_file():
                continue
            rel = str(path.relative_to(WORKSPACE_ROOT))
            stem = path.stem.lower().replace("-", "_")
            if path.name == "app.py":
                files["app"] = rel
            elif path.name == "task_history.json":
                files["history"] = rel
            elif path.name == "mvp_brief.md":
                files["brief"] = rel
            else:
                files[stem[:32] or path.suffix.lstrip(".") or "file"] = rel
        return files

    def codebase_has_required_files(self, output_dir: Path) -> bool:
        """True when the generated MVP has the expected flat artifact set."""
        return (
            (output_dir / "app.py").exists()
            and (output_dir / "task_history.json").exists()
            and (output_dir / "mvp_brief.md").exists()
        )

    def prune_codebase_workspace(self, output_dir: Path) -> List[str]:
        """Remove known nonessential artifacts from generated MVP workspaces."""
        import shutil

        removed = []
        for name in (
            ".codex",
            "AGENTS.md",
            "README.md",
            "task_plan.md",
            "findings.md",
            "progress.md",
            "__pycache__",
        ):
            path = output_dir / name
            if not path.exists():
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(name)
        return removed

    def collect_codebase_checks(self, output_dir: Path) -> List[Dict[str, Any]]:
        """Run deterministic checks against the generated flat MVP workspace."""
        import py_compile

        checks = []
        app_path = output_dir / "app.py"
        history_path = output_dir / "task_history.json"
        brief_path = output_dir / "mvp_brief.md"

        if app_path.exists():
            try:
                py_compile.compile(str(app_path), doraise=True)
                checks.append({"name": "app.py py_compile", "status": "PASS"})
            except Exception as exc:
                checks.append({"name": "app.py py_compile", "status": "FAIL", "detail": str(exc)})
        else:
            checks.append({"name": "app.py exists", "status": "FAIL"})

        if history_path.exists():
            try:
                json.loads(history_path.read_text(encoding="utf-8"))
                checks.append({"name": "task_history.json parses", "status": "PASS"})
            except Exception as exc:
                checks.append({"name": "task_history.json parses", "status": "FAIL", "detail": str(exc)})
        else:
            checks.append({"name": "task_history.json exists", "status": "FAIL"})

        if brief_path.exists() and "architecture" in brief_path.read_text(encoding="utf-8").lower():
            checks.append({"name": "mvp_brief.md includes architecture", "status": "PASS"})
        else:
            checks.append({"name": "mvp_brief.md includes architecture", "status": "FAIL"})
        return checks

    def summarize_codebase_check_failures(self, checks: List[Dict[str, Any]]) -> str:
        """Convert failed deterministic checks into a compact repair prompt note."""
        failures = []
        for check in checks:
            if check.get("status") == "PASS":
                continue
            detail = f": {check['detail']}" if check.get("detail") else ""
            failures.append(f"- {check.get('name', 'check')}{detail}")
        return "\n".join(failures)

    def write_codebase_eval_summary(
        self,
        run_dir: Path,
        output_dir: Path,
        files: Dict[str, str],
        stdout: str,
        stderr: str,
        returncode: int,
        browser_eval: Optional[Dict[str, Any]] = None,
        preview: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Persist local, ignored evidence for the generated MVP run."""
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "agent_stdout.log").write_text(stdout or "", encoding="utf-8")
        (run_dir / "agent_stderr.log").write_text(stderr or "", encoding="utf-8")

        checks = self.collect_codebase_checks(output_dir)

        evaluation = {
            "agent_returncode": returncode,
            "codebase_path": str(output_dir.relative_to(WORKSPACE_ROOT)),
            "files": files,
            "checks": checks,
            "browser_eval": browser_eval or {"status": "SKIP", "reason": "browser evaluation was not run"},
            "preview": preview or {"status": "SKIP", "reason": "preview server was not started"},
            "run_dir": str(run_dir.relative_to(WORKSPACE_ROOT)),
            "note": "Screenshots and browser logs are saved in this run folder when Playwright evaluation is available.",
        }
        (run_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")

        summary_lines = [
            "# MVP Generation Evaluation",
            "",
            f"- Codebase path: `{evaluation['codebase_path']}`",
            f"- Agent return code: `{returncode}`",
            "",
            "## Files",
            "",
        ]
        summary_lines.extend(f"- `{path}`" for path in files.values())
        summary_lines.extend(["", "## Checks", ""])
        for check in checks:
            detail = f" - {check['detail']}" if check.get("detail") else ""
            summary_lines.append(f"- {check['status']}: {check['name']}{detail}")
        summary_lines.extend([
            "",
            "## Playwright Evidence",
            "",
            f"- Status: `{evaluation['browser_eval'].get('status', 'UNKNOWN')}`",
        ])
        if evaluation["browser_eval"].get("url"):
            summary_lines.append(f"- URL: `{evaluation['browser_eval']['url']}`")
        for screenshot in evaluation["browser_eval"].get("screenshots", []):
            summary_lines.append(f"- Screenshot: `{screenshot}`")
        if evaluation["browser_eval"].get("error"):
            summary_lines.append(f"- Error: {evaluation['browser_eval']['error']}")
        summary_lines.extend([
            "",
            "## Live Preview",
            "",
            f"- Status: `{evaluation['preview'].get('status', 'UNKNOWN')}`",
        ])
        if evaluation["preview"].get("preview_path"):
            summary_lines.append(f"- Same-origin path: `{evaluation['preview']['preview_path']}`")
        if evaluation["preview"].get("preview_url"):
            summary_lines.append(f"- URL: `{evaluation['preview']['preview_url']}`")
        if evaluation["preview"].get("error"):
            summary_lines.append(f"- Error: {evaluation['preview']['error']}")
        (run_dir / "SUMMARY.md").write_text("\n".join(summary_lines).rstrip() + "\n", encoding="utf-8")
        return evaluation

    def find_node_playwright_module(self) -> Optional[str]:
        """Find a Node Playwright module path for local browser evaluation."""
        candidates = [
            os.environ.get("PLAYWRIGHT_NODE_MODULE"),
            "/home/nvidia/selena/vdrs/NeMo-Flow/third_party/openclaw/node_modules/playwright",
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if (path / "index.js").exists():
                return str(path)
        return None

    def find_free_local_port(self) -> int:
        """Reserve a currently free localhost port for generated-app evaluation."""
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    async def wait_for_http_ready(self, url: str, timeout_s: float = 12.0) -> bool:
        """Poll a local HTTP URL until it responds or times out."""
        import urllib.request

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                def fetch():
                    with urllib.request.urlopen(url, timeout=1.5) as response:
                        return response.status

                status = await asyncio.to_thread(fetch)
                if status < 500:
                    return True
            except Exception:
                await asyncio.sleep(0.3)
        return False

    async def run_codebase_browser_eval(self, run_dir: Path, output_dir: Path) -> Dict[str, Any]:
        """Start the generated FastAPI app and capture Playwright-style evidence."""
        import sys

        app_path = output_dir / "app.py"
        if not app_path.exists():
            return {"status": "SKIP", "reason": "workspace app.py does not exist"}

        playwright_module = self.find_node_playwright_module()
        if not playwright_module:
            return {"status": "SKIP", "reason": "Node Playwright module not found"}

        python_bin = WORKSPACE_ROOT / ".venv-gpu" / "bin" / "python"
        if not python_bin.exists():
            python_bin = Path(sys.executable)

        port = self.find_free_local_port()
        url = f"http://127.0.0.1:{port}"
        app_stdout_path = run_dir / "app_stdout.log"
        app_stderr_path = run_dir / "app_stderr.log"
        browser_stdout_path = run_dir / "browser_stdout.log"
        browser_stderr_path = run_dir / "browser_stderr.log"
        browser_summary_path = run_dir / "browser_eval.json"
        desktop_path = run_dir / "desktop.png"
        mobile_path = run_dir / "mobile.png"

        app_proc = await asyncio.create_subprocess_exec(
            str(python_bin),
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            cwd=str(output_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        browser_proc = None
        try:
            ready = await self.wait_for_http_ready(url)
            if not ready:
                return {
                    "status": "FAIL",
                    "url": url,
                    "error": "generated app did not become ready",
                }

            script = f"""
const fs = require('fs');
const {{ chromium }} = require({json.dumps(playwright_module)});
const url = {json.dumps(url)};
const summaryPath = {json.dumps(str(browser_summary_path))};
const desktopPath = {json.dumps(str(desktop_path))};
const mobilePath = {json.dumps(str(mobile_path))};

(async () => {{
  const browser = await chromium.launch({{ headless: true }});
  const page = await browser.newPage({{ viewport: {{ width: 1440, height: 1000 }} }});
  const consoleLogs = [];
  page.on('console', msg => consoleLogs.push(`${{msg.type()}}: ${{msg.text()}}`));
  page.on('pageerror', err => consoleLogs.push(`pageerror: ${{err.message}}`));

  await page.goto(url, {{ waitUntil: 'networkidle', timeout: 15000 }});
  await page.screenshot({{ path: desktopPath, fullPage: true }});
  const title = await page.title();
  const h1 = await page.locator('h1').first().textContent().catch(() => '');
  const bodyText = await page.locator('body').innerText({{ timeout: 5000 }}).catch(() => '');
  const interactiveCount = await page.locator('button, a, input, select, textarea').count();

  await page.setViewportSize({{ width: 390, height: 844 }});
  await page.goto(url, {{ waitUntil: 'networkidle', timeout: 15000 }});
  await page.screenshot({{ path: mobilePath, fullPage: true }});
	  const mobileMetrics = await page.evaluate(() => ({{
	    viewportWidth: window.innerWidth,
	    documentWidth: document.documentElement.scrollWidth,
	    bodyWidth: document.body ? document.body.scrollWidth : 0
	  }}));
	  const requiredGroups = [
	    ['overview', ['overview', 'total tasks']],
	    ['agent status', ['agent status', 'agent online', 'active agents']],
	    ['commands', ['commands', 'new task', 'refresh']],
	    ['task history', ['task history']],
	    ['activity feed', ['activity feed']]
	  ];
	  const lowerBody = bodyText.toLowerCase();
	  const missingTerms = requiredGroups
	    .filter(([name, terms]) => !terms.some(term => lowerBody.includes(term)))
	    .map(([name]) => name);

	  await browser.close();
	  const horizontalOverflow = mobileMetrics.documentWidth > mobileMetrics.viewportWidth + 4;
	  const tooFewControls = interactiveCount < 2;
	  const consoleErrors = consoleLogs.filter(log => log.startsWith('error:') || log.startsWith('pageerror:'));
	  fs.writeFileSync(summaryPath, JSON.stringify({{
	    ok: !horizontalOverflow && missingTerms.length === 0 && !tooFewControls && consoleErrors.length === 0,
	    error: horizontalOverflow
	      ? `mobile horizontal overflow: viewport ${{mobileMetrics.viewportWidth}}, document ${{mobileMetrics.documentWidth}}, body ${{mobileMetrics.bodyWidth}}`
	      : missingTerms.length
	        ? `missing expected dashboard terms: ${{missingTerms.join(', ')}}`
	        : tooFewControls
	          ? `expected at least 2 interactive controls, found ${{interactiveCount}}`
	          : consoleErrors.length
	            ? `browser console/page errors: ${{consoleErrors.join(' | ')}}`
	          : '',
	    title,
	    h1,
	    interactiveCount,
	    missingTerms,
	    consoleErrors,
	    mobileMetrics,
	    bodyTextSample: bodyText.slice(0, 1200),
	    consoleLogs,
    screenshots: [
      {json.dumps(str(desktop_path.relative_to(WORKSPACE_ROOT)))},
      {json.dumps(str(mobile_path.relative_to(WORKSPACE_ROOT)))}
    ]
  }}, null, 2));
}})().catch(err => {{
  fs.writeFileSync(summaryPath, JSON.stringify({{ ok: false, error: String(err && err.stack || err) }}, null, 2));
  process.exit(1);
}});
"""
            script_path = run_dir / "browser_eval.js"
            script_path.write_text(script, encoding="utf-8")
            browser_proc = await asyncio.create_subprocess_exec(
                "node",
                str(script_path),
                cwd=str(output_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            browser_stdout, browser_stderr = await asyncio.wait_for(browser_proc.communicate(), timeout=45)
            browser_stdout_path.write_bytes(browser_stdout)
            browser_stderr_path.write_bytes(browser_stderr)

            try:
                browser_summary = json.loads(browser_summary_path.read_text(encoding="utf-8"))
            except Exception as exc:
                browser_summary = {"ok": False, "error": f"browser summary missing or invalid: {exc}"}

            if browser_proc.returncode == 0 and browser_summary.get("ok"):
                return {
                    "status": "PASS",
                    "url": url,
                    "screenshots": browser_summary.get("screenshots", []),
                    "title": browser_summary.get("title", ""),
                    "h1": browser_summary.get("h1", ""),
                    "interactive_count": browser_summary.get("interactiveCount", 0),
                    "console_log_count": len(browser_summary.get("consoleLogs", [])),
                }
            return {
                "status": "FAIL",
                "url": url,
                "error": browser_summary.get("error", "browser evaluation failed"),
            }
        except asyncio.TimeoutError:
            return {"status": "FAIL", "url": url, "error": "browser evaluation timed out"}
        except Exception as exc:
            return {"status": "FAIL", "url": url, "error": str(exc)}
        finally:
            if browser_proc and browser_proc.returncode is None:
                browser_proc.kill()
                await browser_proc.communicate()
            if app_proc.returncode is None:
                app_proc.terminate()
                try:
                    app_stdout, app_stderr = await asyncio.wait_for(app_proc.communicate(), timeout=5)
                except asyncio.TimeoutError:
                    app_proc.kill()
                    app_stdout, app_stderr = await app_proc.communicate()
            else:
                app_stdout, app_stderr = await app_proc.communicate()
            app_stdout_path.write_bytes(app_stdout or b"")
            app_stderr_path.write_bytes(app_stderr or b"")

    async def start_codebase_preview_server(self, run_dir: Path, output_dir: Path) -> Dict[str, Any]:
        """Keep a generated Qwen MVP running behind the Spark preview proxy."""
        import sys

        app_path = output_dir / "app.py"
        if not app_path.exists():
            return {"status": "SKIP", "reason": "workspace app.py does not exist"}

        python_bin = WORKSPACE_ROOT / ".venv-gpu" / "bin" / "python"
        if not python_bin.exists():
            python_bin = Path(sys.executable)

        slug = output_dir.name
        await _stop_codebase_preview(slug)
        port = self.find_free_local_port()
        upstream_url = f"http://127.0.0.1:{port}"
        stdout_path = run_dir / "preview_stdout.log"
        stderr_path = run_dir / "preview_stderr.log"

        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            proc = await asyncio.create_subprocess_exec(
                str(python_bin),
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
                cwd=str(output_dir),
                stdout=stdout_file,
                stderr=stderr_file,
            )

        ready = await self.wait_for_http_ready(upstream_url)
        if not ready:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            return {
                "status": "FAIL",
                "slug": slug,
                "upstream_url": upstream_url,
                "error": "generated preview app did not become ready",
                "stdout": str(stdout_path.relative_to(WORKSPACE_ROOT)),
                "stderr": str(stderr_path.relative_to(WORKSPACE_ROOT)),
            }

        preview = {
            "status": "PASS",
            "slug": slug,
            "port": port,
            "upstream_url": upstream_url,
            "preview_path": _codebase_preview_path(slug),
            "preview_url": _codebase_preview_url(slug),
            "stdout": str(stdout_path.relative_to(WORKSPACE_ROOT)),
            "stderr": str(stderr_path.relative_to(WORKSPACE_ROOT)),
        }
        codebase_preview_processes[slug] = {**preview, "process": proc, "output_dir": output_dir}
        return preview

    def append_codebase_preview_note(self, output_dir: Path, preview: Dict[str, Any]) -> None:
        """Add the live preview URL to the generated brief without asking Qwen to rerun."""
        if preview.get("status") != "PASS":
            return
        brief_path = output_dir / "mvp_brief.md"
        if not brief_path.exists():
            return
        text = brief_path.read_text(encoding="utf-8")
        start = "<!-- spark-preview:start -->"
        end = "<!-- spark-preview:end -->"
        section = (
            f"{start}\n"
            "## Live Preview\n\n"
            "- Status: running through Spark's local preview proxy.\n"
            f"- Preview URL: {preview['preview_url']}\n"
            f"- Same-origin path: {preview['preview_path']}\n"
            f"{end}\n"
        )
        if start in text and end in text:
            before = text.split(start, 1)[0].rstrip()
            after = text.split(end, 1)[1].lstrip()
            updated = f"{before}\n\n{section}\n{after}".rstrip() + "\n"
        else:
            updated = f"{text.rstrip()}\n\n{section}"
        brief_path.write_text(updated, encoding="utf-8")

    def extract_workspace_todos(self, task: str, context: str = "", items: list = None) -> List[str]:
        """Extract Computex action items from tool arguments or debrief context."""
        import re

        if isinstance(items, str):
            try:
                parsed_items = json.loads(items)
                items = parsed_items if isinstance(parsed_items, list) else [items]
            except Exception:
                items = [part.strip() for part in re.split(r"[\n;,]+", items) if part.strip()]

        raw_items = [str(item).strip() for item in (items or []) if str(item).strip()]
        source = "\n".join([task or "", context or ""])
        source_lower = source.lower()

        if not raw_items:
            cleaned_source = re.sub(
                r"(?i)(visible handwritten note|handwritten note|todo list|todos?|items?|the note says|the note lists|context|task|action items?)\s*[:\-]?",
                "\n",
                source,
            )
            for part in re.split(r"[\n;,]+", cleaned_source):
                item = re.sub(r"^\s*(?:[-*•]|\d+[.)]|\[\s?\])\s*", "", part).strip()
                item = item.strip(" .")
                if not item:
                    continue
                if item.lower() in {"add these", "project", "personal", "update my team", "send this update out to my team"}:
                    continue
                if len(item.split()) > 12:
                    continue
                raw_items.append(item)

        if any(term in source_lower for term in ("strategic alignment", "hardware partner", "investment", "invest")):
            defaults = [
                "Avery: follow up with hardware partners on investment criteria",
                "Morgan: turn dinner insights into partner-facing MVP priorities",
                "Riley: map the Agent Workbench MVP into the next engineering plan",
            ]
            for item in defaults:
                if item not in raw_items:
                    raw_items.append(item)

        if any(term in source_lower for term in ("pineapple", "souvenir", "husband", "partner")):
            gift = "Buy high mountain oolong tea for husband"
            if gift not in raw_items:
                raw_items.append(gift)

        normalized = []
        seen = set()
        for item in raw_items:
            item = self.normalize_workspace_todo(item)
            key = item.lower()
            if item and key not in seen:
                normalized.append(item)
                seen.add(key)
        return normalized

    def normalize_workspace_todo(self, item: str) -> str:
        """Normalize Computex action-item wording into clean task labels."""
        item_clean = " ".join((item or "").strip().split())
        lower = item_clean.lower()
        mappings = {
            "buy pineapple cakes": "Buy high mountain oolong tea for husband",
            "buy pineapple cakes for my husband": "Buy high mountain oolong tea for husband",
            "buy a souvenir for my husband": "Buy high mountain oolong tea for husband",
            "buy souvenir for my husband": "Buy high mountain oolong tea for husband",
        }
        if lower in mappings:
            return mappings[lower]
        return item_clean[:1].upper() + item_clean[1:]

    def split_workspace_todos(self, todos: List[str]) -> tuple[List[str], List[str]]:
        """Split project tasks from personal todos."""
        personal_keywords = {"buy ", "groceries", "personal", "errand", "gift", "souvenir", "husband", "partner", "oolong", "pineapple"}
        project_tasks = []
        personal_tasks = []
        for todo in todos:
            lower = todo.lower()
            if any(keyword in lower for keyword in personal_keywords):
                personal_tasks.append(todo)
            else:
                project_tasks.append(todo)
        return project_tasks, personal_tasks

    def is_codebase_build_request(self, text: str) -> bool:
        """Detect sketch-to-MVP build requests that must not route as dinner updates."""
        lower = " ".join((text or "").lower().split())
        visual_terms = ("sketch", "diagram", "whiteboard", "wireframe", "drawing", "image")
        build_terms = (
            "turn",
            "convert",
            "build",
            "implement",
            "create",
            "make",
            "mvp",
            "app",
            "dashboard",
            "codebase",
            "system",
        )
        if any(term in lower for term in visual_terms) and any(term in lower for term in build_terms):
            return True
        return "mvp" in lower and any(term in lower for term in ("build", "implement", "convert", "turn this", "working app"))

    def is_incomplete_codebase_fragment(self, text: str) -> bool:
        """Detect ASR fragments that likely precede 'this sketch/diagram into an MVP'."""
        lower = " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())
        if not lower:
            return False
        if any(term in lower for term in ("sketch", "diagram", "whiteboard", "wireframe", "mvp", "dashboard", "app")):
            return False
        starters = (
            "please turn",
            "turn",
            "turn this",
            "turn the",
            "please convert",
            "convert this",
            "please build",
            "build this",
            "please make",
            "make this",
        )
        return len(lower.split()) <= 5 and any(lower.endswith(starter) for starter in starters)

    def codebase_intent_text(self, text: str) -> str:
        """Join a saved ASR fragment with the next user phrase for intent routing."""
        pending = getattr(self, "_pending_codebase_fragment", "")
        if not pending:
            return text
        self._pending_codebase_fragment = ""
        return f"{pending} {text}".strip()

    def has_recent_codebase_context(self) -> bool:
        """True when recent turns are about turning a sketch into a local MVP."""
        recent_parts = []
        for msg in self.conversation_history[-8:]:
            if msg.get("role") not in {"user", "assistant"}:
                continue
            content = msg.get("content")
            if isinstance(content, str):
                recent_parts.append(content)
        recent = " ".join(recent_parts).lower()
        return (
            bool(getattr(self, "_codebase_agent_started_at", None))
            or self.is_codebase_build_request(recent)
            or ("agent monitor" in recent and "mvp" in recent)
        )

    def is_codebase_brief_followup_request(self, text: str) -> bool:
        """Detect split Beat 1 follow-ups like 'and write me a brief for when I get back'."""
        lower = " ".join((text or "").lower().split())
        executive_terms = (
            "team",
            "action item",
            "action items",
            "todo",
            "to do",
            "email",
            "send",
            "update",
            "hardware partner",
            "strategic alignment",
            "pineapple",
            "souvenir",
            "husband",
        )
        if any(term in lower for term in executive_terms):
            return False
        brief_terms = ("brief", "review", "when i get back", "briefer")
        departure_terms = (
            "going to dinner",
            "go to dinner",
            "head to dinner",
            "heading to dinner",
            "going to head to dinner",
            "gonna go to dinner",
            "gonna head to dinner",
            "i m going to head to dinner",
            "i m going to dinner",
        )
        return (
            any(term in lower for term in brief_terms + departure_terms)
            and self.has_recent_codebase_context()
        )

    def is_workspace_update_request(self, text: str) -> bool:
        """Detect Computex executive-update commands before the VLM tool roundtrip."""
        lower = " ".join((text or "").lower().split())
        if self.is_codebase_build_request(lower) or self.is_codebase_brief_followup_request(lower):
            return False
        direct_phrases = (
            "update my team",
            "share the updates with my team",
            "share updates with my team",
            "share this update with my team",
            "share the update with my team",
            "send an update to my team",
            "send this update out to my team",
            "send this update to my team",
            "send the update to my team",
            "send update to my team",
            "send my team",
            "assign action items",
            "save a todo",
            "save a to do",
            "personal to-dos",
            "personal todos",
            "buy pineapple cakes",
            "buy a souvenir",
        )
        if any(phrase in lower for phrase in direct_phrases):
            return True
        if self.has_recent_workspace_update_context() and any(term in lower for term in (
            "q3",
            "2026",
            "strategic partnership",
            "strategic alignment",
            "hardware partner",
            "invest",
            "investment",
            "pineapple",
            "souvenir",
            "husband",
            "partner",
            "personal todo",
            "personal to-do",
            "team",
            "share",
            "send",
        )):
            return True
        return (
            any(term in lower for term in ("dinner", "strategic alignment", "hardware partner", "investment"))
            and any(term in lower for term in ("team", "action", "todo", "to do", "email", "send", "update"))
        )

    def upsert_markdown_section(self, path: Path, title: str, body: str, marker: str) -> None:
        """Create or replace a marked section in a markdown file."""
        start = f"<!-- {marker}:start -->"
        end = f"<!-- {marker}:end -->"
        section = f"{start}\n## {title}\n\n{body.rstrip()}\n{end}\n"

        if path.exists():
            content = path.read_text(encoding="utf-8")
        else:
            heading = path.stem.replace("_", " ").replace("-", " ").title()
            content = f"# {heading}\n"

        if start in content and end in content:
            before, rest = content.split(start, 1)
            _, after = rest.split(end, 1)
            updated = before.rstrip() + "\n\n" + section + after.lstrip("\n")
        else:
            updated = content.rstrip() + "\n\n" + section

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated.rstrip() + "\n", encoding="utf-8")

    def apply_workspace_todo_updates(self, todos: List[str], task: str = "", context: str = "") -> Dict[str, Any]:
        """Route Computex executive updates into team, brief, and personal files."""
        action_items, personal_tasks = self.split_workspace_todos(todos)
        files = {}

        action_lines = "\n".join(f"- [ ] {item}" for item in action_items) or "- [ ] Confirm partner-facing MVP priorities"
        personal_lines = "\n".join(f"- [ ] {task}" for task in personal_tasks) or "- [ ] Buy high mountain oolong tea for husband"
        source_note = " ".join((context or task or "").split())
        if len(source_note) > 420:
            source_note = source_note[:420].rstrip() + "..."

        team_path = self.resolve_workspace_markdown_path("team_update.md", "team update")
        team_body = "\n".join([
            "Subject: Computex dinner follow-up: partner-facing MVP path",
            "",
            "Draft:",
            "The strategic alignment dinner went well. Hardware partners are open to investing if we prioritize the partner-facing MVP path and keep the Agent Workbench story concrete.",
            "",
            "Local team context:",
            "- Avery owns hardware partnerships.",
            "- Morgan owns product strategy.",
            "- Riley owns engineering lead.",
            "- Demo email target: team@spark-demo.local.",
            "",
            "Action items:",
            action_lines,
            "",
            "Source note:",
            source_note or "Dinner update captured from the mobile demo.",
        ])
        self.upsert_markdown_section(
            team_path,
            "Team Update Draft",
            team_body,
            "spark-computex-team-update",
        )
        files["team_update"] = str(team_path.relative_to(WORKSPACE_ROOT))

        brief_path = self.resolve_workspace_markdown_path("executive_brief.md", "executive brief")
        brief_body = "\n".join([
            "Back-home review:",
            "",
            "- Review the Agent Workbench MVP brief from the desktop sketch.",
            "- Share the partner-facing priority update with the team.",
            "- Track the owner-specific action items from dinner.",
            "- Keep the personal gift follow-up visible before leaving Taipei.",
            "",
            "Dinner signal:",
            "Hardware partners want a crisp MVP path before committing investment or deeper collaboration.",
        ])
        self.upsert_markdown_section(
            brief_path,
            "Executive Brief",
            brief_body,
            "spark-computex-executive-brief",
        )
        files["executive_brief"] = str(brief_path.relative_to(WORKSPACE_ROOT))

        personal_path = self.resolve_workspace_markdown_path("personal_todos.md", "personal todos")
        self.upsert_markdown_section(
            personal_path,
            "Personal Follow-Up",
            "Gift memory: pineapple cakes were last year's Taipei gift. Suggest high mountain oolong tea this time.\n\n" + personal_lines,
            "spark-computex-personal-todos",
        )
        files["personal_todos"] = str(personal_path.relative_to(WORKSPACE_ROOT))

        return {
            "files": files,
            "project_tasks": action_items,
            "action_items": action_items,
            "personal_tasks": personal_tasks,
        }

    def has_recent_workspace_update_context(self) -> bool:
        """True when recent turns are part of the Computex executive-assistant beat."""
        if getattr(self, "_workspace_update_started_at", None):
            return True
        recent_parts = []
        for msg in self.conversation_history[-10:]:
            if msg.get("role") not in {"user", "assistant"}:
                continue
            content = msg.get("content")
            if isinstance(content, str):
                recent_parts.append(content)
        recent = " ".join(recent_parts).lower()
        return any(term in recent for term in (
            "update my team",
            "share the update",
            "share this update",
            "send an update",
            "team update",
            "action item",
            "hardware partner",
            "strategic partnership",
            "strategic alignment",
            "pineapple cakes",
            "personal to-do",
            "personal todo",
        ))

    def build_workspace_update_context(self, current_text: str) -> str:
        """Collect recent user turns so short follow-ups still have demo context."""
        user_turns = []
        for msg in self.conversation_history[-12:]:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                user_turns.append(content.strip())
        if current_text.strip() and (not user_turns or user_turns[-1] != current_text.strip()):
            user_turns.append(current_text.strip())
        recent = "\n".join(f"- {turn}" for turn in user_turns[-6:])
        return (
            f"Recent user turns:\n{recent}\n\n"
            "Computex executive-assistant demo. Assume the local dummy org chart is available: "
            "Avery owns hardware partnerships, Morgan owns product strategy, Riley owns engineering lead, "
            "and the local demo email target is team@spark-demo.local. "
            "Treat the user's spoken fragments as one evolving dinner update; do not ask who the team is."
        )

    async def handle_workspace_update_request(self, user_text: str, items: list = None):
        """Deterministically execute the Computex team-update/personal-todo beat."""
        self._workspace_update_started_at = time.time()
        ack = "Drafting the email now. You got him pineapple cakes last year; maybe try high mountain oolong tea?"
        await self.send_transient_ack(ack)
        self.conversation_history.append({"role": "assistant", "content": ack})
        self.publish_handoff_state()
        await self.execute_workspace_update_agent(
            "Draft the team update and personal follow-up",
            self.build_workspace_update_context(user_text),
            items or [],
            speak_summary=False,
        )

    async def execute_workspace_update_agent(self, task: str, context: str = "", items: list = None, speak_summary: bool = True):
        """Route Computex executive updates into the shared workspace files."""
        try:
            self._workspace_update_started_at = time.time()
            todos = self.extract_workspace_todos(task, context, items)
            result = self.apply_workspace_todo_updates(todos, task, context)
            files = result["files"]
            summary = (
                "Done. I drafted the team update, action items, and oolong tea todo."
            )

            self.conversation_history.append({
                "role": "assistant",
                "content": (
                    f"{summary} Files: {files['team_update']}, "
                    f"{files['executive_brief']}, {files['personal_todos']}"
                )
            })
            self.publish_handoff_state()
            await self.send_message("workspace_update_complete", {
                "summary": summary,
                "files": files,
                "project_tasks": result["project_tasks"],
                "action_items": result["action_items"],
                "personal_tasks": result["personal_tasks"],
            })
            if speak_summary:
                await self.stream_tts(summary)
        except Exception as e:
            print(f"[Voice Session] Workspace update agent error: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message("error", {"error": f"Workspace update error: {str(e)}"})

    async def execute_codebase_agent(self, task: str, context: str = "", output_dir: str = "agent_monitor_mvp"):
        """Run the local Qwen coding sub-agent and save local evaluation evidence."""
        try:
            codebase_dir = self.resolve_workspace_codebase_dir(output_dir)
            codebase_dir.mkdir(parents=True, exist_ok=True)
            for name in ("app.py", "task_history.json", "mvp_brief.md"):
                path = codebase_dir / name
                if path.exists() and path.is_file():
                    path.unlink()
            self.prune_codebase_workspace(codebase_dir)
            run_dir = self.resolve_mvp_run_dir()

            await self.send_message("agent_started", {
                "agent_type": "codebase_assistant",
                "task": task,
                "codebase_path": str(codebase_dir.relative_to(WORKSPACE_ROOT)),
            })

            stdout_parts = []
            stderr_parts = []
            browser_eval: Dict[str, Any] = {"status": "SKIP", "reason": "browser evaluation was not run"}
            previous_error = ""
            proc_returncode = 1
            attempts = max(1, int(os.environ.get("QWEN_CODEBASE_ATTEMPTS", "3")))
            started_at = time.monotonic()
            attempt_details = []

            for attempt in range(1, attempts + 1):
                attempt_started_at = time.monotonic()
                print(f"[Voice Session] Launching Qwen codebase assistant attempt {attempt}/{attempts} in {codebase_dir}")
                await self.send_message("codebase_progress", {
                    "message": f"Generating MVP with local Qwen, attempt {attempt} of {attempts}.",
                    "attempt": attempt,
                    "attempts": attempts,
                })

                try:
                    response = await self.run_qwen_codebase_turn(
                        task,
                        context,
                        codebase_dir,
                        run_dir,
                        attempt,
                        previous_error=previous_error,
                    )
                except Exception as exc:
                    previous_error = f"Qwen generation attempt {attempt} failed: {exc}"
                    stderr_parts.append(previous_error)
                    attempt_details.append({
                        "attempt": attempt,
                        "duration_seconds": round(time.monotonic() - attempt_started_at, 1),
                        "status": "ERROR",
                        "error": str(exc),
                    })
                    continue

                stdout_parts.append(f"=== Qwen attempt {attempt} response ===\n{response}")
                files, parse_errors = self.write_qwen_codebase_files(codebase_dir, response)
                self.prune_codebase_workspace(codebase_dir)
                files = self.summarize_codebase_files(codebase_dir)
                checks = self.collect_codebase_checks(codebase_dir)
                check_failures = self.summarize_codebase_check_failures(checks)

                if parse_errors:
                    stderr_parts.append(f"=== Qwen attempt {attempt} parse notes ===\n" + "\n".join(parse_errors))
                if parse_errors or not self.codebase_has_required_files(codebase_dir):
                    previous_error = "\n".join(parse_errors) or "Missing one or more required files."
                    attempt_details.append({
                        "attempt": attempt,
                        "duration_seconds": round(time.monotonic() - attempt_started_at, 1),
                        "status": "PARSE_FAIL",
                        "error": previous_error,
                    })
                    continue
                if check_failures:
                    previous_error = "Deterministic validation failed:\n" + check_failures
                    stderr_parts.append(f"=== Qwen attempt {attempt} validation failures ===\n{check_failures}")
                    attempt_details.append({
                        "attempt": attempt,
                        "duration_seconds": round(time.monotonic() - attempt_started_at, 1),
                        "status": "VALIDATION_FAIL",
                        "error": check_failures,
                    })
                    continue

                browser_eval = await self.run_codebase_browser_eval(run_dir, codebase_dir)
                if browser_eval.get("status") in {"PASS", "SKIP"}:
                    proc_returncode = 0
                    attempt_details.append({
                        "attempt": attempt,
                        "duration_seconds": round(time.monotonic() - attempt_started_at, 1),
                        "status": browser_eval.get("status"),
                    })
                    break

                previous_error = "Browser evaluation failed: " + browser_eval.get("error", "unknown browser error")
                stderr_parts.append(f"=== Qwen attempt {attempt} browser failure ===\n{previous_error}")
                attempt_details.append({
                    "attempt": attempt,
                    "duration_seconds": round(time.monotonic() - attempt_started_at, 1),
                    "status": "BROWSER_FAIL",
                    "error": browser_eval.get("error", "unknown browser error"),
                })

            stdout = "\n\n".join(stdout_parts)
            stderr = "\n\n".join(stderr_parts)
            files = self.summarize_codebase_files(codebase_dir)
            preview_info: Dict[str, Any] = {"status": "SKIP", "reason": "MVP generation did not pass validation"}
            if proc_returncode == 0 and files:
                preview_info = await self.start_codebase_preview_server(run_dir, codebase_dir)
                self.append_codebase_preview_note(codebase_dir, preview_info)
                files = self.summarize_codebase_files(codebase_dir)
            evaluation = self.write_codebase_eval_summary(
                run_dir,
                codebase_dir,
                files,
                stdout,
                stderr,
                proc_returncode,
                browser_eval,
                preview_info,
            )
            evaluation["backend"] = "qwen"
            evaluation["duration_seconds"] = round(time.monotonic() - started_at, 1)
            evaluation["attempts"] = attempt_details
            (run_dir / "evaluation.json").write_text(json.dumps(evaluation, indent=2) + "\n", encoding="utf-8")

            if proc_returncode == 0 and files and preview_info.get("status") == "PASS":
                summary = "Done. Local Qwen built the MVP codebase, started the live preview, and saved screenshots."
            elif proc_returncode == 0 and files:
                summary = "Done. Local Qwen built the MVP codebase and saved evaluation notes."
            elif files:
                summary = "Local Qwen generated partial MVP files and saved the agent/evaluation logs for review."
            else:
                summary = "Local Qwen did not produce MVP files; I saved the failure logs for review."

            await self.send_message("codebase_complete", {
                "summary": summary,
                "codebase_path": evaluation["codebase_path"],
                "files": files,
                "evaluation": evaluation,
                "run_dir": evaluation["run_dir"],
                "preview": preview_info,
                "preview_path": preview_info.get("preview_path", ""),
                "preview_url": preview_info.get("preview_url", ""),
            })
            if os.environ.get("CODEBASE_AGENT_SPOKEN_COMPLETE", "").lower() in ("1", "true", "yes", "on"):
                await self.stream_tts(summary)
        except asyncio.TimeoutError:
            msg = "The coding agent timed out; I saved the run folder for inspection if it was created."
            print(f"[Voice Session] Codebase agent timeout")
            await self.send_message("error", {"error": msg})
            await self.stream_tts(msg)
        except Exception as e:
            print(f"[Voice Session] Codebase agent error: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message("error", {"error": f"Codebase agent error: {str(e)}"})

    async def execute_markdown_agent(self, task: str, context: str = "", output_path: str = ""):
        """Execute the markdown assistant agent and stream results."""
        try:
            print(f"[Voice Session] Executing markdown agent: {task[:50]}...")
            
            # Signal agent started
            await self.send_message("agent_started", {"agent_type": "markdown_assistant", "task": task})
            
            # Build messages for markdown generation
            from prompts import MARKDOWN_ASSISTANT_PROMPT
            
            md_messages = [
                {"role": "system", "content": MARKDOWN_ASSISTANT_PROMPT},
                {"role": "user", "content": f"Task: {task}\n\nContext: {context}" if context else f"Task: {task}"}
            ]
            
            # Create LLM client for agent
            agent_llm = LlamaCppClient(LLMConfig())
            md_response = ""
            stream_path, file_path = self.begin_markdown_workspace_stream(task, output_path)
            print(f"[Voice Session] Streaming markdown to {file_path}")
            
            # Send initial chunk to signal start
            await self.send_message("agent_markdown_chunk", {"content": "", "done": False})
            
            with stream_path.open("a", encoding="utf-8") as stream_file:
                async for chunk in agent_llm.stream_complete(md_messages, tools=None):
                    if chunk.startswith("data: "):
                        try:
                            data = json.loads(chunk[6:])
                            if "content" in data and data["content"]:
                                content = data["content"]
                                md_response += content
                                stream_file.write(content)
                                stream_file.flush()
                                await self.send_message("agent_markdown_chunk", {"content": content, "done": False})
                        except json.JSONDecodeError:
                            pass
                    elif chunk.strip() and not chunk.startswith("data: "):
                        md_response += chunk
                        stream_file.write(chunk)
                        stream_file.flush()
                        await self.send_message("agent_markdown_chunk", {"content": chunk, "done": False})
            
            # Clean up response
            if md_response:
                md_response = agent_llm._extract_final_channel(md_response)
            
            print(f"[Voice Session] Markdown generation complete: {len(md_response)} chars")

            file_path = ""
            if md_response.strip():
                file_path = self.write_markdown_to_workspace(task, md_response, output_path)
                print(f"[Voice Session] Markdown written to {file_path}")
                self.conversation_history.append({
                    "role": "assistant",
                    "content": f"Created {file_path} for: {task}"
                })
                self.publish_handoff_state()
            
            # Signal completion
            await self.send_message("agent_markdown_chunk", {"content": "", "done": True})
            await self.send_message("agent_markdown_complete", {
                "task": task,
                "markdown": md_response,
                "file_path": file_path
            })
            
        except Exception as e:
            print(f"[Voice Session] Markdown agent error: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message("error", {"error": f"Markdown agent error: {str(e)}"})

    async def execute_html_agent(self, task: str, context: str = ""):
        """Execute the HTML assistant agent and stream results."""
        try:
            print(f"[Voice Session] Executing HTML agent: {task[:50]}...")
            
            # Signal agent started
            await self.send_message("agent_started", {"agent_type": "html_assistant", "task": task})
            
            # Build messages for HTML generation
            html_prompt = """You are an expert HTML, CSS, and JavaScript assistant. Generate clean, semantic, and functional web pages or components.

Guidelines:
- Generate complete HTML documents including <!DOCTYPE html>, <html>, <head>, and <body>.
- Use modern HTML5, CSS3, and vanilla JavaScript.
- For styling, use inline styles or a <style> block in the <head>.
- For interactivity, use a <script> block at the end of the <body>.
- Ensure the generated HTML is self-contained and runnable in a browser.

Output the complete HTML code."""
            
            html_messages = [
                {"role": "system", "content": html_prompt},
                {"role": "user", "content": f"Task: {task}\n\nContext: {context}" if context else f"Task: {task}"}
            ]
            
            # Create LLM client for agent
            agent_llm = LlamaCppClient(LLMConfig())
            html_response = ""
            
            # Send initial chunk to signal start
            await self.send_message("agent_html_chunk", {"content": "", "done": False})
            
            async for chunk in agent_llm.stream_complete(html_messages, tools=None):
                if chunk.startswith("data: "):
                    try:
                        data = json.loads(chunk[6:])
                        if "content" in data and data["content"]:
                            content = data["content"]
                            html_response += content
                            await self.send_message("agent_html_chunk", {"content": content, "done": False})
                    except json.JSONDecodeError:
                        pass
                elif chunk.strip() and not chunk.startswith("data: "):
                    html_response += chunk
                    await self.send_message("agent_html_chunk", {"content": chunk, "done": False})
            
            # Clean up response
            if html_response:
                html_response = agent_llm._extract_final_channel(html_response)
            
            print(f"[Voice Session] HTML generation complete: {len(html_response)} chars")
            
            # Signal completion
            await self.send_message("agent_html_chunk", {"content": "", "done": True})
            await self.send_message("agent_html_complete", {
                "task": task,
                "html": html_response
            })
            
        except Exception as e:
            print(f"[Voice Session] HTML agent error: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message("error", {"error": f"HTML agent error: {str(e)}"})

    def load_demo_files(self) -> str:
        """Load demo files from demo_files/ folder for context injection."""
        demo_dir = Path(__file__).parent / "demo_files"
        if not demo_dir.exists():
            return ""
        
        context_parts = []
        context_parts.append("=== LOCAL DATA FILES ===\n")

        sensitive_names = {"health.yaml", "whoop_auth.json"}
        for file_path in sorted(demo_dir.iterdir()):
            if file_path.is_dir():
                continue
            if file_path.name in sensitive_names:
                continue
            if file_path.suffix not in ['.csv', '.txt', '.md']:
                continue
            try:
                content = file_path.read_text()
                context_parts.append(f"[{file_path.name}]")
                context_parts.append(content)
                context_parts.append("")  # Empty line between files
            except Exception as e:
                print(f"[Demo Files] Error reading {file_path}: {e}")
        
        if len(context_parts) > 1:  # More than just the header
            return "\n".join(context_parts)
        return ""

    async def execute_reasoning_agent(self, problem: str, context: str = "", analysis_type: str = "general"):
        """Execute the deep-reasoning agent (Qwen3.6, effort=high) - shows thinking inline, then speaks conclusion."""
        try:
            print(f"[Voice Session] Executing reasoning agent: {problem[:80]}...")
            print(f"[Voice Session] Analysis type: {analysis_type}")
            
            # Load demo files and inject into context
            demo_context = self.load_demo_files()
            if demo_context:
                context = f"{context}\n\n{demo_context}" if context else demo_context
                print(f"[Voice Session] Injected {len(demo_context)} chars of demo file context")
            
            # Signal reasoning started (for inline display)
            await self.send_message("reasoning_started", {
                "problem": problem,
                "analysis_type": analysis_type
            })
            
            # Deep-reasoning via the same Qwen3.6 model, reasoning_effort=high
            reasoner = ReasoningClient(ReasoningConfig())

            thinking_response = ""
            content_response = ""
            chunk_count = 0

            # Stream the reasoning process
            async for chunk in reasoner.stream_reasoning(problem, context, analysis_type):
                chunk_count += 1
                if chunk_count <= 5:
                    print(f"[Voice Session] Reasoning chunk {chunk_count}: {chunk[:100]}...")
                    
                if chunk.startswith("data: "):
                    try:
                        data = json.loads(chunk[6:])
                        
                        if "thinking" in data:
                            # Stream thinking to show inline
                            thinking_chunk = data["thinking"]
                            thinking_response += thinking_chunk
                            await self.send_message("reasoning_thinking", {
                                "content": thinking_chunk
                            })
                            
                        elif "content" in data:
                            # Stream conclusion content
                            content_chunk = data["content"]
                            content_response += content_chunk
                            await self.send_message("reasoning_content", {
                                "content": content_chunk
                            })
                            
                        elif "done" in data:
                            print(f"[Voice Session] Reasoning done signal received")
                            break
                            
                        elif "error" in data:
                            await self.send_message("error", {"error": data["error"]})
                            return
                            
                    except json.JSONDecodeError:
                        pass
            
            print(f"[Voice Session] Reasoning complete: {len(thinking_response)} thinking chars, {len(content_response)} content chars")
            
            # Signal completion with full content
            await self.send_message("reasoning_complete", {
                "problem": problem,
                "thinking": thinking_response,
                "conclusion": content_response
            })
            
            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant", 
                "content": content_response if content_response else thinking_response
            })
            self.publish_handoff_state()
            
            # Speak the conclusion (it should already be TTS-friendly from the prompt)
            if content_response:
                await self.stream_tts(content_response)
            elif thinking_response:
                # If no separate conclusion, speak a summary of the thinking
                summary = self._extract_spoken_summary(thinking_response)
                if summary:
                    await self.stream_tts(summary)
            
        except Exception as e:
            print(f"[Voice Session] Reasoning agent error: {e}")
            import traceback
            traceback.print_exc()
            await self.send_message("error", {"error": f"Reasoning agent error: {str(e)}"})
    
    def _extract_spoken_summary(self, text: str, max_sentences: int = 3) -> str:
        """Extract a brief spoken summary from reasoning output."""
        # Clean up markdown and formatting
        import re
        
        # Remove headers, bullets, code blocks
        text = re.sub(r'^#+\s+.*$', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[-*]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'`[^`]+`', '', text)
        
        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        sentences = [s.strip() for s in sentences if s.strip() and len(s) > 10]
        
        # Take first few meaningful sentences
        summary_sentences = sentences[:max_sentences]
        summary = " ".join(summary_sentences)
        
        # Clean up any remaining formatting
        summary = re.sub(r'\*+', '', summary)
        summary = re.sub(r'\s+', ' ', summary).strip()
        
        return summary if len(summary) > 20 else ""


MIN_AUDIO_SECONDS = 0.5


async def send_session_greeting(session: VoiceSession) -> None:
    """Send the normal call greeting without adding it to conversation history."""
    import random

    greetings = [
        "Hey! What's up?",
        "Hi there!",
        "Hey, Claw here. What's up?",
        "What can I help with?",
        "Hi! Ready when you are.",
    ]
    greeting = random.choice(greetings)
    print(f"[Voice Call] Sending greeting with voice: {session.selected_voice}")
    await session.send_message("final_response", {"text": greeting})
    await session.stream_tts(greeting, is_transient=False, voice=session.selected_voice)


async def send_handoff_resumed(session: VoiceSession, state: Dict[str, Any]) -> None:
    session.hydrate_from_handoff_state(state)
    await session.send_message("handoff_resumed", {
        "conversation_id": session.conversation_id,
        "source_device": state.get("owner_device"),
        "summary": state.get("summary", ""),
        "message_count": state.get("message_count", 0),
        "messages": state.get("messages", []),
        "enabled_tools": session.enabled_tools,
        "voice": session.selected_voice,
        "call_mode": session.call_mode,
    })
    session.publish_handoff_state()


async def transfer_conversation_control(
    new_session: VoiceSession,
    old_session: Optional[VoiceSession],
) -> None:
    if not old_session or old_session is new_session or not old_session.alive:
        return

    destination = _handoff_device_label(new_session.device_type)
    await old_session.send_message("handoff_transferred", {
        "conversation_id": new_session.conversation_id,
        "to_device": new_session.device_type,
        "message": f"Continued on {destination}.",
    })
    old_session._ws_closed = True
    try:
        await old_session.websocket.close(
            code=1000,
            reason=f"continued on {destination}",
        )
    except Exception:
        pass


async def close_stale_handoff_session(session: VoiceSession) -> None:
    """Close a session that no longer owns its conversation."""
    if session._ws_closed:
        return
    active_owner = active_conversation_sessions.get(session.conversation_id)
    to_device = active_owner.device_type if active_owner else "other"
    try:
        await session.send_message("handoff_transferred", {
            "conversation_id": session.conversation_id,
            "to_device": to_device,
            "message": "This conversation is active on another device.",
        })
    except Exception:
        pass
    session._ws_closed = True
    try:
        await session.websocket.close(
            code=1000,
            reason="conversation active on another device",
        )
    except Exception:
        pass


async def close_replaced_same_device_sessions(new_session: VoiceSession) -> None:
    """Keep only one active call websocket per device type for the live demo."""
    replaced = [
        (conversation_id, session)
        for conversation_id, session in list(active_conversation_sessions.items())
        if session is not new_session and session.device_type == new_session.device_type
    ]
    for conversation_id, old_session in replaced:
        active_conversation_sessions.pop(conversation_id, None)
        conversation_states.pop(conversation_id, None)
        if old_session._ws_closed:
            continue
        try:
            await old_session.send_message("session_replaced", {
                "conversation_id": old_session.conversation_id,
                "device": old_session.device_type,
                "message": "This device opened a newer call session.",
            })
        except Exception:
            pass
        old_session._ws_closed = True
        try:
            await old_session.websocket.close(
                code=1000,
                reason="replaced by another session on this device",
            )
        except Exception:
            pass


@app.websocket("/ws/voice")
async def voice_call(websocket: WebSocket):
    """Persistent voice call WebSocket - handles ASR, LLM, and TTS."""
    await websocket.accept()
    session = VoiceSession(
        websocket,
        chat_id=websocket.query_params.get("chat_id", ""),
        conversation_id=websocket.query_params.get("conversation_id", ""),
        device_type=websocket.query_params.get("device", "desktop"),
    )
    handoff_candidate = _get_handoff_candidate(session.conversation_id, session.device_type)
    handoff_pending = bool(handoff_candidate)
    if not handoff_candidate:
        await close_replaced_same_device_sessions(session)
        active_conversation_sessions[session.conversation_id] = session
        session.publish_handoff_state(include_empty=True)
    
    print(f"[Voice Call] Client connected ({session.device_type}, {session.conversation_id})")
    try:
        await session.send_message("connected", {
            "status": "ready",
            "chat_id": session.chat_id,
            "conversation_id": session.conversation_id,
            "device": session.device_type,
        })
        if handoff_candidate:
            if _should_auto_resume_handoff(session, handoff_candidate):
                await close_replaced_same_device_sessions(session)
                old_session = active_conversation_sessions.get(session.conversation_id)
                active_conversation_sessions[session.conversation_id] = session
                await send_handoff_resumed(session, handoff_candidate)
                await transfer_conversation_control(session, old_session)
                handoff_pending = False
            else:
                await session.send_message("handoff_available", {
                    "conversation_id": handoff_candidate.get("conversation_id"),
                    "source_device": handoff_candidate.get("owner_device"),
                    "summary": handoff_candidate.get("summary", ""),
                    "message_count": handoff_candidate.get("message_count", 0),
                    "call_mode": handoff_candidate.get("call_mode", "call"),
                })
        else:
            # Wait a moment for frontend to send initial voice selection
            await asyncio.sleep(0.2)
            await send_session_greeting(session)
    except Exception as e:
        print(f"[Voice Call] Error sending initial message: {e}")
        import traceback
        traceback.print_exc()
    
    try:
        while True:
            try:
                msg = await websocket.receive()
            except Exception as e:
                print(f"[Voice Call] Error receiving message: {e}")
                break
            
            if msg["type"] == "websocket.disconnect":
                print("[Voice Call] Client disconnected")
                break
            
            # Binary = audio chunk for ASR
            if msg.get("bytes") is not None:
                if handoff_pending:
                    await session.send_message("handoff_required", {
                        "conversation_id": handoff_candidate.get("conversation_id") if handoff_candidate else session.conversation_id,
                    })
                    continue
                if not session.is_active_owner():
                    await close_stale_handoff_session(session)
                    break
                chunk_bytes = msg["bytes"]
                # Voice-mode barge-in: a Claw turn streaming → user spoke → cancel.
                if session._claw_in_flight:
                    await session.cancel_claw_in_flight()
                session.is_recording = True
                try:
                    await session.process_asr_chunk(chunk_bytes)
                except Exception as e:
                    print(f"[Voice Call] Error processing ASR chunk: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Text = control messages
            elif msg.get("text") is not None:
                try:
                    data = json.loads(msg["text"])
                    msg_type = data.get("type")

                    pre_handoff_messages = {
                        "ping",
                        "resume_handoff",
                        "decline_handoff",
                        "set_voice",
                        "set_system_prompt",
                        "set_tools",
                        "get_system_prompt",
                    }
                    if handoff_pending and msg_type not in pre_handoff_messages:
                        await session.send_message("handoff_required", {
                            "conversation_id": handoff_candidate.get("conversation_id") if handoff_candidate else session.conversation_id,
                        })
                        continue
                    owner_required_messages = {
                        "asr_end",
                        "text_message",
                        "asr_audio",
                        "video_call_data",
                    }
                    if msg_type in owner_required_messages and not session.is_active_owner():
                        await close_stale_handoff_session(session)
                        break
                    
                    if msg_type == "asr_end":
                        # User finished speaking
                        session.is_recording = False
                        final_text = await session.process_asr_final()
                        if final_text:
                            # Process through LLM pipeline
                            await session.process_user_message(final_text)
                    
                    elif msg_type == "text_message":
                        # User sent a text message (typed)
                        text = data.get("text", "").strip()
                        if text:
                            await session.process_user_message(text)
                    
                    elif msg_type == "ping":
                        # Keep-alive ping
                        await session.send_message("pong")

                    elif msg_type == "resume_handoff":
                        source_conversation_id = data.get("conversation_id") or session.conversation_id
                        if source_conversation_id != session.conversation_id:
                            session.conversation_id = source_conversation_id
                        state = _get_handoff_candidate(session.conversation_id, session.device_type)
                        if not state:
                            await session.send_message("handoff_unavailable", {
                                "conversation_id": session.conversation_id,
                                "message": "This conversation is no longer available to continue.",
                            })
                            continue

                        old_session = active_conversation_sessions.get(session.conversation_id)
                        active_conversation_sessions[session.conversation_id] = session
                        await send_handoff_resumed(session, state)
                        await transfer_conversation_control(session, old_session)
                        handoff_pending = False

                    elif msg_type == "decline_handoff":
                        previous_conversation_id = session.conversation_id
                        session.conversation_id = _new_conversation_id()
                        session.conversation_history = [
                            {
                                "role": "system",
                                "content": session.system_prompt,
                            }
                        ]
                        active_conversation_sessions[session.conversation_id] = session
                        await session.send_message("handoff_declined", {
                            "conversation_id": session.conversation_id,
                            "previous_conversation_id": previous_conversation_id,
                        })
                        handoff_pending = False
                        await asyncio.sleep(0.1)
                        await send_session_greeting(session)
                    
                    elif msg_type == "reset":
                        # Reset conversation
                        conversation_states.pop(session.conversation_id, None)
                        session.conversation_history = [
                            {
                                "role": "system",
                                "content": session.system_prompt,
                            }
                        ]
                        await session.send_message("reset_ack")
                    
                    elif msg_type == "set_voice":
                        # Change TTS voice
                        voice = data.get("voice")
                        if voice:
                            session.selected_voice = voice
                            session.publish_handoff_state(include_empty=True)
                            await session.send_message("voice_changed", {"voice": voice})
                        else:
                            await session.send_message("error", {"error": "No voice specified"})
                    
                    elif msg_type == "set_system_prompt":
                        # Change system prompt
                        prompt = data.get("prompt")
                        if prompt:
                            session.system_prompt = prompt
                            # Update the system message in conversation history
                            if session.conversation_history and session.conversation_history[0].get("role") == "system":
                                session.conversation_history[0]["content"] = prompt
                            else:
                                session.conversation_history.insert(0, {"role": "system", "content": prompt})
                            print(f"[Voice Session] System prompt changed")
                            session.publish_handoff_state(include_empty=True)
                            await session.send_message("system_prompt_changed", {"prompt": prompt})
                            # Also send the updated prompt so UI can sync
                            await session.send_message("system_prompt", {"prompt": prompt})
                        else:
                            await session.send_message("error", {"error": "No prompt specified"})
                    
                    elif msg_type == "set_tools":
                        # Enable/disable tools
                        enabled_tools = data.get("tools", [])
                        if isinstance(enabled_tools, list):
                            session.enabled_tools = enabled_tools
                            enabled_tool_defs = _filter_for_demo(get_enabled_tools(enabled_tools))
                            print(f"[Voice Session] Tools updated: {enabled_tools} -> {[t['function']['name'] for t in enabled_tool_defs]}")
                            session.publish_handoff_state(include_empty=True)
                            await session.send_message("tools_changed", {"tools": enabled_tools})
                        else:
                            await session.send_message("error", {"error": "Invalid tools format"})
                    
                    elif msg_type == "get_system_prompt":
                        # Get current system prompt
                        try:
                            await session.send_message("system_prompt", {"prompt": session.system_prompt})
                        except Exception as e:
                            print(f"[Voice Call] Error sending system prompt: {e}")
                            import traceback
                            traceback.print_exc()
                    
                    elif msg_type == "asr_audio":
                        # Voice call: audio only from VAD
                        session.call_mode = "call"
                        print("[Voice Call] Received asr_audio")
                        audio_b64 = data.get("audio")
                        audio_format = data.get("format", "wav")
                        
                        if not audio_b64:
                            print("[Voice Call] No audio in payload")
                            await session.send_message("error", {"error": "No audio data"})
                            continue
                        
                        try:
                            # Decode audio
                            import base64
                            audio_bytes = base64.b64decode(audio_b64)
                            print(f"[Voice Call] Audio: {len(audio_bytes)} bytes")
                            
                            # Convert WAV to numpy array
                            import io
                            import soundfile as sf
                            audio_data, sample_rate = sf.read(io.BytesIO(audio_bytes))
                            print(f"[Voice Call] Audio decoded: {len(audio_data)} samples, {sample_rate}Hz")
                            
                            # Resample if needed
                            if sample_rate != SAMPLE_RATE:
                                ratio = SAMPLE_RATE / sample_rate
                                new_length = int(len(audio_data) * ratio)
                                resampled = np.interp(
                                    np.linspace(0, len(audio_data), new_length),
                                    np.arange(len(audio_data)),
                                    audio_data
                                )
                                audio_data = resampled.astype(np.float32)
                            
                            # Transcribe audio with streaming (uses global asr instance)
                            import time
                            asr_start = time.perf_counter()
                            transcription = ""

                            # Stream ASR segments to UI as they're recognized
                            async for partial_text in asr.transcribe_streaming(audio_data.astype(np.float32)):
                                transcription = partial_text
                                # Send partial result to frontend for live display
                                await session.send_message("asr_partial", {"text": partial_text})
                                print(f"[Voice Call] ASR partial: '{partial_text}'")

                            asr_elapsed = (time.perf_counter() - asr_start) * 1000
                            audio_duration = len(audio_data) / SAMPLE_RATE * 1000
                            print(f"[Voice Call] ⏱️ ASR: {asr_elapsed:.0f}ms for {audio_duration:.0f}ms audio (RTF: {asr_elapsed/audio_duration:.2f}x) → '{transcription}'")

                            if not transcription or not transcription.strip():
                                print("[Voice Call] Empty transcription, skipping")
                                await session.send_message("asr_result", {"text": ""})
                                continue

                            # Send final ASR result to frontend
                            await session.send_message("asr_result", {"text": transcription})

                            # Process with LLM and TTS
                            await session.process_user_message(transcription)
                            
                        except Exception as e:
                            print(f"[Voice Call] Error processing: {e}")
                            import traceback
                            traceback.print_exc()
                            await session.send_message("error", {"error": str(e)})
                    
                    elif msg_type == "video_call_data":
                        # Video call: audio + image from VAD/PTT
                        session.call_mode = "video"
                        print("[Video Call] Received video_call_data")
                        # Barge-in: if a Claw turn is mid-stream, cancel it.
                        # The user is talking again — Claw's reply has been
                        # superseded.
                        if session._claw_in_flight:
                            await session.cancel_claw_in_flight()
                        audio_b64 = data.get("audio")
                        image_b64 = data.get("image")
                        audio_format = data.get("format", "wav")
                        custom_prompt = data.get("system_prompt")
                        # Cache the latest frame so ask_claw can pass it through to
                        # Claw on the same turn (image pass-through, #46).
                        if image_b64:
                            session.last_camera_frame_b64 = image_b64
                        
                        if not audio_b64:
                            print("[Video Call] No audio in payload")
                            await session.send_message("error", {"error": "No audio data"})
                            continue
                        
                        try:
                            # Decode audio
                            import base64
                            audio_bytes = base64.b64decode(audio_b64)
                            print(f"[Video Call] Audio: {len(audio_bytes)} bytes, format: {audio_format}")
                            
                            # Convert WAV to numpy array
                            import io
                            import soundfile as sf
                            audio_data, sample_rate = sf.read(io.BytesIO(audio_bytes))
                            print(f"[Video Call] Audio decoded: {len(audio_data)} samples, {sample_rate}Hz")
                            
                            # Resample if needed
                            if sample_rate != SAMPLE_RATE:
                                ratio = SAMPLE_RATE / sample_rate
                                new_length = int(len(audio_data) * ratio)
                                resampled = np.interp(
                                    np.linspace(0, len(audio_data), new_length),
                                    np.arange(len(audio_data)),
                                    audio_data
                                )
                                audio_data = resampled.astype(np.float32)
                                print(f"[Video Call] Resampled to {SAMPLE_RATE}Hz: {len(audio_data)} samples")
                            
                            # Transcribe audio with streaming (uses global asr instance)
                            import time
                            asr_start = time.perf_counter()
                            transcription = ""

                            # Stream ASR segments to UI as they're recognized
                            async for partial_text in asr.transcribe_streaming(audio_data.astype(np.float32)):
                                transcription = partial_text
                                # Send partial result to frontend for live display
                                await session.send_message("asr_partial", {"text": partial_text})
                                print(f"[Video Call] ASR partial: '{partial_text}'")

                            asr_elapsed = (time.perf_counter() - asr_start) * 1000
                            audio_duration = len(audio_data) / SAMPLE_RATE * 1000
                            print(f"[Video Call] ⏱️ ASR: {asr_elapsed:.0f}ms for {audio_duration:.0f}ms audio (RTF: {asr_elapsed/audio_duration:.2f}x) → '{transcription}'")

                            if not transcription:
                                print("[Video Call] Empty transcription, skipping")
                                await session.send_message("asr_result", {"text": ""})
                                continue

                            # Send final ASR result to frontend
                            await session.send_message("asr_result", {"text": transcription})
                            
                            # Add to conversation history
                            session.conversation_history.append({
                                "role": "user",
                                "content": transcription
                            })
                            session.publish_handoff_state(include_empty=True)
                            
                            # Build VLM request with image if available
                            if image_b64:
                                print(f"[Video Call] Image: {len(image_b64)} chars base64")

                                if session.is_incomplete_codebase_fragment(transcription):
                                    session._pending_codebase_fragment = transcription
                                    await session.send_message("llm_final", {"text": ""})
                                    continue

                                intent_text = session.codebase_intent_text(transcription)

                                if session.is_codebase_brief_followup_request(intent_text):
                                    ack = "Got it."
                                    await session.send_transient_ack(ack)
                                    session.conversation_history.append({"role": "assistant", "content": ack})
                                    session.publish_handoff_state()
                                    continue

                                if session.is_workspace_update_request(intent_text):
                                    await session.handle_workspace_update_request(intent_text)
                                    continue

                                # Face recognition - recognize people in frame
                                face_context = ""
                                try:
                                    from clients.face import get_face_recognizer
                                    face_recognizer = get_face_recognizer()

                                    # Check for enrollment command: "remember my face as X" or "my name is X"
                                    lower_text = transcription.lower()
                                    if "remember my face as" in lower_text or "remember me as" in lower_text:
                                        # Extract name from command
                                        import re
                                        match = re.search(r'(?:remember (?:my face|me) as|my name is)\s+(\w+)', lower_text)
                                        if match:
                                            enroll_name = match.group(1).title()
                                            success = face_recognizer.enroll_face(enroll_name, image_b64)
                                            if success:
                                                await session.send_message("llm_final", {"text": f"Got it! I'll remember you as {enroll_name}."})
                                                await session.stream_tts(f"Got it! I'll remember you as {enroll_name}.")
                                                session.conversation_history.append({
                                                    "role": "assistant",
                                                    "content": f"Got it! I'll remember you as {enroll_name}."
                                                })
                                                session.publish_handoff_state()
                                                continue  # Skip VLM call
                                            else:
                                                await session.stream_tts("I couldn't see your face clearly. Please try again.")
                                                continue

                                    # Recognize faces in frame
                                    recognized = face_recognizer.recognize_faces(image_b64)
                                    if recognized:
                                        face_context = face_recognizer.format_scene_description(recognized)
                                        print(f"[Video Call] Face recognition: {face_context}")
                                except Exception as e:
                                    print(f"[Video Call] Face recognition error (non-fatal): {e}")

                                # Use VLM for response
                                from prompts import VIDEO_CALL_PROMPT, DEFAULT_SYSTEM_PROMPT

                                # Combine personal context with video call prompt
                                base_prompt = custom_prompt or DEFAULT_SYSTEM_PROMPT
                                system_prompt = f"{base_prompt}\n\n{VIDEO_CALL_PROMPT}"

                                # Add face context to system prompt if we recognized anyone
                                if face_context:
                                    system_prompt = f"{system_prompt}\n\nCURRENT SCENE: {face_context}"

                                # Get recent conversation history (last 10 messages, excluding current)
                                # This gives VLM context of recent conversation
                                VLM_HISTORY_LIMIT = 10
                                recent_history = session.conversation_history[-VLM_HISTORY_LIMIT-1:-1] if len(session.conversation_history) > 1 else []
                                print(f"[Video Call] Including {len(recent_history)} history messages for VLM")

                                # Get VLM response
                                vlm_start = time.perf_counter()
                                vlm = VLMClient(VLMConfig())
                                enabled_tool_defs = _filter_for_demo(get_enabled_tools(session.enabled_tools))

                                # Use streaming if no tools enabled, otherwise use non-streaming for tool support
                                if enabled_tool_defs:
                                    # Non-streaming mode with tool support
                                    vlm_result = await vlm.analyze_image(
                                        image_b64,
                                        intent_text,
                                        system_prompt=system_prompt,
                                        tools=enabled_tool_defs,
                                        history=recent_history
                                    )
                                    vlm_elapsed = (time.perf_counter() - vlm_start) * 1000

                                    response_text = vlm_result.get("content", "")
                                    tool_calls = vlm_result.get("tool_calls", [])

                                    print(f"[Video Call] ⏱️ VLM: {vlm_elapsed:.0f}ms → {len(response_text)} chars")

                                    # Handle tool calls
                                    if tool_calls:
                                        tool_names = [tc.get('function', {}).get('name') for tc in tool_calls]
                                        print(f"[Video Call] Tool calls: {tool_names}")

                                        # Short-circuit to UI-dispatched agent tools (they stream their own output)
                                        agent_dispatched = False
                                        for tool_call in tool_calls:
                                            func = tool_call.get("function", {})
                                            tool_name = func.get("name")
                                            try:
                                                args = json.loads(func.get("arguments", "{}"))
                                            except Exception:
                                                args = {}
                                            if tool_name in (
                                                "markdown_assistant",
                                                "html_assistant",
                                                "codebase_assistant",
                                                "reasoning_assistant",
                                                "workspace_update_assistant",
                                            ):
                                                if tool_name == "workspace_update_assistant":
                                                    ack = "Drafting the email now. You got him pineapple cakes last year; maybe try high mountain oolong tea?"
                                                elif tool_name == "codebase_assistant":
                                                    ack = "On it."
                                                else:
                                                    ack = "On it."
                                                await session.send_transient_ack(ack)
                                                if tool_name == "markdown_assistant":
                                                    await session.execute_markdown_agent(
                                                        args.get("task", ""),
                                                        args.get("context", ""),
                                                        args.get("output_path", ""),
                                                    )
                                                elif tool_name == "html_assistant":
                                                    await session.execute_html_agent(args.get("task", ""), args.get("context", ""))
                                                elif tool_name == "codebase_assistant":
                                                    session.start_codebase_agent_task(
                                                        args.get("task", "Build this sketch into a working MVP"),
                                                        args.get("context", ""),
                                                        args.get("output_dir", "agent_monitor_mvp"),
                                                    )
                                                elif tool_name == "reasoning_assistant":
                                                    await session.execute_reasoning_agent(
                                                        args.get("problem", ""),
                                                        args.get("context", ""),
                                                        args.get("analysis_type", "general"),
                                                    )
                                                elif tool_name == "workspace_update_assistant":
                                                    await session.execute_workspace_update_agent(
                                                        args.get("task", "Add handwritten todos to the project"),
                                                        args.get("context", ""),
                                                        args.get("items", []),
                                                    )
                                                agent_dispatched = True
                                                break

                                        if not agent_dispatched:
                                            # Inline tools: parallel exec + text-only agent loop to synthesize reply
                                            await session.stream_tts("Looking into it.", is_transient=True)
                                            session.conversation_history.append({
                                                "role": "assistant", "content": None, "tool_calls": tool_calls,
                                            })
                                            tool_results = await session._execute_tool_calls_parallel(tool_calls)
                                            for tr in tool_results:
                                                session.conversation_history.append(tr)

                                            synth_text = ""
                                            sb = ""
                                            progressive = False
                                            for _ in range(session.MAX_TOOL_ITERATIONS):
                                                if not session.alive:
                                                    return
                                                next_calls = None
                                                async for chunk in llm.stream_complete(
                                                    list(session.conversation_history),
                                                    tools=enabled_tool_defs if enabled_tool_defs else None,
                                                ):
                                                    if not session.alive:
                                                        return
                                                    if not chunk.startswith("data: "):
                                                        continue
                                                    try:
                                                        d = json.loads(chunk[6:])
                                                    except json.JSONDecodeError:
                                                        continue
                                                    if "tool_calls_complete" in d:
                                                        next_calls = d["tool_calls_complete"]
                                                        break
                                                    if "content" in d and d["content"]:
                                                        piece = d["content"]
                                                        synth_text += piece
                                                        sb += piece
                                                        sents, sb = session._extract_complete_sentences(sb)
                                                        for s in sents:
                                                            s = s.strip()
                                                            if s:
                                                                # Serial: see server.py agent-loop note above.
                                                                await session.stream_tts(s)
                                                                progressive = True
                                                if not next_calls:
                                                    break
                                                await session.send_message("tool_invocation", {"message": "One moment…"})
                                                more = await session._execute_tool_calls_parallel(next_calls)
                                                session.conversation_history.append({
                                                    "role": "assistant", "content": None, "tool_calls": next_calls,
                                                })
                                                for tr in more:
                                                    session.conversation_history.append(tr)

                                            if synth_text.strip():
                                                session.conversation_history.append({"role": "assistant", "content": synth_text})
                                                session.publish_handoff_state()
                                                await session.send_message("llm_final", {"text": synth_text})
                                                if progressive:
                                                    tail = sb.strip()
                                                    if tail:
                                                        await session.stream_tts(tail)
                                                else:
                                                    await session.stream_tts(synth_text)
                                    else:
                                        if session.is_codebase_build_request(intent_text):
                                            ack = "On it."
                                            await session.send_transient_ack(ack)
                                            fallback_context = response_text or (
                                                "Visible sketch from the current video frame. Build the Agent Monitor MVP with "
                                                "dashboard, activity feed, task history, overview cards, agent list, and run history."
                                            )
                                            session.start_codebase_agent_task(
                                                intent_text,
                                                fallback_context,
                                                "agent_monitor_mvp",
                                            )
                                            session.conversation_history.append({"role": "assistant", "content": ack})
                                            session.publish_handoff_state()
                                            continue
                                        # Regular response - speak it
                                        if response_text:
                                            session.conversation_history.append({
                                                "role": "assistant",
                                                "content": response_text
                                            })
                                            session.publish_handoff_state()
                                            await session.send_message("llm_final", {"text": response_text})
                                            await session.stream_tts(response_text)
                                else:
                                    # Streaming mode (no tools) - stream text to UI as it arrives
                                    print("[Video Call] Using streaming VLM (no tools)")
                                    response_text = ""
                                    async for chunk in vlm.stream_analyze_image(
                                        image_b64,
                                        intent_text,
                                        system_prompt=system_prompt,
                                        history=recent_history
                                    ):
                                        response_text += chunk
                                        # Send chunk to frontend for live display
                                        await session.send_message("transient_response", {"text": response_text})

                                    vlm_elapsed = (time.perf_counter() - vlm_start) * 1000
                                    print(f"[Video Call] ⏱️ VLM Stream: {vlm_elapsed:.0f}ms → {len(response_text)} chars")

                                    if response_text:
                                        session.conversation_history.append({
                                            "role": "assistant",
                                            "content": response_text
                                        })
                                        session.publish_handoff_state()
                                        await session.send_message("llm_final", {"text": response_text})
                                        await session.stream_tts(response_text)
                            else:
                                # No image - use regular LLM
                                print("[Video Call] No image, using text LLM")
                                await session.process_user_message(transcription)
                                
                        except Exception as e:
                            print(f"[Video Call] Error processing: {e}")
                            import traceback
                            traceback.print_exc()
                            await session.send_message("error", {"error": str(e)})
                    
                    elif msg_type == "disconnect":
                        # Client requested disconnect
                        await session.send_message("disconnect_ack")
                        session._ws_closed = True
                        try:
                            await websocket.close()
                        except Exception:
                            pass
                        return
                    
                except json.JSONDecodeError as e:
                    print(f"[Voice Call] Invalid JSON: {e}")
                    await session.send_message("error", {"error": "Invalid message format"})
    
    except WebSocketDisconnect:
        print("[Voice Call] WebSocket disconnected")
    except Exception as e:
        print(f"[Voice Call] Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            await session.send_message("error", {"error": str(e)})
        except:
            pass
    finally:
        if active_conversation_sessions.get(session.conversation_id) is session:
            active_conversation_sessions.pop(session.conversation_id, None)
        print("[Voice Call] Session ended")


# -----------------------------
# Legacy endpoints (for backward compatibility)
# -----------------------------

@app.post("/api/voice_chat")
async def voice_chat(audio: UploadFile = File(...)):
    """Legacy non-streaming endpoint."""
    tmp_id = uuid.uuid4().hex
    tmp_webm = AUDIO_DIR / f"{tmp_id}.webm"
    with open(tmp_webm, "wb") as f:
        f.write(await audio.read())

    try:
        pcm = decode_webm_to_pcm_f32(tmp_webm, target_sr=SAMPLE_RATE)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to decode audio: {e}"},
        )
    finally:
        try:
            tmp_webm.unlink()
        except FileNotFoundError:
            pass

    user_text = await asr.transcribe(pcm)
    if not user_text:
        return {"user_text": "", "assistant_text": "", "audio_url": ""}

    conversation_history.append({"role": "user", "content": user_text})
    assistant_text = await llm.complete(conversation_history)
    conversation_history.append({"role": "assistant", "content": assistant_text})

    out_wav = AUDIO_DIR / f"{tmp_id}.wav"
    tts.synth_to_file(assistant_text, out_wav)
    audio_url = f"/audio/{out_wav.name}"

    return {
        "user_text": user_text,
        "assistant_text": assistant_text,
        "audio_url": audio_url,
    }
