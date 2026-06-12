"""Persistent ACP bridge to OpenClaw — replaces per-call `openclaw agent` CLI.

Why: the CLI subprocess paid ~3 s of node cold-start every call and returned
the whole JSON reply only after Claw was done thinking (~24 s of silent
wait). ACP keeps a connection open, streams text chunks as the agent
generates them (~10 s end-to-end, first chunk in seconds), and supports
mid-turn cancel.

We talk to `openclaw acp` as a long-lived subprocess and speak ACP JSON-RPC
over its stdio. The bridge translates that to the gateway WebSocket
internally — saves us from re-implementing the gateway's auth/protocol
ourselves.

Usage:

    bridge = ClawAcp()
    await bridge.start()
    async for chunk in bridge.prompt("what's 2 + 2?"):
        print(chunk, end="", flush=True)
    await bridge.stop()
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional


CLAW_CONFIG = Path(os.environ.get("OPENCLAW_CONFIG", os.path.expanduser("~/.openclaw/openclaw.json")))


def _gateway_token() -> Optional[str]:
    try:
        d = json.loads(CLAW_CONFIG.read_text())
        return ((d.get("gateway") or {}).get("auth") or {}).get("token")
    except Exception:
        return None


class ClawAcp:
    """One persistent `openclaw acp` subprocess + a single Claw session.

    Concurrency: this client serializes prompts. If you call prompt() while
    a previous prompt's stream is still open, it will await the previous one.
    For multi-prompt concurrency, instantiate multiple ClawAcp objects (each
    spawns its own subprocess + session).
    """

    def __init__(self, *, agent: str = "main", session_key: Optional[str] = None,
                 binary: Optional[str] = None, token: Optional[str] = None,
                 startup_timeout_s: float = 10.0):
        self._agent = agent
        self._session_key = session_key or f"agent:{agent}:main"
        self._binary = binary or os.environ.get("OPENCLAW_BIN") or "openclaw"
        self._token = token or _gateway_token()
        self._startup_timeout_s = startup_timeout_s
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._next_id = 100
        self._pending: Dict[int, asyncio.Future] = {}
        self._notif_queue: Optional[asyncio.Queue] = None
        self._session_id: Optional[str] = None
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def alive(self) -> bool:
        return bool(self._proc and self._proc.returncode is None and not self._closed)

    # ----- lifecycle -----

    async def start(self) -> None:
        if self.alive:
            return
        if not self._token:
            raise RuntimeError("openclaw gateway token not found — set OPENCLAW_CONFIG or pass token=")
        argv = [self._binary, "acp", "--token", self._token, "--session", self._session_key]
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._notif_queue = asyncio.Queue()
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())

        # Wait for the bridge to print '[acp] ready' on stderr (or up to N s)
        # The reader will start accepting JSON frames as soon as they arrive.
        await asyncio.sleep(0.4)

        await self._call("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {},
        })
        new = await self._call("session/new", {"cwd": "/tmp", "mcpServers": []})
        self._session_id = new["sessionId"]

    async def stop(self) -> None:
        self._closed = True
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
            except Exception:
                pass
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        for t in (self._reader_task, self._stderr_task):
            if t and not t.done():
                t.cancel()

    # ----- request helpers -----

    async def _send(self, method: str, params: Optional[dict] = None,
                    *, notify: bool = False) -> Optional[int]:
        if not self.alive:
            raise RuntimeError("ACP bridge not running")
        rid = None
        if not notify:
            rid = self._next_id
            self._next_id += 1
        frame = {"jsonrpc": "2.0", "method": method}
        if rid is not None:
            frame["id"] = rid
        if params is not None:
            frame["params"] = params
        line = json.dumps(frame) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()
        return rid

    async def _call(self, method: str, params: Optional[dict] = None, *, timeout: float = 20.0) -> dict:
        rid = await self._send(method, params)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            res = await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)
        if "error" in res:
            raise RuntimeError(f"ACP {method} error: {res['error']}")
        return res.get("result", {})

    # ----- main API -----

    async def prompt(self, text: str, *, image_b64: Optional[str] = None,
                     image_mime: str = "image/jpeg",
                     timeout_s: float = 120.0) -> AsyncGenerator[str, None]:
        """Send a prompt and yield text chunks as Claw streams them.

        After the generator exhausts, prompt completion is acknowledged.
        Raises on transport errors; never raises on Claw refusals (those come
        through as text chunks).
        """
        if not self.alive:
            await self.start()
        # serialize calls so a second prompt() doesn't interleave with a first
        async with self._lock:
            content = [{"type": "text", "text": text}]
            if image_b64:
                # ACP image-content format (per the bridge's promptCapabilities.image:true)
                content.append({"type": "image", "data": image_b64, "mimeType": image_mime})

            # Drain any stray notifications from before this prompt so we only
            # surface chunks belonging to this turn.
            while self._notif_queue and not self._notif_queue.empty():
                self._notif_queue.get_nowait()

            rid = await self._send("session/prompt", {
                "sessionId": self._session_id,
                "prompt": content,
            })
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            self._pending[rid] = fut

            t0 = time.perf_counter()
            try:
                while True:
                    # race: completion vs. next streamed chunk
                    notif_task = asyncio.create_task(self._notif_queue.get())
                    done, _ = await asyncio.wait(
                        [fut, notif_task],
                        timeout=timeout_s,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        notif_task.cancel()
                        raise asyncio.TimeoutError(f"ACP prompt timed out after {timeout_s}s")
                    if notif_task in done:
                        notif = notif_task.result()
                        upd = (notif.get("params") or {}).get("update") or {}
                        if upd.get("sessionUpdate") == "agent_message_chunk":
                            c = upd.get("content") or {}
                            if c.get("type") == "text":
                                yield c.get("text", "")
                    else:
                        notif_task.cancel()
                    if fut.done():
                        # final response received — drain any last chunks left in queue
                        while not self._notif_queue.empty():
                            n = self._notif_queue.get_nowait()
                            up = (n.get("params") or {}).get("update") or {}
                            if up.get("sessionUpdate") == "agent_message_chunk":
                                c = up.get("content") or {}
                                if c.get("type") == "text":
                                    yield c.get("text", "")
                        break
            finally:
                self._pending.pop(rid, None)

            res = fut.result()
            if "error" in res:
                raise RuntimeError(f"ACP session/prompt error: {res['error']}")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            print(f"[claw_acp] prompt completed in {elapsed_ms:.0f}ms (stop_reason={res.get('result', {}).get('stopReason')})")

    async def cancel(self) -> None:
        """Cancel the in-flight session/prompt, if any."""
        if not self.alive or not self._session_id:
            return
        try:
            await self._send("session/cancel", {"sessionId": self._session_id}, notify=True)
        except Exception:
            pass

    # ----- internal IO -----

    async def _read_stdout(self) -> None:
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    return
                s = line.decode(errors="ignore").strip()
                if not s.startswith("{"):
                    continue
                try:
                    msg = json.loads(s)
                except json.JSONDecodeError:
                    continue
                if "id" in msg and ("result" in msg or "error" in msg):
                    fut = self._pending.get(msg["id"])
                    if fut and not fut.done():
                        fut.set_result(msg)
                else:
                    # streaming notification (session/update etc)
                    if self._notif_queue is not None:
                        await self._notif_queue.put(msg)
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[claw_acp] reader stopped: {e}")

    async def _read_stderr(self) -> None:
        try:
            while True:
                line = await self._proc.stderr.readline()
                if not line:
                    return
                s = line.decode(errors="ignore").rstrip()
                if s and "ready" not in s.lower():
                    print(f"[claw_acp/stderr] {s}")
        except asyncio.CancelledError:
            return
        except Exception:
            return


# ----- module-level singleton helper -----
# realtime2 talks to one Claw at a time; share the bridge across all sessions.

_singleton: Optional[ClawAcp] = None
_singleton_lock = asyncio.Lock()


async def get_singleton() -> ClawAcp:
    global _singleton
    async with _singleton_lock:
        if _singleton is None or not _singleton.alive:
            _singleton = ClawAcp()
            await _singleton.start()
    return _singleton


async def shutdown_singleton() -> None:
    global _singleton
    if _singleton is not None:
        await _singleton.stop()
        _singleton = None
