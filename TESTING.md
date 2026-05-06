**Feature: Bidirectional conversation handoff**
**Test #1: Server handoff helper smoke**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python bench/test_handoff.py`
**Result**:
```bash
handoff helper smoke: PASS
```
**Coverage:** Sanitizes handoff history, drops tool-only messages, preserves system prompt/tools/voice/call mode, exposes `/api/handoff/status` for the Start New Chat modal before camera/mic permission, discovers the newest active conversation even when the new device does not know the prior `conversation_id`, exposes offers only to another active device, transfers desktop -> mobile, transfers mobile -> desktop, and TTL-prunes stale state.

**Feature: Bidirectional conversation handoff**
**Test #2: Syntax and static checks**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python -m py_compile server.py bench/test_handoff.py && node --check static/js/app.js`
**Result**:
```bash
No output. Commands exited successfully.
```

**Feature: Bidirectional conversation handoff**
**Test #3: Handoff token static assertions**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python - <<'PY' ... assert server/app tokens for conversation_id, resume_handoff, handoff_transferred, handoff_required, and bringConversationBack ... PY`
**Result**:
```bash
handoff static assertions: PASS
```

**Feature: Bidirectional conversation handoff**
**Test #4: Whitespace check**
**Status:** PASS
**Code Command**: `git diff --check`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Full demo prompt regression**
**Test #2: Checked-in live E2E prompt suite**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python bench/test_demo_prompts.py`
**Result**:
```bash
demo prompt e2e: url=http://localhost:11434/v1/chat/completions model=qwen3.6:35b-a3b
Cold open: PASS :: Yep. You're on camera, audio is clear, and I'm ready. (2090ms)
Beat 1 README tool: PASS :: markdown_assistant with README.md and React/FastAPI/MySQL context. (3499ms)
Beat 1 improvement: PASS :: Polling MySQL for dashboard updates won't scale. I'd keep MySQL as the source of truth, but add Redis pub/sub between FastAPI instances for realtime fanout. I can sketch that design. (1176ms)
Beat 1 realtime design tool: PASS :: markdown_assistant with realtime_design.md and Redis pub/sub context. (2301ms)
Beat 2 fashion: PASS :: Yep. The dark jacket reads professional and polished, which is a nice upgrade despite the late-night coding. (2159ms)
Beat 3 menu: PASS :: Recommends visible lighter items over salty visible items without private health labels or raw digits. (2169ms)
Beat 4 todo routing tool: PASS :: workspace_update_assistant with all six visible handwritten items. (4474ms)
demo prompt e2e: PASS
```

**Feature: Beat 3 private health context**
**Test #1: Health context loader privacy safety (Test A)**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python - <<'PY' ... import _load_health_context and VIDEO_CALL_PROMPT; assert no raw health/WHOOP numbers, no diagnosis/medication/category labels, qualitative sodium and ramen context present, and loader block is wired into VIDEO_CALL_PROMPT ... PY`
**Result**:
```bash
Test A speech-safe loader: PASS
```

**Feature: Beat 3 private health context**
**Test #2: Demo-file isolation (Test B)**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python - <<'PY' ... VoiceSession.__new__(VoiceSession).load_demo_files(); assert health.yaml/whoop_auth sensitive tokens do not appear ... PY`
**Result**:
```bash
Test B demo-file isolation: PASS
```

**Feature: Beat 3 private health context**
**Test #3: Missing WHOOP subtree graceful degrade (Test C)**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python - <<'PY' ... copy demo_files/health-dummy-data.yaml, remove whoop:, set HEALTH_YAML_PATH, assert non-empty context includes WHOOP data unavailable plus qualitative meal/condition context from relative meal metadata and no digits ... PY`
**Result**:
```bash
Test C missing WHOOP graceful degrade: PASS
```

**Feature: Beat 3 private health context**
**Test #4: Live Chinese-menu privacy and grounding regression (Test D)**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python - <<'PY' ... send local test_assets/menu_zh.png to local qwen3.6:35b-a3b with DEFAULT_SYSTEM_PROMPT + VIDEO_CALL_PROMPT; assert visible translated dish recommendation, visible skip dish, skip/over connective, food-language reason, and no sensitive labels or raw numbers ... PY`
**Result**:
```bash
I'd go with the steamed sea bass over the fried pork chops because the pork is fried and salty, and you've had heavy meals lately.
Test D live Beat 3 privacy/grounding: PASS
```
**Note:** The ignored local fixture `test_assets/menu_zh_dishes.json` accepts both the canonical translation "salt-and-pepper pork chop" and the model's observed translation variant "fried pork chop(s)" for `椒盐猪排`.

**Feature: Beat 3 private health context**
**Test #5: Import-time concatenation (Test F)**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python - <<'PY' ... touch demo_files/health.yaml, assert prompts.VIDEO_CALL_PROMPT constant is unchanged until importlib.reload(prompts), then assert health context remains wired ... PY`
**Result**:
```bash
Test F import-time concatenation: PASS
```

**Feature: Beat 3 private health context**
**Test #6: WHOOP OAuth credential gate**
**Status:** PASS (superseded by Phase 3 implementation smoke tests below)
**Code Command**: `.venv-gpu/bin/python - <<'PY' ... print whether WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET are set ... PY`
**Result**:
```bash
WHOOP_CLIENT_ID=unset
WHOOP_CLIENT_SECRET=unset
```
**Note:** Phase 3 was originally skipped by policy because credentials were absent. It was reopened after credentials were added.

**Feature: WHOOP OAuth local cache**
**Test #1: Auth URL configuration**
**Status:** PASS
**Code Command**: `source ~/.bashrc && .venv-gpu/bin/python - <<'PY' ... assert WhoopConfig is enabled, redirect URI is https://localhost:8443/whoop/callback, auth URL uses response_type=code, state, and least-privilege scopes ... PY`
**Result**:
```bash
whoop auth_url config: PASS
```

**Feature: WHOOP OAuth local cache**
**Test #2: YAML cache and auth token writers**
**Status:** PASS
**Code Command**: `source ~/.bashrc && .venv-gpu/bin/python - <<'PY' ... normalize fixture WHOOP payloads, replace only whoop: in a temp health.yaml, write temp auth tokens, assert token mode 600 ... PY`
**Result**:
```bash
whoop yaml/token writers: PASS
```

**Feature: WHOOP OAuth local cache**
**Test #2b: Cron refresh wrapper syntax**
**Status:** PASS
**Code Command**: `bash -n scripts/refresh-whoop.sh`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: WHOOP OAuth local cache**
**Test #3: FastAPI route registration**
**Status:** PASS
**Code Command**: `source ~/.bashrc && .venv-gpu/bin/python - <<'PY' ... import server.app and assert /whoop/login and /whoop/callback are registered ... PY`
**Result**:
```bash
whoop routes registered: PASS
```

**Feature: WHOOP OAuth local cache**
**Test #4: Real WHOOP OAuth browser flow (Test G)**
**Status:** NOT RUN
**Code Command**: `Open https://localhost:8443/whoop/login in a browser after launching the app with WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, and WHOOP_REDIRECT_URI.`
**Result**:
```bash
Manual consent flow pending.
```
**Note:** The non-interactive implementation checks pass. The final WHOOP consent step requires a browser login and cannot be completed by the test harness without user interaction.

**Feature: Live prompt regression against local Qwen3.6**
**Test #1: Demo beats prompt and tool-call behavior**
**Status:** PASS
**Code Command**: `python3 - <<'PY' ... live prompt suite against http://localhost:11434/v1/chat/completions using DEFAULT_SYSTEM_PROMPT, VIDEO_CALL_PROMPT, and enabled tool schemas ... PY`
**Result**:
```bash
Cold open camera/audio response: PASS
  text: Yep. You're on camera, audio is clear, and I'm ready.

Beat 1 README tool call: PASS
  tool: markdown_assistant
  args: {'task': 'Convert the hand-drawn architecture into a Markdown README', 'context': 'Whiteboard shows: React frontend -> FastAPI backend -> MySQL database', 'output_path': 'README.md'}

Beat 1 engineering judgment, no customer-data tool: PASS
  text: Polling MySQL for dashboard updates won't scale. I'd keep MySQL as the source of truth, but add Redis pub/sub between FastAPI instances for realtime fanout. I can sketch that design.

Beat 1 follow-up realtime design tool call: PASS
  tool: markdown_assistant
  args: {'task': 'Sketch a realtime architecture design for React Dashboard -> FastAPI -> MySQL with Redis pub/sub for realtime fanout', 'context': 'Whiteboard architecture shows React Dashboard -> FastAPI -> MySQL. User wants to improve it by adding Redis pub/sub for realtime updates instead of polling MySQL.', 'output_path': 'realtime_design.md'}

Beat 2 fashion answer: PASS
  text: Yep, that dark navy top looks professional and put together on camera. It's a solid choice for your calls today.

Beat 3 private menu recommendation: PASS
  text: I'd recommend the braised vegetables and steamed rice over the beef noodle soup. The vegetables offer a lighter, higher-protein option that aligns with your fitness goals, while the beef noodle soup is heavy in salt and carbs, especially after yesterday's ramen.

Beat 4 handwritten todo workspace tool call: PASS
  tool: workspace_update_assistant
  args: {'task': 'Add these handwritten todos to the project', 'context': 'Handwritten note lists: add streaming updates; Redis pub/sub; write events table; React hook; test reconnect; buy umbrella.', 'items': ['add streaming updates', 'Redis pub/sub', 'write events table', 'React hook', 'test reconnect', 'buy umbrella']}
```

**Feature: Post-merge claw demo regression rerun**
**Test #1: Syntax, JavaScript, and whitespace checks**
**Status:** PASS
**Code Command**: `python3 -m py_compile server.py prompts.py tools.py clients/*.py && node --check static/js/app.js && git diff --check HEAD`
**Result**:
```bash
No output. Commands exited successfully.
```

**Feature: Post-merge claw demo regression rerun**
**Test #2: Tool schema sentinel validation**
**Status:** PASS
**Code Command**:
```bash
python3 - <<'PY'
import json
import asyncio
from tools import ALL_TOOLS, execute_tool, is_agent_tool

assert 'workspace_update_assistant' in ALL_TOOLS
assert 'output_path' in ALL_TOOLS['markdown_assistant']['function']['parameters']['properties']
assert is_agent_tool('workspace_update_assistant')

async def main():
    md = json.loads(await execute_tool('markdown_assistant', {
        'task': 'Convert this hand-drawn architecture into a Markdown README',
        'context': 'React frontend -> FastAPI backend -> MySQL',
        'output_path': 'README.md',
    }))
    ws = json.loads(await execute_tool('workspace_update_assistant', {
        'task': 'Add these to the project',
        'items': ['add streaming updates', 'Redis pub/sub', 'write events table', 'React hook', 'test reconnect', 'buy umbrella'],
    }))
    assert md['agent_type'] == 'markdown_assistant'
    assert md['output_path'] == 'README.md'
    assert ws['agent_type'] == 'workspace_update_assistant'
    assert len(ws['items']) == 6
    print('markdown:', md)
    print('workspace:', ws)

asyncio.run(main())
PY
```
**Result**:
```bash
markdown: {'agent_type': 'markdown_assistant', 'task': 'Convert this hand-drawn architecture into a Markdown README', 'context': 'React frontend -> FastAPI backend -> MySQL', 'output_path': 'README.md', 'status': 'initiated'}
workspace: {'agent_type': 'workspace_update_assistant', 'task': 'Add these to the project', 'context': '', 'items': ['add streaming updates', 'Redis pub/sub', 'write events table', 'React hook', 'test reconnect', 'buy umbrella'], 'status': 'initiated'}
```

**Feature: Post-merge claw demo regression rerun**
**Test #3: Beat 4 deterministic routing**
**Status:** PASS
**Code Command**:
```bash
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import server

with TemporaryDirectory() as tmp:
    server.WORKSPACE_ROOT = Path(tmp).resolve()
    session = server.VoiceSession.__new__(server.VoiceSession)
    assert session.infer_markdown_output_path('Convert this hand-drawn architecture into a Markdown README for the project.') == 'README.md'
    assert session.infer_markdown_output_path('Yeah, sketch the Redis pub/sub realtime design.') == 'realtime_design.md'
    assert session.is_workspace_update_request('Add these to the project')
    assert session.is_workspace_update_request('Can you add these handwritten todos to the project?')
    assert not session.is_workspace_update_request('What should I order from this menu?')
    todos = session.extract_workspace_todos(
        'Add these to the project',
        'Visible handwritten note: add streaming updates; Redis pub/sub; write events table; React hook; test reconnect; buy umbrella',
        []
    )
    result = session.apply_workspace_todo_updates(todos)
    root = Path(tmp)
    tasks = (root / result['files']['project_tasks']).read_text()
    design = (root / result['files']['realtime_design']).read_text()
    personal = (root / result['files']['personal_todos']).read_text()
    assert 'Add streaming updates' in tasks
    assert 'Add Redis pub/sub' in tasks
    assert 'Test reconnect' in tasks
    assert 'Buy umbrella' not in tasks
    assert 'Redis pub/sub fans events out across FastAPI instances' in design
    assert 'Buy umbrella' in personal
    print('routing: PASS')
    print('todos:', todos)
    print('files:', result['files'])
PY
```
**Result**:
```bash
routing: PASS
todos: ['Add streaming updates', 'Add Redis pub/sub', 'Write events table', 'Build React hook', 'Test reconnect', 'Buy umbrella']
files: {'project_tasks': 'workspace/project_dashboard/tasks.md', 'realtime_design': 'workspace/realtime_design.md', 'personal_todos': 'workspace/personal_todos.md'}
```

**Feature: GPU runtime availability**
**Test #1: Docker CUDA GPU visibility**
**Status:** PASS
**Code Command**: `docker run --rm --gpus all nvcr.io/nvidia/cuda:13.0.0-devel-ubuntu24.04 nvidia-smi --query-gpu=name,driver_version --format=csv,noheader`
**Result**:
```bash
NVIDIA GB10, 580.95.05
```

**Feature: GPU runtime availability**
**Test #2: Host Python CUDA package check**
**Status:** INFO
**Code Command**: `python3 - <<'PY' ... torch and ctranslate2 CUDA checks ... PY`
**Result**:
```bash
host_torch: 2.10.0+cpu
host_cuda_available: False
host_ctranslate2: 4.7.1
host_ct2_cuda_error: ValueError This CTranslate2 package was not compiled with CUDA support
```

**Feature: Claw/main demo merge regression**
**Test #1: Post-merge syntax and whitespace validation**
**Status:** PASS
**Code Command**: `python3 -m py_compile server.py prompts.py tools.py clients/*.py && node --check static/js/app.js && git diff --check HEAD`
**Result**:
```bash
No output. Commands exited successfully.
```

**Feature: Claw/main demo merge regression**
**Test #2: Tool schema sentinel validation**
**Status:** PASS
**Code Command**:
```bash
python3 - <<'PY'
import json
import asyncio
from tools import ALL_TOOLS, execute_tool, is_agent_tool

assert 'workspace_update_assistant' in ALL_TOOLS
assert 'output_path' in ALL_TOOLS['markdown_assistant']['function']['parameters']['properties']
assert is_agent_tool('workspace_update_assistant')

async def main():
    md = json.loads(await execute_tool('markdown_assistant', {
        'task': 'Convert this hand-drawn architecture into a Markdown README',
        'context': 'React frontend -> FastAPI backend -> MySQL',
        'output_path': 'README.md',
    }))
    ws = json.loads(await execute_tool('workspace_update_assistant', {
        'task': 'Add these to the project',
        'items': ['add streaming updates', 'Redis pub/sub', 'write events table', 'React hook', 'test reconnect', 'buy umbrella'],
    }))
    assert md['agent_type'] == 'markdown_assistant'
    assert md['output_path'] == 'README.md'
    assert ws['agent_type'] == 'workspace_update_assistant'
    assert len(ws['items']) == 6
    print('markdown:', md)
    print('workspace:', ws)

asyncio.run(main())
PY
```
**Result**:
```bash
markdown: {'agent_type': 'markdown_assistant', 'task': 'Convert this hand-drawn architecture into a Markdown README', 'context': 'React frontend -> FastAPI backend -> MySQL', 'output_path': 'README.md', 'status': 'initiated'}
workspace: {'agent_type': 'workspace_update_assistant', 'task': 'Add these to the project', 'context': '', 'items': ['add streaming updates', 'Redis pub/sub', 'write events table', 'React hook', 'test reconnect', 'buy umbrella'], 'status': 'initiated'}
```

**Feature: Beat 4 phone handwritten-note fast path**
**Test #1: Deterministic trigger and workspace routing**
**Status:** PASS
**Code Command**:
```bash
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import server

with TemporaryDirectory() as tmp:
    server.WORKSPACE_ROOT = Path(tmp).resolve()
    session = server.VoiceSession.__new__(server.VoiceSession)
    assert session.is_workspace_update_request('Add these to the project')
    assert session.is_workspace_update_request('Can you add these handwritten todos to the project?')
    assert not session.is_workspace_update_request('What should I order from this menu?')
    todos = session.extract_workspace_todos('Add these to the project', 'Phone handwritten-note request: Add these to the project', [])
    result = session.apply_workspace_todo_updates(todos)
    root = Path(tmp)
    tasks = (root / result['files']['project_tasks']).read_text()
    design = (root / result['files']['realtime_design']).read_text()
    personal = (root / result['files']['personal_todos']).read_text()
    assert 'Add streaming updates' in tasks
    assert 'Add Redis pub/sub' in tasks
    assert 'Test reconnect' in tasks
    assert 'Buy umbrella' not in tasks
    assert 'Redis pub/sub fans events out across FastAPI instances' in design
    assert 'Buy umbrella' in personal
    print('trigger: PASS')
    print('todos:', todos)
    print('files:', result['files'])
PY
```
**Result**:
```bash
trigger: PASS
todos: ['Add streaming updates', 'Add Redis pub/sub', 'Write events table', 'Build React hook', 'Test reconnect', 'Buy umbrella']
files: {'project_tasks': 'workspace/project_dashboard/tasks.md', 'realtime_design': 'workspace/realtime_design.md', 'personal_todos': 'workspace/personal_todos.md'}
```

**Feature: Route handwritten todos into workspace project files**
**Test #1: Python and JavaScript syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile server.py prompts.py tools.py && node --check static/js/app.js && git diff --check -- tools.py prompts.py server.py static/index.html static/js/app.js`
**Result**:
```bash
No output. Commands exited successfully.
```

**Feature: Route handwritten todos into workspace project files**
**Test #2: Deterministic workspace routing**
**Status:** PASS
**Code Command**:
```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import server

with TemporaryDirectory() as tmp:
    server.WORKSPACE_ROOT = Path(tmp).resolve()
    session = server.VoiceSession.__new__(server.VoiceSession)
    todos = session.extract_workspace_todos(
        'Add these to the project',
        'Visible handwritten note: add streaming updates; Redis pub/sub; write events table; React hook; test reconnect; buy umbrella',
        []
    )
    result = session.apply_workspace_todo_updates(todos)
    root = Path(tmp)
    tasks = (root / result['files']['project_tasks']).read_text()
    design = (root / result['files']['realtime_design']).read_text()
    personal = (root / result['files']['personal_todos']).read_text()

    assert 'Add Redis pub/sub' in tasks
    assert 'Buy umbrella' not in tasks
    assert 'Redis pub/sub fans events out across FastAPI instances' in design
    assert 'Buy umbrella' in personal
    print('todos:', todos)
    print('files:', result['files'])
PY
```
**Result**:
```bash
todos: ['Add streaming updates', 'Add Redis pub/sub', 'Write events table', 'Build React hook', 'Test reconnect', 'Buy umbrella']
files: {'project_tasks': 'workspace/project_dashboard/tasks.md', 'realtime_design': 'workspace/realtime_design.md', 'personal_todos': 'workspace/personal_todos.md'}
```

**Feature: Route handwritten todos into workspace project files**
**Test #3: Served asset verification**
**Status:** PASS
**Code Command**: `curl -ks https://localhost:8443/ | rg -n "agentWorkspaceUpdateAssistant|beat4-workspace-routing" && curl -ks 'https://localhost:8443/static/js/app.js?v=beat4-workspace-routing' | rg -n "workspace_update_complete|Workspace update assistant"`
**Result**:
```bash
279:            <input type="checkbox" id="agentWorkspaceUpdateAssistant" value="workspace_update_assistant" checked style="width: 18px; height: 18px; cursor: pointer;">
490:  <script src="/static/js/app.js?v=beat4-workspace-routing"></script>
2695:        log("Workspace update assistant uses inline display");
2795:    case "workspace_update_complete":
2796:      // Workspace update assistant finished - add file summary
```

**Feature: Full demo beat prompt regression**
**Test #1: Text-based LLM prompt suite**
**Status:** PASS
**Code Command**: `python - <<'PY' ... prompt regression suite for cold open and Beats 1-4 ... PY`
**Result**:
```bash
Cold open: PASS :: Yep. You're on camera, audio is clear, and I'm ready.
Beat 1 README tool: PASS :: markdown_assistant with output_path README.md and React/FastAPI/MySQL context.
Beat 1 improvement: PASS :: Polling MySQL won't scale; add Redis pub/sub between FastAPI instances for realtime fanout.
Beat 1 realtime design tool: PASS :: markdown_assistant with output_path realtime_design.md.
Beat 2 fashion: PASS :: Mentions navy shirt/jacket, professional, and late-night coding.
Beat 3 menu: PASS :: Recommends braised vegetables over beef noodle soup, tied to yesterday's ramen and health goals.
Beat 4 todo routing tool: PASS :: workspace_update_assistant with all six handwritten items, including umbrella.
```

**Feature: Tuned video-call cold-open response**
**Test #1: Python syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile server.py prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: CUDA Python environment for ASR and TTS**
**Test #1: Runtime syntax validation**
**Status:** PASS
**Code Command**: `.venv-gpu/bin/python -m py_compile clients/asr.py clients/tts.py server.py config.py && bash -n launch-https.sh && bash -n launch-gpu-dev.sh`
**Result**:
```bash
No output. Commands exited successfully.
```

**Feature: CUDA Python environment for ASR and TTS**
**Test #2: Torch and CTranslate2 CUDA capability**
**Status:** PASS
**Code Command**:
```bash
LD_LIBRARY_PATH=$PWD/.venv-gpu/lib:$LD_LIBRARY_PATH .venv-gpu/bin/python - <<'PY'
import ctranslate2, torch
print('torch', torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))
print('ctranslate2', ctranslate2.__version__, sorted(ctranslate2.get_supported_compute_types('cuda')))
PY
```
**Result**:
```bash
torch 2.11.0+cu130 True NVIDIA GB10
ctranslate2 4.7.1 ['bfloat16', 'float16', 'float32', 'int8', 'int8_bfloat16', 'int8_float16', 'int8_float32']
```

**Feature: CUDA local ASR**
**Test #1: faster-whisper warmup on GPU**
**Status:** PASS
**Code Command**:
```bash
LD_LIBRARY_PATH=$PWD/.venv-gpu/lib:$LD_LIBRARY_PATH HF_HOME=/home/nvidia/hfcache HUGGINGFACE_HUB_CACHE=/home/nvidia/hfcache/hub ASR_MODE=local ASR_DEVICE=cuda ASR_COMPUTE_TYPE=float16 ASR_MODEL=Systran/faster-whisper-small.en .venv-gpu/bin/python - <<'PY'
from config import ASRConfig
from clients.asr import LocalWhisperASR
asr = LocalWhisperASR(ASRConfig())
asr.warmup()
print('asr_device', asr.cfg.device)
print('asr_compute_type', asr.cfg.compute_type)
print('model_loaded', asr._model is not None)
PY
```
**Result**:
```bash
[ASR] Using local faster-whisper (model=Systran/faster-whisper-small.en, device=cuda)
[ASR] Warming up model...
[ASR] CUDA compute types available: {'int8_float16', 'int8_float32', 'float16', 'bfloat16', 'int8_bfloat16', 'float32', 'int8'}
[ASR] Loading model Systran/faster-whisper-small.en on cuda (float16)...
[ASR] Model loaded successfully
[ASR] Warmup complete (965ms)
asr_device cuda
asr_compute_type float16
model_loaded True
```

**Feature: CUDA Kokoro TTS**
**Test #1: Synthesize audio on GPU**
**Status:** PASS
**Code Command**:
```bash
LD_LIBRARY_PATH=$PWD/.venv-gpu/lib:$LD_LIBRARY_PATH HF_HOME=/home/nvidia/hfcache HUGGINGFACE_HUB_CACHE=/home/nvidia/hfcache/hub TTS_DEVICE=cuda TTS_ENGINE=kokoro .venv-gpu/bin/python - <<'PY'
from pathlib import Path
from config import TTSConfig
from clients.tts import create_tts
import torch
out = Path('/tmp/spark_kokoro_cuda_test.wav')
tts = create_tts(TTSConfig())
tts.synth_to_file('Yep. You are on camera, audio is clear, and I am ready.', out)
print('tts_class', type(tts).__name__)
print('torch_cuda', torch.cuda.is_available())
print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')
print('wav_exists', out.exists(), 'bytes', out.stat().st_size if out.exists() else 0)
PY
```
**Result**:
```bash
[TTS] Loading Kokoro pipeline (lang=a, voice=af_bella)...
[TTS] Pipeline loaded on device: cuda
tts_class KokoroTTS
torch_cuda True
device NVIDIA GB10
wav_exists True bytes 171644
```

**Feature: 8445 GPU dev launcher**
**Test #1: Startup reaches HTTPS server with CUDA checks**
**Status:** PASS
**Code Command**: `timeout 35 ./launch-gpu-dev.sh`
**Result**:
```bash
ASR Mode: local
ASR Device: cuda
ASR Compute Type: float16
TTS Overlap: true
Dev Reload: true
Port: 8445 (HTTPS)
CTranslate2 CUDA compute types: ['bfloat16', 'float16', 'float32', 'int8', 'int8_bfloat16', 'int8_float16', 'int8_float32']
Torch CUDA device for TTS: NVIDIA GB10
INFO:     Uvicorn running on https://0.0.0.0:8445 (Press CTRL+C to quit)
INFO:     Application startup complete.
```

**Feature: Venv-local FFmpeg fallback for browser mic audio**
**Test #1: imageio-ffmpeg binary is available to audio decoder**
**Status:** PASS
**Code Command**:
```bash
FFMPEG_BIN="$($PWD/.venv-gpu/bin/python - <<'PY'
import imageio_ffmpeg
print(imageio_ffmpeg.get_ffmpeg_exe())
PY
)"
"$FFMPEG_BIN" -version | sed -n '1,2p'
FFMPEG_PATH="$FFMPEG_BIN" .venv-gpu/bin/python - <<'PY'
from config import FFMPEG_PATH
from audio import check_ffmpeg_available
print('ffmpeg_path', FFMPEG_PATH)
print('available', check_ffmpeg_available())
PY
```
**Result**:
```bash
ffmpeg version 7.0.2-static https://johnvansickle.com/ffmpeg/  Copyright (c) 2000-2024 the FFmpeg developers
built with gcc 8 (Debian 8.3.0-6)
ffmpeg_path /home/nvidia/selena/spark-realtime-chatbot/.venv-gpu/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-aarch64-v7.0.2
available True
```

**Feature: 8445 GPU dev server after environment fix**
**Test #1: Detached server health check**
**Status:** PASS
**Code Command**: `setsid bash -c 'exec ./launch-gpu-dev.sh' > logs/gpu-dev-8445.log 2>&1 < /dev/null & ...; curl -ks https://localhost:8445/health`
**Result**:
```bash
{"status":"ok"}

Startup log confirmed:
FFmpeg: /home/nvidia/selena/spark-realtime-chatbot/.venv-gpu/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-aarch64-v7.0.2
CTranslate2 CUDA compute types: ['bfloat16', 'float16', 'float32', 'int8', 'int8_bfloat16', 'int8_float16', 'int8_float32']
Torch CUDA device for TTS: NVIDIA GB10
[ASR] Loading model Systran/faster-whisper-small.en on cuda (float16)...
[TTS] Pipeline loaded on device: cuda
```

**Feature: Clean menu recommendation wording**
**Test #1: Prompt syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Translate menu items before recommending**
**Test #1: Prompt syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Recommend actual visible menu items**
**Test #1: Prompt syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Menu-grounded private recommendation prompt**
**Test #1: Prompt syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Hard-coded private demo health memory**
**Test #1: Prompt syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Force rear camera preview unmirrored and bust static cache**
**Test #1: JavaScript syntax validation**
**Status:** PASS
**Code Command**: `node --check static/js/app.js`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Force rear camera preview unmirrored and bust static cache**
**Test #2: Served asset verification**
**Status:** PASS
**Code Command**: `curl -ks https://localhost:8443/ | rg -n "styles\\.css|app\\.js" && curl -ks 'https://localhost:8443/static/js/app.js?v=rear-camera-unmirror' | rg -n "exact: facingMode|video\\.style\\.transform|classList.toggle\\('mirrored'" && curl -ks 'https://localhost:8443/static/css/styles.css?v=rear-camera-unmirror' | rg -n "video\\.mirrored|transform: none|scaleX"`
**Result**:
```bash
14:  <link rel="stylesheet" href="/static/css/styles.css?v=rear-camera-unmirror">
486:  <script src="/static/js/app.js?v=rear-camera-unmirror"></script>
1016:      facingMode: useExactFacingMode ? { exact: facingMode } : { ideal: facingMode },
1041:    video.classList.toggle('mirrored', facingMode === 'user');
1042:    video.style.transform = facingMode === 'user' ? 'scaleX(-1)' : 'none';
1313:      transform: none;
1525:      transform: none;
1528:    .video-call-webcam video.mirrored {
1529:      transform: scaleX(-1);
```

**Feature: Rear camera preview is not mirrored**
**Test #1: JavaScript syntax validation**
**Status:** PASS
**Code Command**: `node --check static/js/app.js`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Rear camera preview is not mirrored**
**Test #2: Whitespace validation**
**Status:** PASS
**Code Command**: `git diff --check -- static/css/styles.css static/js/app.js`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Flip video-call camera on mobile**
**Test #1: JavaScript syntax validation**
**Status:** PASS
**Code Command**: `node --check static/js/app.js`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Professional outfit prompt branching**
**Test #1: Prompt syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Refined video-call fashion response wording**
**Test #1: Prompt syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Tuned video-call fashion response**
**Test #1: Prompt syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile prompts.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Stream markdown agent output into workspace file**
**Test #1: Streaming file lifecycle**
**Status:** PASS
**Code Command**:
```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import server

with TemporaryDirectory() as tmp:
    server.WORKSPACE_ROOT = Path(tmp).resolve()
    session = server.VoiceSession.__new__(server.VoiceSession)
    stream_path, relative = session.begin_markdown_workspace_stream(
        'Convert this hand-drawn architecture into a Markdown README for the project.'
    )
    assert relative == 'workspace/README.md'
    assert stream_path.read_text() == ''
    with stream_path.open('a', encoding='utf-8') as f:
        f.write('# Live')
        f.flush()
        assert stream_path.read_text() == '# Live'
        f.write(' README\n')
        f.flush()
    assert stream_path.read_text() == '# Live README\n'
    final_path = session.write_markdown_to_workspace(
        'Convert this hand-drawn architecture into a Markdown README for the project.',
        '# Final README\n'
    )
    assert final_path == relative
    assert stream_path.read_text() == '# Final README\n'
    print(relative)
    print(stream_path.read_text().strip())
PY
```
**Result**:
```bash
workspace/README.md
# Final README
```

**Feature: Persist markdown agent output to workspace/**
**Test #1: Python syntax validation**
**Status:** PASS
**Code Command**: `python -m py_compile server.py prompts.py tools.py`
**Result**:
```bash
No output. Command exited successfully.
```

**Feature: Persist markdown agent output to workspace/**
**Test #2: Workspace path inference and containment**
**Status:** PASS
**Code Command**:
```bash
python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
import server

with TemporaryDirectory() as tmp:
    server.WORKSPACE_ROOT = Path(tmp).resolve()
    session = server.VoiceSession.__new__(server.VoiceSession)
    readme_path = session.write_markdown_to_workspace(
        'Convert this hand-drawn architecture into a Markdown README for the project.',
        '# Demo README\n'
    )
    design_path = session.write_markdown_to_workspace(
        'Sketch the Redis pub/sub realtime fanout design.',
        '# Realtime Design\n'
    )
    escaped_path = session.write_markdown_to_workspace(
        'Unsafe path test',
        '# Safe\n',
        '../outside.md'
    )
    print(readme_path)
    print(design_path)
    print(escaped_path)
    assert readme_path == 'workspace/README.md'
    assert design_path == 'workspace/realtime_design.md'
    assert escaped_path == 'workspace/outside.md'
    assert (Path(tmp) / readme_path).read_text() == '# Demo README\n'
PY
```
**Result**:
```bash
workspace/README.md
workspace/realtime_design.md
workspace/outside.md
```

**Feature: Display saved markdown path in browser**
**Test #1: JavaScript syntax validation**
**Status:** PASS
**Code Command**: `node --check static/js/app.js`
**Result**:
```bash
No output. Command exited successfully.
```
