import base64
import io
import os

import discord
import requests
from PIL import Image

MAX_IMAGE_EDGE = 768  # long-edge px; lower = fewer image tokens

# 1. Configuration
TOKEN = os.environ['DISCORD_BOT_TOKEN']
# APPLICATION_URL = 'https://discord.com/oauth2/authorize?client_id=1506326445692026920&permissions=8&integration_type=0&scope=bot' # this link adds the bot to a server
INFERENCE_URL = 'http://localhost:30000/v1/chat/completions'
MODEL_NAME = 'Qwen 3.6 35B A3B'  # Your pulled model

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
    # Ignore messages sent by the bot itself
    if message.author == client.user:
        return

    # Trigger when someone tags the bot
    if client.user in message.mentions:
        user_query = message.content.replace(f'<@!{client.user.id}>', '').strip()

        # You are a helpful assistant for food-ordering decisions.

        # Style rules — follow strictly:
        # - Name 1-2 specific dishes visible in the menu photo.
        # - Give a brief, lightweight reason using only the words "light", "clean", or "balanced".
        # - Never reference what the user ate previously or any personal history.
        # - Never mention a diagnosis or health condition.
        # - Never name a "favorite" food by category — just pick from the menu in front of you.
        # - All answers MUST be in English.
        # - Keep your response to ONE sentence.

        # Hidden preferences (use to bias picks, never cite):
        # - Prefer lightly-prepared dishes (steamed, sautéed) over fried or heavy.
        # - Prefer dishes with vegetables and lean protein over rich/oily ones.

        # GOOD EXAMPLE:
        # "I'd go with the steamed shrimp dumplings and a side of stir-fried bok choy — both are light, clean, and a nicely balanced pick."

        # BAD EXAMPLES (do NOT produce):
        # - "Since you had ramen yesterday, skip the noodles..."   (references past meals)
        # - "Given your love for braised beef, try..."             (names favorites)
        # - "To support your blood pressure..."                    (mentions diagnosis)
        # - "Try the fried rice with shrimp."                      (heavy/oily pick)


        # BAD EXAMPLES:
        # - 'I'd recommend the braised beef since it's lower in salt.' (no comparison to other dishes)
        # - 'I recommend the steamed shrimp dumplings with a side of stir-fried greens as a fresh, lighter choice.' (wordy, no comparison to other dishes)
        # - 'To support your blood pressure...' (mentions diagnosis)
        # - 'I would recommend the braised beef as it is a lighter option compared to other choices and fits your preference for that dish.' (wordy)
        # - 'I suggest the braised beef (紅燒牛肉麵) as it fits your taste preferences while being a cleaner option compared to the fried noodles.' (includes Chinese characters)
        # - 'I'd recommend the steamed shrimp dumplings since they are a light, steamed option that fits your taste preferences better than the heavier noodles or fried items.' (wordy, explicitly names taste preferences)
        # - 'I recommend the Steamed Shrimp Dumplings with a side of stir-fried vegetables since it's a lighter, lower-salt choice compared to the fried items.' (doesn't name a specific copmarison dish, explicitly names taste preferences)

        demo_context = """
        You are a helpful assistant that can answer questions and help with tasks.
        
        If the user asks for advice on food ordering, keep in mind the following:
        
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
        - ALWAYS recommend one dish over another (e.g. 'I'd recommend the braised beef over the fried rice since ...').
        - Frame all recommendations in food-positive language (cleaner, less salty, lighter)
        - Recommend dishes from the menu in front of you.
        - All answers MUST be in English. NO Chinese characters.
        - Keep your response brief with natural flow (1 sentence max). 
        
        GOOD EXAMPLE: 
        - 'I'd recommend the braised beef instead of the fried rice since it's lower in salt.' 
        - 'I recommend the steamed shrimp dumplings with a side of stir-fried greens since it's light and low in salt.'
        """

        prompt = user_query + "\n\n" + demo_context

        parts = [{"type": "text", "text": prompt}]
        for att in message.attachments:
            img = Image.open(io.BytesIO(await att.read())).convert("RGB")
            img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

        # Send a typing indicator while processing
        async with message.channel.typing():

            # Send prompt to local AI (OpenAI-compatible chat/completions shape)
            payload = {
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": parts}],
                "max_tokens": 512,
                "stream": False,
            }

            try:
                response = requests.post(INFERENCE_URL, json=payload, timeout=120)
                response.raise_for_status()
                ai_response = response.json()["choices"][0]["message"]["content"]
            except Exception as e:
                ai_response = f"Sorry, I couldn't reach my local AI backend ({e})."

            # Split and send the response if it exceeds Discord's 2000 character limit
            if len(ai_response) > 2000:
                chunks = [ai_response[i:i+2000] for i in range(0, len(ai_response), 2000)]
                for chunk in chunks:
                    await message.channel.send(chunk)
            else:
                await message.channel.send(ai_response)

client.run(TOKEN)