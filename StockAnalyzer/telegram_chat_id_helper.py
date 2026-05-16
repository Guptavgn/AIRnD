import os
import urllib.request
import json
from dotenv import load_dotenv

load_dotenv()

bot_token = os.getenv('TELEGRAM_BOT_TOKEN')

if not bot_token:
    bot_token = input('Enter your Telegram bot token: ').strip()

if not bot_token:
    print('Telegram bot token is required.')
    exit(1)

url = f'https://api.telegram.org/bot{bot_token}/getUpdates'
print('Requesting Telegram updates to discover chat ID...')

try:
    with urllib.request.urlopen(url, timeout=20) as response:
        body = response.read().decode('utf-8')
        result = json.loads(body)
        if not result.get('ok'):
            print('Telegram API error:', result)
            exit(1)
        updates = result.get('result', [])
        if not updates:
            print('No updates found. Send a message to your bot first, then run this again.')
            exit(0)
        chat_ids = set()
        for update in updates:
            message = update.get('message') or update.get('edited_message')
            if message and 'chat' in message:
                chat_ids.add(message['chat'].get('id'))
        if not chat_ids:
            print('No chat IDs found in updates. Make sure you have messaged your bot.')
        else:
            print('Found Telegram chat IDs:')
            for chat_id in chat_ids:
                print(chat_id)
except Exception as e:
    print('Failed to fetch Telegram updates:', e)
    exit(1)
