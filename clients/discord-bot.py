import base64
import io
import json
import os
import sys
from pathlib import Path

import discord
import requests
import urllib3
from PIL import Image
from faster_whisper import WhisperModel

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Make the project root importable so we can pull in tools.py from clients/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import ALL_TOOLS, _INLINE_DISPATCH

MAX_IMAGE_EDGE = 768  # long-edge px; lower = fewer image tokens
ASR_MODEL = WhisperModel("Systran/faster-whisper-small.en", device="cuda")

# 1. Configuration
TOKEN = os.environ['DISCORD_BOT_TOKEN']
# APPLICATION_URL = 'https://discord.com/oauth2/authorize?client_id=1506326445692026920&permissions=8&integration_type=0&scope=bot' # this link adds the bot to a server
INFERENCE_URL = 'http://localhost:30000/v1/chat/completions'
MODEL_NAME = 'Qwen 3.6 35B A3B'
TOKEN_USAGE_URL = os.environ.get('TOKEN_USAGE_URL', 'https://localhost:8443/api/token_usage')

WRITE_FILE_TOOL = ALL_TOOLS["write_file"]
READ_FILE_TOOL  = ALL_TOOLS["read_file"]
EDIT_HTML_TOOL  = ALL_TOOLS["edit_html"]

ORCHESTRATOR_PROMPT = """You are Claw, my personal AI assistant — a helpful lobster 🦞 — running fully on NVIDIA DGX Spark. 
You handle two kinds of requests. Pick exactly one mode per turn based on the user's message.

=== MODE A: FOOD ORDERING ===
Trigger: user asks what to eat, what to order, or shares a menu photo.
Do not use any tool in this mode.

User Health Context:
- User has high blood pressure diagnosis and needs to avoid salty, oily foods
- Yesterday user had ramen for lunch

User Food Preferences:
- Prefer lightly-prepared dishes (steamed, sautéed) over fried or heavy.
- Prefer dishes with vegetables and lean protein over rich/oily ones.
- User enjoys braised beef, steamed shrimp dumplings, stir-fried vegetables, tofu soup

Response rules:
- NEVER mention the a diagnosis.
- NEVER explicitly mention taste preferences or favorite foods.
- ALWAYS recommend one dish over another (e.g. 'I'd recommend the braised beef over the fried rice because...').
- Frame all recommendations in food-positive language (cleaner, less salty, lighter)
- Recommend dishes from the menu in front of you.
- All answers MUST be in English. NO Chinese characters.
- If the menu is in a non-English language, SILENTLY translate dish names to English and use the English name in your recommendation. Do not mention that you translated.
- NEVER add notes, disclaimers, parentheticals, or meta-commentary about the menu, the language, or your reasoning.
- Keep your response brief with natural flow (1 sentence max, no parentheticals).

GOOD EXAMPLE:
- 'I'd recommend the braised beef instead of the fried rice since it's lower in salt.'
- 'I recommend the steamed shrimp dumplings with a side of stir-fried greens since it's light and low in salt.'

BAD EXAMPLE (do NOT produce):
- 'I'd recommend the steamed shrimp dumplings. (Note: this menu is in Chinese, so I translated the dish names.)'  ← never add a Note or parenthetical
- 'The menu appears to be in Chinese, but I'd recommend...'                                                       ← never reference the menu's language

=== MODE B: EMAIL DRAFTING ===
Trigger: user asks you to draft, write, send, or compose an email or message.

Rules:
- Call the write_file tool with path "workspace/<short-descriptive-slug>.md".
- Write the email as markdown with this structure:
  - `# Subject: <subject line>` as the top-level heading
  - Greeting line (e.g. "Hi team,")
  - Body paragraphs — use **bold** for emphasis and `- ` bullet lists for action items or updates
  - Sign-off (e.g. "Thanks,\n<name>")
- In your chat response, say ONE short sentence acknowledging the request (e.g. "On it - drafting that now.").
- Do NOT include the email body in the chat response.

=== MODE C: EDIT HTML PAGE ===
Trigger: user asks to update, edit, change, or fix an HTML page (headline, button, tagline, subtitle, price, etc.).

Rules:
- First call read_file with the page's path (default "workspace/landing.html"; if the user names a different page like "about.html", use "workspace/about.html") to see the current HTML.
- Then call edit_html with the exact old_text from the file and the new_text the user requested. Only set filename if the user named a non-default page.
- In your chat response, say ONE short sentence acknowledging the change (e.g. "Done - the headline is now X.").
- Do NOT call write_file. Do NOT regenerate the whole page.

GOOD EXAMPLE:
- User: "update the landing page headline to say 'The chip harness for fast prototyping'"
  -> read_file({"path": "workspace/landing.html"})
  -> edit_html({"old_text": "<current headline from the file>", "new_text": "The chip harness for fast prototyping"})
  -> "Done - the headline is now 'The chip harness for fast prototyping.'"

=== FALLBACK ===
For any other request, respond briefly as a helpful assistant. Do not use tools.
"""

# 2. Setup Bot Intents
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# 3. Handle Events
@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    # Ignore messages from any bot (self or others) to prevent loops
    if message.author.bot:
        return

    user_query = message.content.strip()

    # Transcribe any audio attachments and fold into the text prompt
    for att in message.attachments:
        if att.content_type and att.content_type.startswith("audio/"):
            segments, _ = ASR_MODEL.transcribe(io.BytesIO(await att.read()), language="en")
            transcript = " ".join(s.text for s in segments).strip()
            user_query = (user_query + " " + transcript).strip()

    parts = [{"type": "text", "text": user_query}]
    for att in message.attachments:
        if not (att.content_type and att.content_type.startswith("image/")):
            continue
        img = Image.open(io.BytesIO(await att.read())).convert("RGB")
        img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    async with message.channel.typing():
        messages = [
            {"role": "system", "content": ORCHESTRATOR_PROMPT},
            {"role": "user", "content": parts},
        ]
        print(f"\n--- [user] {user_query!r}  (images: {sum(1 for p in parts if p.get('type')=='image_url')})")

        MAX_TOOL_ITERS = 4
        sent_anything = False
        ran_a_tool = False
        for _ in range(MAX_TOOL_ITERS):
            payload = {
                "model": MODEL_NAME,
                "messages": messages,
                "tools": [WRITE_FILE_TOOL, READ_FILE_TOOL, EDIT_HTML_TOOL],
                "max_tokens": 512,
                "stream": False,
                "cache_prompt": True,
            }
            try:
                response = requests.post(INFERENCE_URL, json=payload, timeout=120)
                response.raise_for_status()
                data = response.json()
                msg = data["choices"][0]["message"]
            except Exception as e:
                print(f"--- [error] {e}")
                await message.channel.send(f"Sorry, I couldn't reach my local AI backend ({e}).")
                return

            usage = data.get("usage") or {}
            print(f"--- [usage from llama.cpp] {usage}")
            if usage:
                try:
                    r = requests.post(TOKEN_USAGE_URL, json={
                        "source": "discord",
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    }, timeout=2, verify=False)
                    print(f"--- [token_usage push] status={r.status_code} body={r.text[:200]}")
                except Exception as e:
                    print(f"--- [token_usage push failed] {e}")

            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []
            print(f"--- [model] finish={data['choices'][0].get('finish_reason')}  content={content!r}")
            if tool_calls:
                print(f"--- [model] tool_calls={[(tc['function']['name'], tc['function']['arguments'][:120]) for tc in tool_calls]}")

            # Surface the model's chat text
            if content:
                sent_anything = True
                for i in range(0, len(content), 2000):
                    await message.channel.send(content[i:i+2000])

            # No tools requested -> the model is done
            if not tool_calls:
                break

            # Feed the assistant turn + each tool result back for the next iteration
            ran_a_tool = True
            messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                result = await _INLINE_DISPATCH[name](args)  # JSON string
                try:
                    err = json.loads(result).get("error")
                except json.JSONDecodeError:
                    err = None
                if err:
                    await message.channel.send(f"Tool error: {err}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "name": name,
                    "content": result,
                })

        # Fallback: we did work but the model never produced a closing sentence
        if ran_a_tool and not sent_anything:
            await message.channel.send("Done.")

client.run(TOKEN)