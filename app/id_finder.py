
# FILE: id_finder.py
# A robust script to find Telegram Chat and Topic IDs.
# UPDATED: Now explicitly deletes any active webhook before starting.

import requests
import time
import os
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
# Paste the User ID you got from @userinfobot here:
YOUR_USER_ID = "1940785152"
# ---------------------

def delete_webhook():
    """Deletes any existing webhook to enable getUpdates."""
    print("Attempting to delete any existing webhook...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    response = requests.get(url)
    if response.json().get('result'):
        print("✅ Webhook deleted successfully.")
        return True
    else:
        print("⚠️ No webhook was set, or an error occurred. Continuing...")
        return False # Continue even if it fails, might not have been set

def get_updates(offset=None):
    """Gets the latest messages from the Telegram API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {'timeout': 100, 'offset': offset}
    try:
        response = requests.get(url, params=params)
        return response.json()['result']
    except Exception as e:
        # This error will now only happen if there's a real network issue
        print(f"Error getting updates: {e}")
        return []

def send_message(chat_id, text):
    """Sends a message to a specific user."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
    requests.post(url, params=params)

def main():
    """Main function to run the ID finder."""
    if not BOT_TOKEN or "YOUR_TOKEN" in BOT_TOKEN:
        print("ERROR: Please set your TELEGRAM_BOT_TOKEN in the .env file.")
        return
        
    if not YOUR_USER_ID or "PASTE_YOUR_PERSONAL_USER_ID_HERE" in YOUR_USER_ID:
        print("ERROR: Please paste your personal User ID into the YOUR_USER_ID variable in this script.")
        return

    # 1. Delete webhook
    delete_webhook()
    time.sleep(1) # Give Telegram a second to process

    # 2. Clear any pending updates
    print("Clearing old updates...")
    updates = get_updates()
    update_id = updates[-1]['update_id'] + 1 if updates else None
    
    print("\n✅ Bot is now listening. Send a message to your group/topic...")
    send_message(YOUR_USER_ID, "ID Finder Bot is running. Send a message to the target group now.")

    while True:
        updates = get_updates(update_id)
        if updates:
            for update in updates:
                update_id = update['update_id'] + 1
                try:
                    message = update['message']
                    chat_id = message['chat']['id']
                    chat_title = message['chat'].get('title', 'Unknown Group')
                    topic_id = message.get('message_thread_id')
                    
                    report = (
                        f"🎉 *ID Found!* 🎉\n\n"
                        f"Group Name: *{chat_title}*\n"
                        f"Group Chat ID: `{chat_id}`\n\n"
                    )
                    
                    if topic_id:
                        report += f"Topic ID: `{topic_id}`\n\n"
                    else:
                        report += "This message was not in a topic.\n\n"
                        
                    report += "You can now stop this script (Ctrl+C)."
                    
                    send_message(YOUR_USER_ID, report)
                    print("ID report sent to you on Telegram. Exiting.")
                    return

                except KeyError:
                    pass
        time.sleep(1)

if __name__ == '__main__':
    main()