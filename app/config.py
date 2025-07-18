# FILE: config.py
# ==============================================================================
# UPDATED: Added email credentials to the final validation check.
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
SLACK_USER_ID_OF_LIST_POSTER = os.getenv('SLACK_USER_ID_OF_LIST_POSTER') 
SLACK_USER_ID_OF_SECOND_POSTER = os.getenv('SLACK_USER_ID_OF_SECOND_POSTER')
SLACK_CHECKIN_CHANNEL_ID = os.getenv('SLACK_CHECKIN_CHANNEL_ID')
SLACK_CLEANING_CHANNEL_ID = os.getenv('SLACK_CLEANING_CHANNEL_ID')

# --- Telegram Configuration ---
TELEGRAM_TARGET_CHAT_ID = os.getenv('TELEGRAM_TARGET_CHAT_ID')
TELEGRAM_TOPIC_IDS = {
    "GENERAL": 1,
    "ISSUES": 2,
    "EMAILS": 229, # Make sure this is the correct ID for your #emails topic
}

# --- NEW: Email Watchdog Configuration ---
IMAP_SERVER = os.getenv('IMAP_SERVER', 'imap.gmail.com')
IMAP_USERNAME = os.getenv('IMAP_USERNAME')
IMAP_PASSWORD = os.getenv('IMAP_PASSWORD')

# --- Application Settings ---
TIMEZONE = "Europe/Budapest"

# --- Validation ---
if not all([
    TELEGRAM_BOT_TOKEN, 
    SLACK_BOT_TOKEN, 
    SLACK_SIGNING_SECRET, 
    DATABASE_URL, 
    GEMINI_API_KEY, 
    WEBHOOK_URL,
    SLACK_CHECKIN_CHANNEL_ID,
    SLACK_CLEANING_CHANNEL_ID,
    IMAP_USERNAME, # Added
    IMAP_PASSWORD  # Added
]):
    raise ValueError("A required setting is missing. Check all tokens, URLs, and email credentials.")