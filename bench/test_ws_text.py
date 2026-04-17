#!/usr/bin/env python3
"""Full-server e2e: open a WebSocket to /ws/voice, send a text turn, collect
messages until final_response, measure TTFT-to-first-content and total time.

Run inside the running container (or on host with `pip install websockets`):
  python3 bench/test_ws_text.py --url ws://localhost:8453/ws/voice --text "hi"
"""
import argparse
import asyncio
import json
import time

import websockets


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8453/ws/voice")
    ap.add_argument("--text", default="What's 2 plus 2?")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    print(f"→ connecting {args.url}")
    async with websockets.connect(args.url, max_size=None) as ws:
        # Drain the server's handshake + initial greeting until things quiet down
        drain_deadline = time.time() + 4.0
        while time.time() < drain_deadline:
            try:
                _ = await asyncio.wait_for(ws.recv(), timeout=max(0.05, drain_deadline - time.time()))
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
            drain_deadline = min(drain_deadline, time.time() + 0.5)

        await ws.send(json.dumps({"type": "set_tools", "tools": []}))
        # Brief pause to let set_tools land
        await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "text_message", "text": args.text}))
        print(f"→ sent text_message: {args.text!r}")
        t0 = time.perf_counter()

        ttft_ms = None
        final_text = None
        saw_final = False
        deadline = time.time() + args.timeout
        n_msgs = 0
        n_audio = 0
        while time.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
            except asyncio.TimeoutError:
                break
            n_msgs += 1
            if isinstance(msg, bytes):
                n_audio += 1
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000
                continue
            try:
                j = json.loads(msg)
            except Exception:
                continue
            mt = j.get("type")
            if mt in ("transient_response", "llm_final", "final_response"):
                txt = j.get("text", "")
                if txt and ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000
                if mt == "final_response":
                    final_text = txt
                    saw_final = True
                    # Don't break — let a bit of audio flow in for realism
                    deadline = min(deadline, time.time() + 1.0)
            elif mt in ("tts_chunk", "tts_start"):
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000
            # Print terse one-liner per message
            if mt and mt not in ("tts_chunk",):
                print(f"  [{(time.perf_counter()-t0)*1000:.0f}ms] {mt}: {str(j)[:120]}")

        total_ms = (time.perf_counter() - t0) * 1000
        print()
        print(f"msgs: {n_msgs}, binary audio frames: {n_audio}")
        print(f"ttft: {ttft_ms:.0f}ms" if ttft_ms else "ttft: (never)")
        print(f"total: {total_ms:.0f}ms")
        print(f"saw final_response: {saw_final}")
        if final_text:
            print(f"final: {final_text[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
