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
