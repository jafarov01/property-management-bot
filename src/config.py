# FILE: config.py
# ==============================================================================
# UPDATED: Added specific channel IDs for robust routing.
# ==============================================================================
import os
from dotenv import load_dotenv

load_dotenv()

# --- Core Credentials & URLs ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN')
SLACK_SIGNING_SECRET = os.getenv('SLACK_SIGNING_SECRET')
DATABASE_URL = os.getenv('DATABASE_URL')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL') 

# --- Slack Configuration ---
# ID of the user whose posts trigger the bot (e.g., "Conny")
SLACK_USER_ID_OF_LIST_POSTER = os.getenv('SLACK_USER_ID_OF_LIST_POSTER') 
# ID of the channel where check-in lists are posted
SLACK_CHECKIN_CHANNEL_ID = os.getenv('SLACK_CHECKIN_CHANNEL_ID')
# ID of the channel where cleaning lists are posted
SLACK_CLEANING_CHANNEL_ID = os.getenv('SLACK_CLEANING_CHANNEL_ID')

# --- Telegram Configuration ---
TELEGRAM_TARGET_CHAT_ID = os.getenv('TELEGRAM_TARGET_CHAT_ID', "-1002714303997")
TELEGRAM_TOPIC_IDS = {
    "GENERAL": 1,
    "ISSUES": 4,
    "CANCELLATIONS": 3,
    "NEW_BOOKINGS": 2,
}

# --- Validation ---
if not all([
    TELEGRAM_BOT_TOKEN, 
    SLACK_BOT_TOKEN, 
    SLACK_SIGNING_SECRET, 
    DATABASE_URL, 
    GEMINI_API_KEY, 
    WEBHOOK_URL,
    SLACK_CHECKIN_CHANNEL_ID,
    SLACK_CLEANING_CHANNEL_ID
]):
    raise ValueError("A required setting is missing from your .env or config file. Check all tokens, URLs, and channel IDs.")