# FILE: run.py
import uvicorn
import logging
import os

if __name__ == "__main__":
    logging.info("Starting Eivissa Operations Bot server...")
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
    
# FILE: config.py
# ==============================================================================
# UPDATED: Added email credentials to the final validation check.
# ==============================================================================
import os
from dotenv import load_dotenv

load_dotenv()

# --- Core Credentials & URLs ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# --- Slack Configuration ---
SLACK_USER_ID_OF_LIST_POSTER = os.getenv("SLACK_USER_ID_OF_LIST_POSTER")
SLACK_USER_ID_OF_SECOND_POSTER = os.getenv("SLACK_USER_ID_OF_SECOND_POSTER")
SLACK_CHECKIN_CHANNEL_ID = os.getenv("SLACK_CHECKIN_CHANNEL_ID")
SLACK_CLEANING_CHANNEL_ID = os.getenv("SLACK_CLEANING_CHANNEL_ID")

# --- Telegram Configuration ---
TELEGRAM_TARGET_CHAT_ID = os.getenv("TELEGRAM_TARGET_CHAT_ID")
TELEGRAM_TOPIC_IDS = {
    "GENERAL": 1,
    "ISSUES": 2,
    "EMAILS": 229,  # Make sure this is the correct ID for your #emails topic
}

# --- NEW: Email Watchdog Configuration ---
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_USERNAME = os.getenv("IMAP_USERNAME")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")

# --- Application Settings ---
TIMEZONE = "Europe/Budapest"

# --- Validation ---
if not all(
    [
        TELEGRAM_BOT_TOKEN,
        SLACK_BOT_TOKEN,
        SLACK_SIGNING_SECRET,
        DATABASE_URL,
        GEMINI_API_KEY,
        WEBHOOK_URL,
        SLACK_CHECKIN_CHANNEL_ID,
        SLACK_CLEANING_CHANNEL_ID,
        IMAP_USERNAME,  # Added
        IMAP_PASSWORD,  # Added
    ]
):
    raise ValueError(
        "A required setting is missing. Check all tokens, URLs, and email credentials."
    )


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from .config import DATABASE_URL  # <-- FIX: Changed to relative import

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# FILE: app/email_parser.py
# VERSION: 8.0 (Production - No Filter)
# UPDATED: The email fetching logic has been updated to capture every single
# unread email in the inbox, removing all previous header-based filtering.
# ==============================================================================
import imaplib
import email
from email.header import decode_header
from typing import List, Dict
import re
import json
import google.generativeai as genai
from .config import GEMINI_API_KEY, IMAP_SERVER, IMAP_USERNAME, IMAP_PASSWORD

# --- AI Configuration ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")


def get_email_body(msg):
    """Extracts the text content from an email message object."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                try:
                    return part.get_payload(decode=True).decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        return part.get_payload(decode=True).decode("latin-1")
                    except:
                        return None
    else:
        try:
            return msg.get_payload(decode=True).decode("utf-8")
        except UnicodeDecodeError:
            try:
                return msg.get_payload(decode=True).decode("latin-1")
            except:
                return None
    return None


async def parse_booking_email_with_ai(email_body: str) -> Dict:
    """Uses AI to parse email content, including a summary, reservation number, and deadline."""
    prompt = f"""
    You are an expert data extraction system for a property management company.

    **Instructions:**
    1.  Read the email and determine a short, descriptive `category` for its main purpose (e.g., "Guest Complaint", "New Booking", "Cancellation", "Service Issue").
    2.  Create a concise, one-sentence `summary` of the core issue or message in the email.
    3.  Extract the following details if they are present:
        - `guest_name`
        - `property_code`
        - `platform` ("Airbnb" or "Booking.com")
        - `reservation_number`
        - `deadline` (e.g., "respond before", "within 48 hours", or a specific date).
    4.  If a field is not present, use the value `null`.
    5.  You MUST return a single, valid JSON object.

    ---
    **Email content to parse now:**
    {email_body[:4000]}
    ---
    """
    try:
        response = await model.generate_content_async(prompt)
        # Use regex to find a JSON object within the response text
        match = re.search(r"\{.*\}", response.text, re.DOTALL)
        if not match:
            return {
                "category": "Parsing Failed",
                "summary": "AI response did not contain a valid JSON object.",
            }

        cleaned_response = match.group(0)
        return json.loads(cleaned_response)
    except Exception as e:
        return {
            "category": "Parsing Exception",
            "summary": f"An exception occurred: {e}",
        }


def fetch_unread_emails() -> List[Dict]:
    """
    Connects to the IMAP server and fetches ALL unread emails without any filtering.
    """
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")

        # Search for all unseen emails
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return []

        all_unread_emails = []
        for num in messages[0].split():
            try:
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK":
                    continue

                msg = email.message_from_bytes(msg_data[0][1])

                # --- NO FILTER APPLIED ---
                # Process every fetched email. The previous header check has been removed.
                body = get_email_body(msg)
                if body:
                    all_unread_emails.append({"body": body})

            finally:
                # Always mark the email as read to prevent infinite loops, even if processing fails.
                mail.store(num, "+FLAGS", "\\Seen")

        mail.logout()
        return all_unread_emails
    except Exception as e:
        print(f"Failed to fetch emails: {e}")
        return []

# FILE: header_inspector.py
# ==============================================================================
# A self-contained diagnostic tool to fetch and print email headers.
# This version does NOT import from config.py to avoid validation errors.
# ==============================================================================
import imaplib
import email
from email.header import decode_header
import os
from dotenv import load_dotenv

# --- Load environment variables directly ---
load_dotenv()
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_USERNAME = os.getenv("IMAP_USERNAME")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD")


def inspect_latest_email_headers():
    """Connects to the IMAP server and prints the headers of the latest unread email."""
    if not all([IMAP_SERVER, IMAP_USERNAME, IMAP_PASSWORD]):
        print(
            "❌ ERROR: Please ensure IMAP_SERVER, IMAP_USERNAME, and IMAP_PASSWORD are set in your .env file."
        )
        return

    try:
        print("Connecting to email server...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(IMAP_USERNAME, IMAP_PASSWORD)
        mail.select("inbox")
        print("✅ Connection successful.")

        # Search for all unread emails
        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            print(
                "\nNo unread emails found. Please have an email forwarded now and then re-run this script."
            )
            mail.logout()
            return

        # Get the latest email ID from the list
        latest_email_id = messages[0].split()[-1]
        print(f"Found latest unread email with ID: {latest_email_id.decode()}")

        # Fetch the full message (RFC822)
        status, msg_data = mail.fetch(latest_email_id, "(RFC822)")
        if status != "OK":
            print("Failed to fetch email content.")
            mail.logout()
            return

        msg = email.message_from_bytes(msg_data[0][1])

        print("\n--- HEADERS FOR LATEST UNREAD EMAIL ---")
        for header, value in msg.items():
            # Decode the header value to handle different character sets
            decoded_value = ""
            try:
                decoded_parts = decode_header(value)
                for part, charset in decoded_parts:
                    if isinstance(part, bytes):
                        # If a charset is specified, use it; otherwise, guess
                        decoded_value += part.decode(charset or "utf-8", "ignore")
                    else:
                        decoded_value += str(part)
            except Exception:
                decoded_value = value  # Fallback to raw value if decoding fails

            print(f"{header}: {decoded_value}")
        print("---------------------------------------\n")

        print("✅ Inspection complete.")
        print("IMPORTANT: This email has NOT been marked as read.")

        mail.logout()

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    inspect_latest_email_headers()

# FILE: id_finder.py
# A robust script to find Telegram Chat and Topic IDs.
# UPDATED: Now explicitly deletes any active webhook before starting.

import requests
import time
import os
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Paste the User ID you got from @userinfobot here:
YOUR_USER_ID = "1940785152"
# ---------------------


def delete_webhook():
    """Deletes any existing webhook to enable getUpdates."""
    print("Attempting to delete any existing webhook...")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    response = requests.get(url)
    if response.json().get("result"):
        print("✅ Webhook deleted successfully.")
        return True
    else:
        print("⚠️ No webhook was set, or an error occurred. Continuing...")
        return False  # Continue even if it fails, might not have been set


def get_updates(offset=None):
    """Gets the latest messages from the Telegram API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 100, "offset": offset}
    try:
        response = requests.get(url, params=params)
        return response.json()["result"]
    except Exception as e:
        # This error will now only happen if there's a real network issue
        print(f"Error getting updates: {e}")
        return []


def send_message(chat_id, text):
    """Sends a message to a specific user."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, params=params)


def main():
    """Main function to run the ID finder."""
    if not BOT_TOKEN or "YOUR_TOKEN" in BOT_TOKEN:
        print("ERROR: Please set your TELEGRAM_BOT_TOKEN in the .env file.")
        return

    if not YOUR_USER_ID or "PASTE_YOUR_PERSONAL_USER_ID_HERE" in YOUR_USER_ID:
        print(
            "ERROR: Please paste your personal User ID into the YOUR_USER_ID variable in this script."
        )
        return

    # 1. Delete webhook
    delete_webhook()
    time.sleep(1)  # Give Telegram a second to process

    # 2. Clear any pending updates
    print("Clearing old updates...")
    updates = get_updates()
    update_id = updates[-1]["update_id"] + 1 if updates else None

    print("\n✅ Bot is now listening. Send a message to your group/topic...")
    send_message(
        YOUR_USER_ID,
        "ID Finder Bot is running. Send a message to the target group now.",
    )

    while True:
        updates = get_updates(update_id)
        if updates:
            for update in updates:
                update_id = update["update_id"] + 1
                try:
                    message = update["message"]
                    chat_id = message["chat"]["id"]
                    chat_title = message["chat"].get("title", "Unknown Group")
                    topic_id = message.get("message_thread_id")

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


if __name__ == "__main__":
    main()

# FILE: app/main.py
import logging
import sys
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Depends  # <-- FIX: Import Depends
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from sqlalchemy.orm import Session
from sqlalchemy import text
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from . import config, models, telegram_client
from .database import engine, SessionLocal, get_db
from . import telegram_handlers
from . import slack_handler as slack_processor
from .scheduled_tasks import (
    scheduler, daily_midnight_task, daily_briefing_task,
    check_emails_task, email_reminder_task, check_pending_relocations_task
)
from .utils.db_manager import db_session_manager

# --- Configure Logging ---
handler = logging.StreamHandler(sys.stdout)
handler.flush = sys.stdout.flush
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[handler]
)

# --- Database & Application Instances ---
models.Base.metadata.create_all(bind=engine)
slack_app = AsyncApp(token=config.SLACK_BOT_TOKEN, signing_secret=config.SLACK_SIGNING_SECRET)
telegram_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
slack_handler = AsyncSlackRequestHandler(slack_app)

# --- Global Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs errors and sends a notification to the ISSUES topic."""
    logging.error("Exception caught by global error handler", exc_info=context.error)
    error_message = (
        f"🚨 *An unexpected error occurred*\n\n"
        f"*Type:* `{type(context.error).__name__}`\n"
        f"*Error:* `{context.error}`\n\n"
        f"Details have been logged for review."
    )
    # Ensure bot instance is available for sending message
    if context.bot:
        await telegram_client.send_telegram_message(context.bot, error_message, topic_name="ISSUES")

# --- Application Lifespan (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles application startup and shutdown events."""
    bot = telegram_app.bot
    # Schedule all jobs, passing the bot instance to tasks that need it

    scheduler.add_job(daily_midnight_task, 'cron', hour=0, minute=5, id="midnight_cleaner", replace_existing=True)  # FIX: args removed
    scheduler.add_job(daily_briefing_task, 'cron', hour=10, minute=0, args=["Morning"], id="morning_briefing", replace_existing=True)  # FIX: bot arg removed
    scheduler.add_job(daily_briefing_task, 'cron', hour=22, minute=0, args=["Evening"], id="evening_briefing", replace_existing=True)  # FIX: bot arg removed
    scheduler.add_job(check_emails_task, 'interval', minutes=5, id="email_checker", replace_existing=True)  # FIX: args removed
    scheduler.add_job(email_reminder_task, 'interval', minutes=10, id="email_reminder", replace_existing=True)  # FIX: args removed
    scheduler.add_job(check_pending_relocations_task, 'cron', hour=12, minute=0, id="relocation_checker", replace_existing=True)  # FIX: args removed
    scheduler.start()
    logging.info("APScheduler started with all tasks scheduled.")
    
    await telegram_app.initialize()
    await telegram_app.start()
    webhook_url = f"{config.WEBHOOK_URL}/telegram/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url)
    logging.info(f"Telegram webhook set to: {webhook_url}")
    
    yield
    
    await telegram_app.stop()
    await telegram_app.shutdown()
    scheduler.shutdown()
    logging.info("Telegram webhook deleted and scheduler shut down.")

# --- FastAPI App Initialization ---
app = FastAPI(lifespan=lifespan)

# --- Register Telegram Handlers ---
# A loop can simplify handler registration
command_mapping = {
    "help": telegram_handlers.help_command,
    "status": telegram_handlers.status_command,
    "check": telegram_handlers.check_command,
    "occupied": telegram_handlers.occupied_command,
    "available": telegram_handlers.available_command,
    "pending_cleaning": telegram_handlers.pending_cleaning_command,
    "relocate": telegram_handlers.relocate_command,
    "rename_property": telegram_handlers.rename_property_command,
    "set_clean": telegram_handlers.set_clean_command,
    "early_checkout": telegram_handlers.early_checkout_command,
    "cancel_booking": telegram_handlers.cancel_booking_command,
    "edit_booking": telegram_handlers.edit_booking_command,
    "log_issue": telegram_handlers.log_issue_command,
    "block_property": telegram_handlers.block_property_command,
    "unblock_property": telegram_handlers.unblock_property_command,
    "booking_history": telegram_handlers.booking_history_command,
    "find_guest": telegram_handlers.find_guest_command,
    "daily_revenue": telegram_handlers.daily_revenue_command,
    "relocations": telegram_handlers.relocations_command,
}
for command, handler_func in command_mapping.items():
    telegram_app.add_handler(CommandHandler(command, handler_func))

telegram_app.add_handler(CallbackQueryHandler(telegram_handlers.button_callback_handler))
telegram_app.add_error_handler(error_handler)

# --- Register Slack Handler ---
@slack_app.event("message")
async def handle_message_events(body: dict, ack):
    """Delegates Slack message events to the dedicated processor."""
    await ack()
    asyncio.create_task(slack_processor.process_slack_message(payload=body, bot=telegram_app.bot))

# --- API Endpoints ---

@app.get("/_secret_migration_v7_expand_alert_fields")
async def perform_capacity_migration(db: Session = Depends(get_db)):
    """
    A temporary, one-time endpoint to proactively increase the size of several
    text columns in the email_alerts table to prevent future truncation errors.
    """
    try:
        # A single transaction to alter all required columns
        sql_commands = [
            "ALTER TABLE email_alerts ALTER COLUMN property_code TYPE VARCHAR(1024);",
            "ALTER TABLE email_alerts ALTER COLUMN reservation_number TYPE VARCHAR(1024);",
            "ALTER TABLE email_alerts ALTER COLUMN deadline TYPE VARCHAR(1024);"
        ]
        
        for command in sql_commands:
            db.execute(text(command))
        
        db.commit()
        
        logging.info("Capacity migration successful: email_alerts columns expanded.")
        return {"status": "success", "message": "Migration applied: 'email_alerts' columns for property_code, reservation_number, and deadline were expanded."}
    except Exception as e:
        logging.error(f"Migration v7 failed: {e}")
        return {"status": "error", "message": str(e)}, 500


@app.get("/")
async def health_check():
    """Provides a simple health check endpoint."""
    return {"status": "ok", "message": "Eivissa Operations Bot is alive!"}

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    """Handles incoming webhooks from Telegram."""
    await telegram_app.process_update(Update.de_json(await req.json(), telegram_app.bot))
    return Response(status_code=200)

@app.post("/slack/events")
async def slack_events_endpoint(req: Request):
    """Handles incoming events from the Slack Events API."""
    return await slack_handler.handle(req)

# FILE: app/models.py
# ==============================================================================
# VERSION: 5.0 (Production)
# UPDATED: Added `reminders_sent` column to EmailAlert to support the new
# two-reminder logic without misusing the `handled_at` column.
# ==============================================================================
from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    ForeignKey,
    Text,
    DateTime,
    BigInteger,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class Property(Base):
    __tablename__ = "properties"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    status = Column(String(50), default="AVAILABLE", nullable=False, index=True)
    notes = Column(Text, nullable=True)
    bookings = relationship(
        "Booking", back_populates="property", cascade="all, delete-orphan"
    )
    issues = relationship(
        "Issue", back_populates="property", cascade="all, delete-orphan"
    )


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    property_code = Column(String(50), index=True, nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True)
    guest_name = Column(String(1024), nullable=False)
    platform = Column(String(255))
    checkin_date = Column(Date, nullable=False, index=True)
    checkout_date = Column(Date, index=True, nullable=True)
    due_payment = Column(String(255))
    status = Column(String(50), default="Active", index=True)
    property = relationship("Property", back_populates="bookings")


class Issue(Base):
    __tablename__ = "issues"
    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    reported_at = Column(Date, server_default=func.now(), nullable=False)
    description = Column(Text, nullable=False)
    is_resolved = Column(String(50), default="No", nullable=False)
    property = relationship("Property", back_populates="issues")


class Relocation(Base):
    __tablename__ = "relocations"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    guest_name = Column(String(1024), nullable=False)
    original_property_code = Column(String(50), nullable=False)
    new_property_code = Column(String(50), nullable=False)
    relocated_at = Column(DateTime(timezone=True), server_default=func.now())
    booking = relationship("Booking")


class EmailAlert(Base):
    __tablename__ = "email_alerts"
    id = Column(Integer, primary_key=True, index=True)
    telegram_message_id = Column(BigInteger, nullable=True, index=True)
    category = Column(String(255), nullable=False)
    status = Column(String(50), default="OPEN", nullable=False, index=True)
    handled_by = Column(String(1024), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    handled_at = Column(DateTime(timezone=True), nullable=True)
    reminders_sent = Column(Integer, default=0, nullable=False)  # New column

    # --- Columns to store parsed data ---
    summary = Column(Text, nullable=True)
    guest_name = Column(String(1024), nullable=True)
    property_code = Column(String(1024), nullable=True)
    platform = Column(String(255), nullable=True)
    reservation_number = Column(String(255), nullable=True)
    deadline = Column(String(255), nullable=True)

# FILE: app/scheduled_tasks.py
# ==============================================================================
# VERSION: 5.0
# UPDATED: All task functions have been refactored to remove the 'bot' object
# from their arguments to prevent PicklingError with the SQLAlchemyJobStore.
# Each task now creates its own Bot instance when needed.
# ==============================================================================
import logging
import datetime
from sqlalchemy.orm import Session
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from . import config, email_parser, models, telegram_client
from .utils.db_manager import db_session_manager

# --- Scheduler Instance ---
jobstores = {"default": SQLAlchemyJobStore(url=config.DATABASE_URL)}
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=config.TIMEZONE)

# --- Scheduled Task Functions ---


@db_session_manager
async def set_properties_to_available(
    property_codes: list, reason: str, *, db: Session
):
    """
    Takes a list of property codes and sets their status to AVAILABLE.
    Sends a summary message to Telegram.
    """
    if not property_codes:
        logging.info(f"Task '{reason}': No properties to make available.")
        return

    try:
        db.query(models.Property).filter(
            models.Property.code.in_(property_codes),
            models.Property.status == "PENDING_CLEANING",
        ).update({"status": "AVAILABLE"}, synchronize_session=False)
        db.commit()

        summary_text = (
            f"{reason}\n\n"
            f"🧹 The following {len(property_codes)} properties have been cleaned and are now *AVAILABLE*:\n\n"
            f"`{', '.join(sorted(property_codes))}`"
        )

        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        await telegram_client.send_telegram_message(
            bot, summary_text, topic_name="GENERAL"
        )
        logging.info(
            f"Task '{reason}': Set {len(property_codes)} properties to AVAILABLE."
        )
    except Exception as e:
        logging.error(f"Error during '{reason}' task", exc_info=e)
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        await telegram_client.send_telegram_message(
            bot, f"🚨 Error in scheduled task '{reason}': {e}", topic_name="ISSUES"
        )


@db_session_manager
async def check_pending_relocations_task(*, db: Session):
    """Sends a daily reminder for unresolved guest relocations."""
    logging.info("Running daily check for unresolved relocations...")
    try:
        threshold = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=6
        )

        unresolved_bookings = (
            db.query(models.Booking)
            .filter(
                models.Booking.status == "PENDING_RELOCATION",
                models.Booking.created_at <= threshold,
            )
            .all()
        )

        if unresolved_bookings:
            logging.warning(
                f"Found {len(unresolved_bookings)} unresolved relocations. Sending alert."
            )
            bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
            alert_text = telegram_client.format_unresolved_relocations_alert(
                unresolved_bookings
            )
            await telegram_client.send_telegram_message(
                bot, alert_text, topic_name="ISSUES"
            )
        else:
            logging.info("No unresolved relocations found.")

    except Exception as e:
        logging.error("Critical error in check_pending_relocations_task.", exc_info=e)


@db_session_manager
async def check_emails_task(*, db: Session):
    """Periodically fetches and processes unread emails."""
    logging.info("Running email check...")
    try:
        unread_emails = email_parser.fetch_unread_emails()
        if not unread_emails:
            return

        logging.info(f"Found {len(unread_emails)} new emails to process.")
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        for email_data in unread_emails:
            try:
                parsed_data = await email_parser.parse_booking_email_with_ai(
                    email_data["body"]
                )

                if parsed_data and parsed_data.get("category") not in [
                    "Parsing Failed",
                    "Parsing Exception",
                ]:
                    new_alert = models.EmailAlert(
                        category=parsed_data.get("category", "Uncategorized"),
                        summary=parsed_data.get("summary"),
                        guest_name=parsed_data.get("guest_name"),
                        property_code=parsed_data.get("property_code"),
                        platform=parsed_data.get("platform"),
                        reservation_number=parsed_data.get("reservation_number"),
                        deadline=parsed_data.get("deadline"),
                    )
                    db.add(new_alert)
                    db.commit()

                    notification_text, reply_markup = (
                        telegram_client.format_email_notification(new_alert)
                    )
                    sent_message = await telegram_client.send_telegram_message(
                        bot,
                        notification_text,
                        topic_name="EMAILS",
                        reply_markup=reply_markup,
                    )

                    if sent_message:
                        new_alert.telegram_message_id = sent_message.message_id
                        db.commit()
                else:
                    logging.warning(
                        f"AI parsing failed. Reason: {parsed_data.get('summary')}"
                    )
                    failure_summary = parsed_data.get(
                        "summary", "No summary provided by parser."
                    )

                    failed_alert = models.EmailAlert(
                        category="PARSING_FAILED",
                        summary=failure_summary,
                        status="HANDLED",
                    )
                    db.add(failed_alert)
                    db.commit()

                    alert_text = telegram_client.format_parsing_failure_alert(
                        failure_summary
                    )
                    await telegram_client.send_telegram_message(
                        bot, alert_text, topic_name="ISSUES"
                    )

            except Exception as e:
                logging.error(f"Failed to process a single email.", exc_info=e)
                db.rollback()
    except Exception as e:
        logging.error(f"Critical error in check_emails_task.", exc_info=e)


@db_session_manager
async def email_reminder_task(*, db: Session):
    """
    Checks for open email alerts and sends a maximum of two reminders.
    """
    logging.info("Checking for open email alerts for reminders...")
    now = datetime.datetime.now(datetime.timezone.utc)

    alerts_to_check = (
        db.query(models.EmailAlert)
        .filter(
            models.EmailAlert.status == "OPEN", models.EmailAlert.reminders_sent < 2
        )
        .all()
    )

    if not alerts_to_check:
        return

    reminder_text = telegram_client.format_email_reminder()
    alerts_reminded = 0

    for alert in alerts_to_check:
        should_remind = False
        if alert.reminders_sent == 0:
            if now >= alert.created_at + datetime.timedelta(minutes=10):
                should_remind = True
        elif alert.reminders_sent == 1:
            if now >= alert.created_at + datetime.timedelta(minutes=20):
                should_remind = True

        if should_remind:
            try:
                bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
                await bot.send_message(
                    chat_id=config.TELEGRAM_TARGET_CHAT_ID,
                    text=reminder_text,
                    message_thread_id=config.TELEGRAM_TOPIC_IDS.get("EMAILS"),
                    reply_to_message_id=alert.telegram_message_id,
                    parse_mode="Markdown",
                )
                alert.reminders_sent += 1
                db.commit()
                alerts_reminded += 1
            except Exception as e:
                logging.error(
                    f"Could not send reminder for alert {alert.id}", exc_info=e
                )
                db.rollback()

    if alerts_reminded > 0:
        logging.info(f"Sent {alerts_reminded} email reminders.")


async def send_checkout_reminder(
    guest_name: str, property_code: str, checkout_date: str
):
    """Sends a high-priority checkout reminder for a relocated guest."""
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    report = telegram_client.format_checkout_reminder_alert(
        guest_name, property_code, checkout_date
    )
    await telegram_client.send_telegram_message(bot, report, topic_name="ISSUES")
    logging.info(f"Sent checkout reminder for {guest_name} in {property_code}.")


@db_session_manager
async def daily_briefing_task(time_of_day: str, *, db: Session):
    """Sends a daily status briefing to the GENERAL topic."""
    logging.info(f"Running {time_of_day} briefing...")
    occupied = (
        db.query(models.Property).filter(models.Property.status == "OCCUPIED").count()
    )
    pending = (
        db.query(models.Property)
        .filter(models.Property.status == "PENDING_CLEANING")
        .count()
    )
    maintenance = (
        db.query(models.Property)
        .filter(models.Property.status == "MAINTENANCE")
        .count()
    )
    available = (
        db.query(models.Property).filter(models.Property.status == "AVAILABLE").count()
    )
    report = telegram_client.format_daily_briefing(
        time_of_day, occupied, pending, maintenance, available
    )
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    await telegram_client.send_telegram_message(bot, report, topic_name="GENERAL")


@db_session_manager
async def daily_midnight_task(*, db: Session):
    """Sets all PENDING_CLEANING properties to AVAILABLE for the new day."""
    logging.info("Running midnight task...")
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    try:
        props_to_make_available = (
            db.query(models.Property)
            .filter(models.Property.status == "PENDING_CLEANING")
            .all()
        )
        if not props_to_make_available:
            logging.info("Midnight Task: No properties were pending cleaning.")
            return
        prop_codes = [prop.code for prop in props_to_make_available]
        for prop in props_to_make_available:
            prop.status = "AVAILABLE"
        db.commit()
        summary_text = (
            f"Automated Midnight Task (00:05 Local Time)\n\n"
            f"🧹 The following {len(prop_codes)} properties have been cleaned and are now *AVAILABLE* for the new day:\n\n"
            f"`{', '.join(sorted(prop_codes))}`"
        )
        await telegram_client.send_telegram_message(
            bot, summary_text, topic_name="GENERAL"
        )
        logging.info(f"Midnight Task: Set {len(prop_codes)} properties to AVAILABLE.")
    except Exception as e:
        logging.error("Error during midnight task", exc_info=e)
        await telegram_client.send_telegram_message(
            bot, f"🚨 Error in scheduled midnight task: {e}", topic_name="ISSUES"
        )

# FILE: app/slack_handler.py
import logging
import time
import datetime
import pytz
from difflib import get_close_matches
from sqlalchemy.orm import Session
from telegram import Bot

from . import config, slack_parser, models, telegram_client
from .utils.db_manager import db_session_manager
from .scheduled_tasks import scheduler, set_properties_to_available


@db_session_manager
async def process_slack_message(payload: dict, bot: Bot, *, db: Session):
    """
    Parses and processes messages from designated Slack channels to update the database.
    """
    try:
        event = payload.get("event", {})
        # Ignore messages from bots or without a user ID
        if "user" not in event:
            return

        user_id = event.get("user")
        # Process messages only from the designated users
        authorized_user_ids = [
            config.SLACK_USER_ID_OF_LIST_POSTER,
            config.SLACK_USER_ID_OF_SECOND_POSTER,
        ]
        if user_id not in authorized_user_ids:
            return

        message_text = event.get("text", "")
        channel_id = event.get("channel")
        message_ts = float(event.get("ts", time.time()))
        list_date_str = datetime.date.fromtimestamp(message_ts).isoformat()

        logging.info(
            f"MESSAGE RECEIVED from {user_id} in channel {channel_id}: {message_text[:50]}..."
        )

        all_prop_codes = [p.code for p in db.query(models.Property.code).all()]

        # --- Handle 'great reset' command for system initialization ---
        if "great reset" in message_text.lower():
            logging.warning(
                "'great reset' command detected. Wiping and reseeding the database."
            )
            # Remove all scheduled checkout reminders
            for job in scheduler.get_jobs():
                if job.id.startswith("checkout_reminder_"):
                    job.remove()
            # Cascade delete is configured in models, so this will clear related bookings/issues
            db.query(models.Property).delete()
            db.query(models.EmailAlert).delete()
            db.query(models.Relocation).delete()
            db.commit()

            # Seed the database with properties from the message
            properties_to_seed = await slack_parser.parse_cleaning_list_with_ai(
                message_text
            )
            count = 0
            for prop_code in properties_to_seed:
                if (
                    prop_code
                    and prop_code != "N/A"
                    and not db.query(models.Property)
                    .filter(models.Property.code == prop_code)
                    .first()
                ):
                    db.add(models.Property(code=prop_code, status="AVAILABLE"))
                    count += 1
            db.commit()
            await telegram_client.send_telegram_message(
                bot,
                f"✅ *System Initialized*\n\nSuccessfully seeded the database with `{count}` properties.",
                topic_name="GENERAL",
            )
            return

        # --- Handle Check-in Lists ---
        if channel_id == config.SLACK_CHECKIN_CHANNEL_ID:
            new_bookings_data = await slack_parser.parse_checkin_list_with_ai(
                message_text, list_date_str
            )
            processed_bookings = []
            for booking_data in new_bookings_data:
                try:
                    prop_code = booking_data["property_code"]
                    guest_name = booking_data["guest_name"]

                    if guest_name in ["N/A", "Unknown Guest"] or prop_code == "UNKNOWN":
                        logging.warning(
                            f"Skipping booking for {prop_code} due to missing guest name or code."
                        )
                        continue

                    if prop_code not in all_prop_codes:
                        suggestions = get_close_matches(
                            prop_code, all_prop_codes, n=3, cutoff=0.7
                        )
                        original_line = next(
                            (
                                line
                                for line in message_text.split("\n")
                                if line.strip().startswith(prop_code)
                            ),
                            message_text,
                        )
                        alert_text = telegram_client.format_invalid_code_alert(
                            prop_code, original_line, suggestions
                        )
                        await telegram_client.send_telegram_message(
                            bot, alert_text, topic_name="ISSUES"
                        )
                        continue

                    prop = (
                        db.query(models.Property)
                        .filter(models.Property.code == prop_code)
                        .with_for_update()
                        .first()
                    )

                    if prop.status != "AVAILABLE":
                        if prop.status == "OCCUPIED":
                            first_booking = (
                                db.query(models.Booking)
                                .filter(
                                    models.Booking.property_id == prop.id,
                                    models.Booking.status == "Active",
                                )
                                .order_by(models.Booking.id.desc())
                                .first()
                            )
                            booking_data["status"] = "PENDING_RELOCATION"
                            second_booking = models.Booking(
                                **booking_data, property_id=prop.id
                            )
                            db.add(second_booking)
                            db.commit()
                            alert_text, reply_markup = (
                                telegram_client.format_conflict_alert(
                                    prop.code, first_booking, second_booking
                                )
                            )
                            await telegram_client.send_telegram_message(
                                bot,
                                alert_text,
                                topic_name="ISSUES",
                                reply_markup=reply_markup,
                            )
                        else:
                            booking_data["status"] = "PENDING_RELOCATION"
                            failed_booking = models.Booking(
                                **booking_data, property_id=prop.id
                            )
                            db.add(failed_booking)
                            db.commit()
                            alert_text, reply_markup = (
                                telegram_client.format_checkin_error_alert(
                                    property_code=prop_code,
                                    new_guest=booking_data["guest_name"],
                                    prop_status=prop.status,
                                    maintenance_notes=prop.notes,
                                )
                            )
                            await telegram_client.send_telegram_message(
                                bot,
                                alert_text,
                                topic_name="ISSUES",
                                reply_markup=reply_markup,
                            )
                        continue

                    prop.status = "OCCUPIED"
                    db_booking = models.Booking(property_id=prop.id, **booking_data)
                    db.add(db_booking)
                    db.flush()
                    processed_bookings.append(db_booking)
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logging.error(
                        f"Error processing a single check-in line: {booking_data}",
                        exc_info=e,
                    )
                    await telegram_client.send_telegram_message(
                        bot,
                        f"⚠️ Failed to process one line of the check-in list: `{booking_data}`. Please check it manually.",
                        topic_name="ISSUES",
                    )

            if processed_bookings:
                summary_text = telegram_client.format_daily_list_summary(
                    processed_bookings, [], [], list_date_str
                )
                await telegram_client.send_telegram_message(
                    bot, summary_text, topic_name="GENERAL"
                )

        # --- Handle Cleaning Lists ---
        elif channel_id == config.SLACK_CLEANING_CHANNEL_ID:
            properties_to_process = await slack_parser.parse_cleaning_list_with_ai(
                message_text
            )
            success_codes = []
            warnings = []
            for prop_code in properties_to_process:
                prop = (
                    db.query(models.Property)
                    .filter(models.Property.code == prop_code)
                    .first()
                )
                if not prop:
                    warnings.append(
                        f"`{prop_code}`: Code not found in database (check for typo)."
                    )
                    continue

                if prop.status == "OCCUPIED":
                    prop.status = "PENDING_CLEANING"
                    booking_to_update = (
                        db.query(models.Booking)
                        .filter(
                            models.Booking.property_id == prop.id,
                            models.Booking.status == "Active",
                        )
                        .order_by(models.Booking.id.desc())
                        .first()
                    )
                    if booking_to_update:
                        booking_to_update.checkout_date = datetime.date.fromisoformat(
                            list_date_str
                        ) + datetime.timedelta(days=1)
                        booking_to_update.status = "Departed"
                    success_codes.append(prop.code)
                else:
                    warnings.append(
                        f"`{prop_code}`: Not processed, status was already `{prop.status}`."
                    )
            db.commit()
            receipt_message = telegram_client.format_cleaning_list_receipt(
                success_codes, warnings
            )
            await telegram_client.send_telegram_message(
                bot, receipt_message, topic_name="GENERAL"
            )

            # --- Dynamic Scheduling Logic for Late Posts ---
            if success_codes:
                budapest_tz = pytz.timezone(config.TIMEZONE)
                now_budapest = datetime.datetime.now(budapest_tz)

                if now_budapest.hour >= 0 and now_budapest.minute > 5:
                    # Query for ALL properties that are currently pending cleaning
                    all_pending_props = (
                        db.query(models.Property.code)
                        .filter(models.Property.status == "PENDING_CLEANING")
                        .all()
                    )
                    all_pending_codes = [code for code, in all_pending_props]

                    if not all_pending_codes:
                        logging.info(
                            "Late cleaning list detected, but no properties are pending cleaning."
                        )
                        return

                    run_time = now_budapest + datetime.timedelta(minutes=15)
                    job_id = f"late_cleaning_{now_budapest.strftime('%Y%m%d_%H%M%S')}"

                    # Schedule a job to clean ALL pending properties
                    scheduler.add_job(
                        set_properties_to_available,
                        "date",
                        run_date=run_time,
                        args=[
                            all_pending_codes,
                            f"On-Demand Cleaning Task ({now_budapest.strftime('%H:%M')})",
                        ],
                        id=job_id,
                    )
                    logging.info(
                        f"Late cleaning list detected. Scheduled task '{job_id}' to clean all {len(all_pending_codes)} pending properties at {run_time.strftime('%H:%M:%S')}."
                    )

                    # Update the confirmation message to reflect the new logic
                    schedule_confirm_msg = (
                        f"⚠️ *Late Cleaning List Detected*\n\n"
                        f"A task has been scheduled to mark all *{len(all_pending_codes)} pending properties* as `AVAILABLE` in 15 minutes (at approx. {run_time.strftime('%H:%M')})."
                    )
                    await telegram_client.send_telegram_message(
                        bot, schedule_confirm_msg, topic_name="GENERAL"
                    )

    except Exception as e:
        db.rollback()
        logging.critical("CRITICAL ERROR IN SLACK PROCESSOR", exc_info=e)
        await telegram_client.send_telegram_message(
            bot,
            f"🚨 A critical error occurred in the Slack message processor: `{e}`. Please review the logs.",
            topic_name="ISSUES",
        )

# FILE: slack_parser.py
# ==============================================================================
from typing import List, Dict
import datetime
import json
import re
import google.generativeai as genai
from .config import GEMINI_API_KEY  # <-- FIX: Changed to relative import

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")


async def parse_checkin_list_with_ai(
    message_text: str, checkin_date: str
) -> List[Dict]:
    """
    Uses a robust, few-shot prompt to parse check-in data with high accuracy,
    handling messy and varied inputs.
    """
    # This advanced prompt includes examples to guide the AI on handling edge cases.
    prompt = f"""
    You are a high-precision data extraction bot. Your task is to analyze user text and convert it into a structured JSON format without fail.

    **Instructions:**
    1.  Extract check-in details for the date: **{checkin_date}**.
    2.  The fields are "property_code", "guest_name", "platform", and "due_payment".
    3.  The property code is ALWAYS the first word on the line.
    4.  The guest name is the text after the first separator until the next separator. If you cannot read the name (e.g., it's in a different alphabet), use the placeholder text provided (e.g., "Chinese").
    5.  If any other field is missing, use the value "N/A".
    6.  You MUST return the data as a valid JSON array of objects, even if there is only one check-in.
    7.  Do NOT include any explanatory text, markdown formatting, or anything other than the raw JSON data in your response.

    **Examples:**

    **Input 1 (Standard):**
    A1 - John Smith - Arb - none
    K4 - Maria Garcia - Bdc - 50 eur

    **Your Output for Input 1:**
    [
        {{"property_code": "A1", "guest_name": "John Smith", "platform": "Arb", "due_payment": "none"}},
        {{"property_code": "K4", "guest_name": "Maria Garcia", "platform": "Bdc", "due_payment": "50 eur"}}
    ]

    **Input 2 (Messy, with placeholder name and missing fields):**
    C5 - Chinese - paid - asap
    D2 - Peter Pan

    **Your Output for Input 2:**
    [
        {{"property_code": "C5", "guest_name": "Chinese", "platform": "paid", "due_payment": "asap"}},
        {{"property_code": "D2", "guest_name": "Peter Pan", "platform": "N/A", "due_payment": "N/A"}}
    ]
    
    **Input 3 (Single line):**
    F2 - Last Minute Guest - paid

    **Your Output for Input 3:**
    [
        {{"property_code": "F2", "guest_name": "Last Minute Guest", "platform": "paid", "due_payment": "N/A"}}
    ]
    
    ---
    **Text to parse now:**
    {message_text}
    ---
    """

    validated_bookings = []
    try:
        response = await model.generate_content_async(prompt)

        # More robust cleaning: find the first '[' and the last ']' to extract the JSON array
        match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if not match:
            print(f"AI Check-in Parsing Error: No valid JSON array found in response.")
            print(f"Raw AI Response: {response.text}")
            return []

        cleaned_response = match.group(0)
        parsed_data = json.loads(cleaned_response)

        if not isinstance(parsed_data, list):
            raise TypeError("AI did not return a list of objects.")

        for item in parsed_data:
            if not isinstance(item, dict):
                continue
            validated_bookings.append(
                {
                    "property_code": str(item.get("property_code", "UNKNOWN")).upper(),
                    "guest_name": item.get("guest_name", "Unknown Guest"),
                    "platform": item.get("platform", "N/A"),
                    "due_payment": item.get("due_payment", "N/A"),
                    "checkin_date": datetime.date.fromisoformat(checkin_date),
                    "checkout_date": None,
                    "status": "Active",
                }
            )
        return validated_bookings
    except Exception as e:
        print(f"AI Check-in Parsing Exception: {e}")
        print(
            f"Failed to parse response: {response.text if 'response' in locals() else 'No response'}"
        )
        return []


async def parse_cleaning_list_with_ai(message_text: str) -> List[str]:
    """
    Uses a robust prompt to extract only property codes from a bulk text message.
    """
    prompt = f"""
    You are a high-precision data extraction bot. Your task is to extract property codes from the user's text.

    **Instructions:**
    1.  Identify and extract ONLY the property codes (e.g., A1, K4, Nador2).
    2.  Ignore all other words, numbers, dates, and formatting (e.g., "Cleaning", "list", "for", "guests", "-").
    3.  You MUST return the data as a valid JSON array of strings.
    4.  Do NOT include any explanatory text, markdown formatting, or anything other than the raw JSON data in your response.

    **Example:**

    **Input:**
    Cleaning list for 13 July
    Nador1 - 4 guests
    A57
    G1 and G2

    **Your Output:**
    ["Nador1", "A57", "G1", "G2"]

    ---
    **Text to parse now:**
    {message_text}
    ---
    """
    try:
        response = await model.generate_content_async(prompt)

        # More robust cleaning: find the first '[' and the last ']' to extract the JSON array
        match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if not match:
            print(f"AI Cleaning Parsing Error: No valid JSON array found in response.")
            print(f"Raw AI Response: {response.text}")
            return []

        cleaned_response = match.group(0)
        parsed_data = json.loads(cleaned_response)
        return [
            str(item).upper() for item in parsed_data if isinstance(item, (str, int))
        ]
    except Exception as e:
        print(f"AI Cleaning Parsing Exception: {e}")
        print(
            f"Failed to parse response: {response.text if 'response' in locals() else 'No response'}"
        )
        return []
# FILE: slack_parser.py
# ==============================================================================
from typing import List, Dict
import datetime
import json
import re
import google.generativeai as genai
from .config import GEMINI_API_KEY  # <-- FIX: Changed to relative import

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")


async def parse_checkin_list_with_ai(
    message_text: str, checkin_date: str
) -> List[Dict]:
    """
    Uses a robust, few-shot prompt to parse check-in data with high accuracy,
    handling messy and varied inputs.
    """
    # This advanced prompt includes examples to guide the AI on handling edge cases.
    prompt = f"""
    You are a high-precision data extraction bot. Your task is to analyze user text and convert it into a structured JSON format without fail.

    **Instructions:**
    1.  Extract check-in details for the date: **{checkin_date}**.
    2.  The fields are "property_code", "guest_name", "platform", and "due_payment".
    3.  The property code is ALWAYS the first word on the line.
    4.  The guest name is the text after the first separator until the next separator. If you cannot read the name (e.g., it's in a different alphabet), use the placeholder text provided (e.g., "Chinese").
    5.  If any other field is missing, use the value "N/A".
    6.  You MUST return the data as a valid JSON array of objects, even if there is only one check-in.
    7.  Do NOT include any explanatory text, markdown formatting, or anything other than the raw JSON data in your response.

    **Examples:**

    **Input 1 (Standard):**
    A1 - John Smith - Arb - none
    K4 - Maria Garcia - Bdc - 50 eur

    **Your Output for Input 1:**
    [
        {{"property_code": "A1", "guest_name": "John Smith", "platform": "Arb", "due_payment": "none"}},
        {{"property_code": "K4", "guest_name": "Maria Garcia", "platform": "Bdc", "due_payment": "50 eur"}}
    ]

    **Input 2 (Messy, with placeholder name and missing fields):**
    C5 - Chinese - paid - asap
    D2 - Peter Pan

    **Your Output for Input 2:**
    [
        {{"property_code": "C5", "guest_name": "Chinese", "platform": "paid", "due_payment": "asap"}},
        {{"property_code": "D2", "guest_name": "Peter Pan", "platform": "N/A", "due_payment": "N/A"}}
    ]
    
    **Input 3 (Single line):**
    F2 - Last Minute Guest - paid

    **Your Output for Input 3:**
    [
        {{"property_code": "F2", "guest_name": "Last Minute Guest", "platform": "paid", "due_payment": "N/A"}}
    ]
    
    ---
    **Text to parse now:**
    {message_text}
    ---
    """

    validated_bookings = []
    try:
        response = await model.generate_content_async(prompt)

        # More robust cleaning: find the first '[' and the last ']' to extract the JSON array
        match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if not match:
            print(f"AI Check-in Parsing Error: No valid JSON array found in response.")
            print(f"Raw AI Response: {response.text}")
            return []

        cleaned_response = match.group(0)
        parsed_data = json.loads(cleaned_response)

        if not isinstance(parsed_data, list):
            raise TypeError("AI did not return a list of objects.")

        for item in parsed_data:
            if not isinstance(item, dict):
                continue
            validated_bookings.append(
                {
                    "property_code": str(item.get("property_code", "UNKNOWN")).upper(),
                    "guest_name": item.get("guest_name", "Unknown Guest"),
                    "platform": item.get("platform", "N/A"),
                    "due_payment": item.get("due_payment", "N/A"),
                    "checkin_date": datetime.date.fromisoformat(checkin_date),
                    "checkout_date": None,
                    "status": "Active",
                }
            )
        return validated_bookings
    except Exception as e:
        print(f"AI Check-in Parsing Exception: {e}")
        print(
            f"Failed to parse response: {response.text if 'response' in locals() else 'No response'}"
        )
        return []


async def parse_cleaning_list_with_ai(message_text: str) -> List[str]:
    """
    Uses a robust prompt to extract only property codes from a bulk text message.
    """
    prompt = f"""
    You are a high-precision data extraction bot. Your task is to extract property codes from the user's text.

    **Instructions:**
    1.  Identify and extract ONLY the property codes (e.g., A1, K4, Nador2).
    2.  Ignore all other words, numbers, dates, and formatting (e.g., "Cleaning", "list", "for", "guests", "-").
    3.  You MUST return the data as a valid JSON array of strings.
    4.  Do NOT include any explanatory text, markdown formatting, or anything other than the raw JSON data in your response.

    **Example:**

    **Input:**
    Cleaning list for 13 July
    Nador1 - 4 guests
    A57
    G1 and G2

    **Your Output:**
    ["Nador1", "A57", "G1", "G2"]

    ---
    **Text to parse now:**
    {message_text}
    ---
    """
    try:
        response = await model.generate_content_async(prompt)

        # More robust cleaning: find the first '[' and the last ']' to extract the JSON array
        match = re.search(r"\[.*\]", response.text, re.DOTALL)
        if not match:
            print(f"AI Cleaning Parsing Error: No valid JSON array found in response.")
            print(f"Raw AI Response: {response.text}")
            return []

        cleaned_response = match.group(0)
        parsed_data = json.loads(cleaned_response)
        return [
            str(item).upper() for item in parsed_data if isinstance(item, (str, int))
        ]
    except Exception as e:
        print(f"AI Cleaning Parsing Exception: {e}")
        print(
            f"Failed to parse response: {response.text if 'response' in locals() else 'No response'}"
        )
        return []
# FILE: telegram_client.py
# ==============================================================================
# VERSION: 2.0
# UPDATED: The email notification formatters now include a 'DEADLINE' field,
# making urgent, time-sensitive tasks more visible to the team.
# ==============================================================================

import datetime
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .config import TELEGRAM_TARGET_CHAT_ID, TELEGRAM_TOPIC_IDS  # CORRECTED LINE
from .models import EmailAlert, Booking


async def send_telegram_message(
    bot: telegram.Bot,
    text: str,
    topic_name: str = "GENERAL",
    reply_markup=None,
    parse_mode: str = "Markdown",
):
    """Sends a message to a specific topic and returns the sent message object."""
    topic_id = TELEGRAM_TOPIC_IDS.get(topic_name)
    message_thread_id_to_send = topic_id if topic_name != "GENERAL" else None

    return await bot.send_message(
        chat_id=TELEGRAM_TARGET_CHAT_ID,
        text=text,
        message_thread_id=message_thread_id_to_send,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


def format_daily_list_summary(
    checkins: list, cleanings: list, pending_cleanings: list, date_str: str
) -> str:
    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    readable_date = date_obj.strftime("%B %d, %Y")
    message = [f"*{readable_date}*", f"✅ *Daily Lists Processed*"]
    if checkins:
        message.append(f"\n➡️ *New Check-ins Logged ({len(checkins)}):*")
        for booking in checkins:
            prop_code = (
                booking.property.code if booking.property else booking.property_code
            )
            message.append(f"  • `{prop_code}` - {booking.guest_name}")
    if cleanings:
        message.append(f"\n🧹 *Properties Marked as AVAILABLE ({len(cleanings)}):*")
        message.append(f"  • `{'`, `'.join(cleanings)}`")
    if pending_cleanings:
        message.append(
            f"\n⏳ *Properties Marked as PENDING CLEANING ({len(pending_cleanings)}):*"
        )
        message.append(f"  • `{'`, `'.join(pending_cleanings)}`")
    return "\n".join(message)


def format_conflict_alert(
    prop_code: str, active_booking: Booking, pending_booking: Booking
) -> tuple:
    """Formats the interactive alert for an overbooking conflict."""
    readable_date = datetime.datetime.now().strftime("%B %d, %Y")
    alert_text = (
        f"*{readable_date}*\n🚨 *OVERBOOKING CONFLICT* for `{prop_code}` 🚨\n\n"
        f"Two bookings exist for the same property. Please take action.\n\n"
        f"➡️ *Active Guest:*\n"
        f"  - Name: *{active_booking.guest_name}*\n"
        f"  - Platform: `{active_booking.platform}`\n\n"
        f"⏳ *Pending Guest:*\n"
        f"  - Name: *{pending_booking.guest_name}*\n"
        f"  - Platform: `{pending_booking.platform}`\n\n"
        f"To resolve, use the buttons below or the `/relocate` command."
    )
    keyboard = [
        [
            InlineKeyboardButton(
                f"Swap (Make {pending_booking.guest_name} Active)",
                callback_data=f"swap_relocation:{active_booking.id}:{pending_booking.id}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"Cancel Pending Guest ({pending_booking.guest_name})",
                callback_data=f"cancel_pending_relocation:{pending_booking.id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "Show Available Rooms", callback_data=f"show_available:{prop_code}"
            )
        ],
    ]
    return alert_text, InlineKeyboardMarkup(keyboard)


def format_checkin_error_alert(
    property_code: str, new_guest: str, prop_status: str, maintenance_notes: str = None
) -> tuple:
    readable_date = datetime.datetime.now().strftime("%B %d, %Y")
    title = f"🚨 *CHECK-IN FAILED* for `{property_code}` 🚨"
    reason = ""
    if prop_status == "PENDING_CLEANING":
        reason = "Property is awaiting cleaning and is not yet available."
    elif prop_status == "MAINTENANCE":
        reason = f"Property is blocked for *MAINTENANCE*.\nReason: _{maintenance_notes or 'No reason specified.'}_"
    else:
        reason = f"Property is in an unbookable state: `{prop_status}`."
    alert_text = (
        f"*{readable_date}*\n{title}\n\n"
        f"{reason}\n\n"
        f"Cannot check in new guest: *{new_guest}*.\n\n"
        f"This booking is now pending relocation. Please take action!"
    )
    keyboard = [
        [
            InlineKeyboardButton(
                "Show Available Rooms", callback_data=f"show_available:{property_code}"
            ),
            InlineKeyboardButton(
                "Suggest Relocation",
                switch_inline_query_current_chat=f"/relocate {property_code} ",
            ),
        ]
    ]
    return alert_text, InlineKeyboardMarkup(keyboard)


def format_email_notification(alert_record: EmailAlert) -> tuple:
    """Formats a high-priority, interactive notification based on a parsed email."""
    title = f"‼️ *URGENT EMAIL: {alert_record.category}* ‼️"
    platform_info = f"from *{alert_record.platform or 'Unknown'}*"
    mention = "@La1038"  # User to be mentioned

    message = [f"{title} {platform_info} {mention}"]

    if alert_record.summary:
        message.append(f"\n*Summary:* _{alert_record.summary}_")

    details = []
    if alert_record.guest_name:
        details.append(f"  - **Guest:** {alert_record.guest_name}")
    if alert_record.reservation_number:
        details.append(f"  - **Reservation #:** `{alert_record.reservation_number}`")
    if alert_record.property_code:
        details.append(f"  - **Property:** `{alert_record.property_code}`")

    if details:
        message.append("\n*Details:*")
        message.extend(details)

    if alert_record.deadline:
        message.append(f"\n⚠️ *DEADLINE:* `{alert_record.deadline}`")

    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Mark as Handled", callback_data=f"handle_email:{alert_record.id}"
            )
        ]
    ]

    return "\n".join(message), InlineKeyboardMarkup(keyboard)


def format_parsing_failure_alert(summary: str) -> str:
    """Formats a non-interactive alert for when AI email parsing fails."""
    return (
        f"🚨 *AI Email Parsing Failure* 🚨\n\n"
        f"The AI system failed to process an email.\n\n"
        f"*Reason:* _{summary}_\n\n"
        f"Please check the `eivissateam@gmail.com` inbox for an unread email that requires manual attention."
    )


def format_handled_email_notification(
    alert_record: EmailAlert, handler_name: str
) -> str:
    """Rebuilds an email alert message from DB data to show it has been handled."""
    title = f"📧 *{alert_record.category}* from *{alert_record.platform or 'Unknown'}*"
    message = [title]

    if alert_record.summary:
        message.append(f"\n*Summary:* _{alert_record.summary}_")

    details = []
    if alert_record.guest_name:
        details.append(f"  - **Guest:** {alert_record.guest_name}")
    if alert_record.reservation_number:
        details.append(f"  - **Reservation #:** `{alert_record.reservation_number}`")
    if alert_record.property_code:
        details.append(f"  - **Property:** `{alert_record.property_code}`")

    if details:
        message.append("\n*Details:*")
        message.extend(details)

    # --- NEW: Add deadline if it exists ---
    if alert_record.deadline:
        message.append(f"\n*Deadline:* `{alert_record.deadline}`")

    timestamp = alert_record.handled_at.strftime("%Y-%m-%d %H:%M")
    message.append(f"\n---\n✅ *Handled by {handler_name} at {timestamp}*")

    return "\n".join(message)


def format_unresolved_relocations_alert(bookings: list) -> str:
    """Formats a high-priority alert listing all unresolved relocations."""
    message = [
        "‼️ *DAILY REMINDER: Unresolved Relocations* ‼️\n",
        "The following guests have been pending relocation for over 6 hours and require immediate action:\n",
    ]
    for booking in bookings:
        message.append(f"  - *Guest:* {booking.guest_name}")
        message.append(f"    *Conflict Property:* `{booking.property_code}`")
        message.append(
            f"    *Created:* `{booking.created_at.strftime('%Y-%m-%d %H:%M')}` UTC\n"
        )

    message.append(
        "Please use the `/relocate` command or the buttons in the original alert to resolve these cases."
    )
    return "\n".join(message)


def format_email_reminder() -> str:
    """Formats a high-priority reminder for an open email alert."""
    return "🚨🚨 *REMINDER: ACTION STILL REQUIRED* 🚨🚨\nThe alert above has not been handled yet. Please review and take action."


def format_available_list(
    available_props: list, for_relocation_from: str = None
) -> str:
    if not available_props:
        return "❌ No properties are currently available."
    message = ["✅ *Available Properties:*"]
    codes = sorted([prop.code for prop in available_props])
    message.append(f"`{', '.join(codes)}`")
    if for_relocation_from:
        message.append(
            f"\n_To relocate from `{for_relocation_from}`, type:_ `/relocate {for_relocation_from} [new_room] [YYYY-MM-DD]`"
        )
    return "\n".join(message)


def format_status_report(
    total: int, occupied: int, available: int, pending_cleaning: int, maintenance: int
) -> str:
    return (
        f"📊 *Current System Status*\n\n"
        f"Total Properties: `{total}`\n"
        f"➡️ Occupied: `{occupied}`\n"
        f"⏳ Pending Cleaning: `{pending_cleaning}`\n"
        f"🛠️ Maintenance: `{maintenance}`\n"
        f"✅ Available: `{available}`"
    )


def format_property_check(prop, active_booking, issues) -> str:
    if not prop:
        return "❌ Property code not found in the database."

    status_emoji = {
        "AVAILABLE": "✅",
        "OCCUPIED": "➡️",
        "PENDING_CLEANING": "⏳",
        "MAINTENANCE": "🛠️",
    }.get(prop.status, "❓")

    message = [f"{status_emoji} *{prop.code}* Status: `{prop.status}`"]
    if prop.status == "OCCUPIED" and active_booking:
        message.append(f"  • Guest: *{active_booking.guest_name}*")
        message.append(f"  • Check-in: `{active_booking.checkin_date}`")
        message.append(f"  • Platform: `{active_booking.platform}`")
    elif prop.status == "PENDING_CLEANING" and active_booking:
        message.append(f"  • Previous Guest: *{active_booking.guest_name}*")
        message.append(f"  • Expected Checkout: `{active_booking.checkout_date}`")
    elif prop.status == "MAINTENANCE":
        message.append(f"  • Reason: _{prop.notes or 'No reason specified.'}_")

    if issues:
        message.append("\n*Recent Issues:*")
        for issue in issues:
            message.append(f"  - `{issue.reported_at}`: {issue.description}")

    return "\n".join(message)


def format_occupied_list(occupied_props: list) -> str:
    if not occupied_props:
        return "✅ All properties are currently available."
    message = ["🏨 *Currently Occupied Properties:*"]
    codes = sorted([prop.code for prop in occupied_props])
    message.append(f"`{', '.join(codes)}`")
    return "\n".join(message)


def format_simple_success(message: str) -> str:
    return f"✅ *Success*\n{message}"


def format_simple_error(message: str) -> str:
    return f"❌ *Error*\n{message}"


def format_booking_history(prop_code: str, bookings: list) -> str:
    if not bookings:
        return f"No booking history found for `{prop_code}`."
    message = [f"📖 *Booking History for {prop_code}*"]
    for b in bookings:
        message.append(
            f"  - `{b.checkin_date}` to `{b.checkout_date or 'Present'}`: *{b.guest_name}*"
        )
    return "\n".join(message)


def format_find_guest_results(results: list) -> str:
    if not results:
        return "❌ No active guest found matching that name."
    message = ["🔍 *Guest Search Results:*"]
    for booking in results:
        message.append(
            f"  • *{booking.guest_name}* is in property `{booking.property.code}`"
        )
    return "\n".join(message)


def format_pending_cleaning_list(props: list) -> str:
    if not props:
        return "✅ No properties are currently pending cleaning."
    message = ["⏳ *Properties Pending Cleaning:*"]
    codes = sorted([prop.code for prop in props])
    message.append(f"`{', '.join(codes)}`")
    return "\n".join(message)


def format_daily_revenue_report(
    date_str: str, total_revenue: float, booking_count: int
) -> str:
    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    readable_date = date_obj.strftime("%B %d, %Y")
    return (
        f"💰 *Revenue Report for {readable_date}*\n\n"
        f"Total Calculated Revenue: *€{total_revenue:.2f}*\n"
        f"From `{booking_count}` bookings."
    )


def format_checkout_reminder_alert(
    guest_name: str, property_code: str, checkout_date: str
) -> str:
    return (
        f"‼️ *HIGH PRIORITY REMINDER* ‼️\n\n"
        f"A relocated guest, *{guest_name}*, is scheduled to check out from property `{property_code}` tomorrow, *{checkout_date}*.\n\n"
        f"Please ensure you **add `{property_code}` to tomorrow's cleaning list**."
    )


def format_relocation_history(relocations: list) -> str:
    if not relocations:
        return "✅ No relocation history found."
    message = ["📖 *Recent Relocation History:*\n"]
    for r in relocations:
        date_str = r.relocated_at.strftime("%Y-%m-%d")
        message.append(
            f"- `{date_str}`: *{r.guest_name}* was moved from `{r.original_property_code}` to `{r.new_property_code}`."
        )
    return "\n".join(message)


def format_daily_briefing(
    time_of_day: str,
    occupied: int,
    pending_cleaning: int,
    maintenance: int,
    available: int,
) -> str:
    readable_date = datetime.datetime.now().strftime("%B %d, %Y")
    return (
        f"*{time_of_day} Briefing - {readable_date}*\n\n"
        f"Here is the current operational status:\n"
        f"➡️ Occupied: `{occupied}`\n"
        f"⏳ Pending Cleaning: `{pending_cleaning}`\n"
        f"🛠️ Maintenance: `{maintenance}`\n"
        f"✅ Available: `{available}`"
    )


def format_cleaning_list_receipt(success_codes: list, warnings: list) -> str:
    message = ["✅ *Cleaning List Processed*"]
    if success_codes:
        message.append(
            f"\nThe following {len(success_codes)} properties were correctly marked as `PENDING_CLEANING`:"
        )
        message.append(f"`{', '.join(sorted(success_codes))}`")
    else:
        message.append("\nNo properties were updated.")
    if warnings:
        message.append("\n\n⚠️ *Warnings (These were NOT processed):*")
        for warning in warnings:
            message.append(f"  - {warning}")
    return "\n".join(message)


def format_invalid_code_alert(
    invalid_code: str, original_message: str, suggestions: list = None
) -> str:
    alert_text = (
        f"❓ *Invalid Property Code Detected*\n\n"
        f"An operation was attempted for property code `{invalid_code}`, but this code does not exist in the database.\n\n"
    )
    if suggestions:
        alert_text += f"*Did you mean one of these?* `{', '.join(suggestions)}`\n\n"
    alert_text += f"The original message was:\n`{original_message}`\n\nPlease check for a typo and re-submit."
    return alert_text
# FILE: app/telegram_handlers.py
import datetime
import re
from sqlalchemy.orm import Session, joinedload
from telegram import Update
from telegram.ext import ContextTypes
import pytz
from . import models, telegram_client, config
from .database import engine
from .utils.db_manager import db_session_manager
from .utils.validators import get_property_from_context
from .scheduled_tasks import scheduler, send_checkout_reminder

# --- DYNAMIC HELP COMMAND MANUAL ---
COMMANDS_HELP_MANUAL = {
    "status": {
        "description": "Get a full summary of all property statuses.",
        "example": "/status",
    },
    "check": {
        "description": "Get a detailed status report for a single property.",
        "example": "/check A1",
    },
    "rename_property": {
        "description": "Correct a property's code in the database.",
        "example": "/rename_property C7 C8",
    },
    "available": {
        "description": "List all properties that are clean and available.",
        "example": "/available",
    },
    "occupied": {
        "description": "List all properties that are currently occupied.",
        "example": "/occupied",
    },
    "pending_cleaning": {
        "description": "List all properties waiting to be cleaned.",
        "example": "/pending_cleaning",
    },
    "early_checkout": {
        "description": "Manually mark an occupied property as ready for cleaning.",
        "example": "/early_checkout C5",
    },
    "set_clean": {
        "description": "Manually mark a property as clean and available.",
        "example": "/set_clean D2",
    },
    "cancel_booking": {
        "description": "Cancel an active booking and make the property available.",
        "example": "/cancel_booking A1",
    },
    "edit_booking": {
        "description": "Edit details of an active booking (guest_name, due_payment, platform).",
        "example": "/edit_booking K4 guest_name Maria Garcia-Lopez",
    },
    "relocate": {
        "description": "Move a guest pending relocation and set their checkout date.",
        "example": "/relocate A1 A2 2025-07-20",
    },
    "log_issue": {
        "description": "Log a new maintenance issue for a property.",
        "example": "/log_issue C5 Shower drain is clogged",
    },
    "block_property": {
        "description": "Block a property for maintenance.",
        "example": "/block_property G2 Repainting walls",
    },
    "unblock_property": {
        "description": "Unblock a property and make it available.",
        "example": "/unblock_property G2",
    },
    "booking_history": {
        "description": "Show the last 5 bookings for a property.",
        "example": "/booking_history A1",
    },
    "find_guest": {
        "description": "Find which property a guest is staying in.",
        "example": "/find_guest Smith",
    },
    "daily_revenue": {
        "description": "Calculate estimated revenue for a given date (defaults to today).",
        "example": "/daily_revenue 2025-07-13",
    },
    "relocations": {
        "description": "Show a history of recent guest relocations.",
        "example": "/relocations or /relocations A1",
    },
    "help": {"description": "Show this help manual.", "example": "/help"},
}

# --- Telegram Command Handlers ---


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the full command manual."""
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="\n".join(
            [
                "*Eivissa Operations Bot - Command Manual* 🤖\n",
                *[
                    f"*/{command}*\n_{details['description']}_\nExample: `{details['example']}`\n"
                    for command, details in COMMANDS_HELP_MANUAL.items()
                ],
            ]
        ),
        parse_mode="Markdown",
    )


@db_session_manager
async def status_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Sends a summary of all property statuses."""
    total = db.query(models.Property).count()
    occupied = (
        db.query(models.Property).filter(models.Property.status == "OCCUPIED").count()
    )
    available = (
        db.query(models.Property).filter(models.Property.status == "AVAILABLE").count()
    )
    pending = (
        db.query(models.Property)
        .filter(models.Property.status == "PENDING_CLEANING")
        .count()
    )
    maintenance = (
        db.query(models.Property)
        .filter(models.Property.status == "MAINTENANCE")
        .count()
    )
    report = telegram_client.format_status_report(
        total, occupied, available, pending, maintenance
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def check_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Gets a detailed status report for a single property."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    active_booking = None
    if prop.status != "AVAILABLE":
        active_booking = (
            db.query(models.Booking)
            .filter(models.Booking.property_id == prop.id)
            .order_by(models.Booking.id.desc())
            .first()
        )
    report = telegram_client.format_property_check(prop, active_booking, prop.issues)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def occupied_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Lists all currently occupied properties."""
    props = (
        db.query(models.Property)
        .filter(models.Property.status == "OCCUPIED")
        .order_by(models.Property.code)
        .all()
    )
    report = telegram_client.format_occupied_list(props)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def available_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Lists all clean and available properties."""
    props = (
        db.query(models.Property)
        .filter(models.Property.status == "AVAILABLE")
        .order_by(models.Property.code)
        .all()
    )
    report = telegram_client.format_available_list(props)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def early_checkout_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Manually marks an occupied property as PENDING_CLEANING."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    if prop.status != "OCCUPIED":
        report = telegram_client.format_simple_error(
            f"Property `{prop.code}` is currently `{prop.status}`, not OCCUPIED."
        )
    else:
        prop.status = "PENDING_CLEANING"
        db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{prop.code}` has been checked out and is now *PENDING_CLEANING*."
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def set_clean_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Manually marks a property as clean and AVAILABLE."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    if prop.status != "PENDING_CLEANING":
        report = telegram_client.format_simple_error(
            f"Property `{prop.code}` is currently `{prop.status}`, not PENDING_CLEANING."
        )
    else:
        prop.status = "AVAILABLE"
        db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{prop.code}` has been manually set to *AVAILABLE*."
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def rename_property_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Renames a property's code in the database."""
    if len(context.args) != 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/rename_property [OLD_CODE] [NEW_CODE]`",
        )
        return

    old_code, new_code = context.args[0].upper(), context.args[1].upper()

    if db.query(models.Property).filter(models.Property.code == new_code).first():
        report = telegram_client.format_simple_error(
            f"Cannot rename: Property `{new_code}` already exists."
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
        )
        return

    prop_to_rename = (
        db.query(models.Property).filter(models.Property.code == old_code).first()
    )
    if not prop_to_rename:
        report = telegram_client.format_simple_error(
            f"Property `{old_code}` not found."
        )
    else:
        prop_to_rename.code = new_code
        db.query(models.Booking).filter(
            models.Booking.property_code == old_code
        ).update({"property_code": new_code})
        db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{old_code}` has been successfully renamed to `{new_code}`."
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def relocate_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Moves a guest pending relocation to an available room."""
    if len(context.args) != 3:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/relocate [FROM_CODE] [TO_CODE] [YYYY-MM-DD]`",
        )
        return

    from_code, to_code, checkout_date_str = (
        context.args[0].upper(),
        context.args[1].upper(),
        context.args[2],
    )
    try:
        checkout_date = datetime.date.fromisoformat(checkout_date_str)
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Error: Invalid date format. Please use `YYYY-MM-DD`.",
        )
        return

    to_prop = db.query(models.Property).filter(models.Property.code == to_code).first()
    if not to_prop or to_prop.status != "AVAILABLE":
        report = telegram_client.format_simple_error(
            f"Property `{to_code}` is not available for relocation."
        )
    else:
        booking_to_relocate = (
            db.query(models.Booking)
            .filter(
                models.Booking.property_code == from_code,
                models.Booking.status == "PENDING_RELOCATION",
            )
            .order_by(models.Booking.id.desc())
            .first()
        )
        if not booking_to_relocate:
            report = telegram_client.format_simple_error(
                f"No booking found pending relocation for `{from_code}`."
            )
        else:
            log_entry = models.Relocation(
                booking_id=booking_to_relocate.id,
                guest_name=booking_to_relocate.guest_name,
                original_property_code=from_code,
                new_property_code=to_code,
            )
            db.add(log_entry)
            to_prop.status = "OCCUPIED"
            booking_to_relocate.status = "Active"
            booking_to_relocate.property_id = to_prop.id
            booking_to_relocate.property_code = to_prop.code
            booking_to_relocate.checkout_date = checkout_date
            reminder_datetime = datetime.datetime.combine(
                checkout_date - datetime.timedelta(days=1), datetime.time(18, 0)
            )
            scheduler.add_job(
                send_checkout_reminder,
                "date",
                run_date=reminder_datetime,
                args=[booking_to_relocate.guest_name, to_code, checkout_date_str],
                id=f"checkout_reminder_{booking_to_relocate.id}",
                replace_existing=True,
            )
            db.commit()
            report = telegram_client.format_simple_success(
                f"Relocation Successful!\n"
                f"Guest *{booking_to_relocate.guest_name}* has been moved to `{to_code}`.\n"
                f"A checkout reminder has been scheduled for *{reminder_datetime.strftime('%Y-%m-%d %H:%M')}*."
            )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def pending_cleaning_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Lists all properties waiting to be cleaned."""
    props = (
        db.query(models.Property)
        .filter(models.Property.status == "PENDING_CLEANING")
        .order_by(models.Property.code)
        .all()
    )
    report = telegram_client.format_pending_cleaning_list(props)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def cancel_booking_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Cancels an active booking and makes the property available."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    if prop.status != "OCCUPIED":
        report = telegram_client.format_simple_error(
            f"Property `{prop.code}` is not occupied."
        )
    else:
        booking = (
            db.query(models.Booking)
            .filter(
                models.Booking.property_id == prop.id, models.Booking.status == "Active"
            )
            .first()
        )
        if booking:
            booking.status = "Cancelled"
            prop.status = "AVAILABLE"
            db.commit()
            report = telegram_client.format_simple_success(
                f"Booking for *{booking.guest_name}* in `{prop.code}` has been cancelled. The property is now available."
            )
        else:
            report = telegram_client.format_simple_error(
                f"No active booking found for `{prop.code}`."
            )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def edit_booking_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Edits details of an active booking."""
    if len(context.args) < 3:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/edit_booking [CODE] [field] [new_value]`\nFields: `guest_name`, `due_payment`, `platform`",
        )
        return

    prop_code = context.args[0].upper()
    prop = db.query(models.Property).filter(models.Property.code == prop_code).first()

    if not prop or prop.status != "OCCUPIED":
        report = telegram_client.format_simple_error(
            f"Property `{prop_code}` not found or is not occupied."
        )
    else:
        field = context.args[1].lower()
        new_value = " ".join(context.args[2:])
        booking = (
            db.query(models.Booking)
            .filter(
                models.Booking.property_id == prop.id, models.Booking.status == "Active"
            )
            .first()
        )
        if not booking:
            report = telegram_client.format_simple_error(
                f"No active booking found for `{prop_code}`."
            )
        elif field not in ["guest_name", "due_payment", "platform"]:
            report = telegram_client.format_simple_error(
                f"Invalid field `{field}`. Use `guest_name`, `due_payment`, or `platform`."
            )
        else:
            setattr(booking, field, new_value)
            db.commit()
            report = telegram_client.format_simple_success(
                f"Booking for `{prop_code}` updated: `{field}` is now *{new_value}*."
            )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def log_issue_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Logs a new maintenance issue for a property."""
    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/log_issue [CODE] [description]`",
        )
        return

    prop = await get_property_from_context(update, context.args[:1], db)
    if not prop:
        return

    description = " ".join(context.args[1:])
    new_issue = models.Issue(property_id=prop.id, description=description)
    db.add(new_issue)
    db.commit()
    report = telegram_client.format_simple_success(
        f"New issue logged for `{prop.code}`: _{description}_"
    )
    await telegram_client.send_telegram_message(
        context.bot, report, topic_name="ISSUES"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Issue logged successfully in the #issues topic.",
    )


@db_session_manager
async def block_property_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Blocks a property for maintenance."""
    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/block_property [CODE] [reason]`",
        )
        return

    prop = await get_property_from_context(update, context.args[:1], db)
    if not prop:
        return

    if prop.status == "OCCUPIED":
        report = telegram_client.format_simple_error(
            f"Cannot block `{prop.code}`, it is currently occupied."
        )
    else:
        reason = " ".join(context.args[1:])
        prop.status = "MAINTENANCE"
        prop.notes = reason
        db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{prop.code}` is now blocked for *MAINTENANCE*.\nReason: _{reason}_"
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def unblock_property_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Unblocks a property and makes it available."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    if prop.status != "MAINTENANCE":
        report = telegram_client.format_simple_error(
            f"Property `{prop.code}` is not under maintenance."
        )
    else:
        prop.status = "AVAILABLE"
        prop.notes = None
        db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{prop.code}` has been unblocked and is now *AVAILABLE*."
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def booking_history_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Shows the last 5 bookings for a property."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    bookings = (
        db.query(models.Booking)
        .filter(models.Booking.property_code == prop.code)
        .order_by(models.Booking.checkin_date.desc())
        .limit(5)
        .all()
    )
    report = telegram_client.format_booking_history(prop.code, bookings)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def find_guest_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Finds which property a guest is staying in."""
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Usage: `/find_guest [GUEST_NAME]`"
        )
        return

    guest_name = " ".join(context.args)
    results = (
        db.query(models.Booking)
        .options(joinedload(models.Booking.property))
        .filter(
            models.Booking.guest_name.ilike(f"%{guest_name}%"),
            models.Booking.status == "Active",
        )
        .all()
    )
    report = telegram_client.format_find_guest_results(results)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def daily_revenue_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Calculates estimated revenue for a given date."""
    try:
        date_str = (
            context.args[0] if context.args else datetime.date.today().isoformat()
        )
        target_date = datetime.date.fromisoformat(date_str)
    except (ValueError, IndexError):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Invalid date format. Please use `YYYY-MM-DD`.",
        )
        return

    bookings = (
        db.query(models.Booking)
        .filter(models.Booking.checkin_date == target_date)
        .all()
    )
    total_revenue = 0.0
    for b in bookings:
        # Use regex to find the first number (integer or float) in the payment string
        numbers = re.findall(r"\d+\.?\d*", b.due_payment)
        if numbers:
            total_revenue += float(numbers[0])
    report = telegram_client.format_daily_revenue_report(
        date_str, total_revenue, len(bookings)
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def relocations_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Shows a history of recent guest relocations."""
    query = db.query(models.Relocation).order_by(models.Relocation.relocated_at.desc())
    if context.args:
        prop_code = context.args[0].upper()
        query = query.filter(
            (models.Relocation.original_property_code == prop_code)
            | (models.Relocation.new_property_code == prop_code)
        )
    history = query.limit(10).all()
    report = telegram_client.format_relocation_history(history)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def button_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: Session
):
    """Handles all callback queries from inline buttons."""
    query = update.callback_query
    await query.answer()
    action, *data = query.data.split(":")

    # --- Show Available Rooms Action ---
    if action == "show_available":
        prop_code = data[0]
        props = (
            db.query(models.Property)
            .filter(models.Property.status == "AVAILABLE")
            .order_by(models.Property.code)
            .all()
        )
        report = telegram_client.format_available_list(
            props, for_relocation_from=prop_code
        )

        # This check prevents an error if the user clicks the button multiple times.
        if report not in query.message.text:
            # Re-applying `query.message.reply_markup` ensures buttons persist.
            await query.edit_message_text(
                text=f"{query.message.text_markdown}\n\n{report}",
                parse_mode="Markdown",
                reply_markup=query.message.reply_markup,
            )

    # --- Swap Relocation Action ---
    elif action == "swap_relocation":
        active_booking_id, pending_booking_id = data[0], data[1]
        active_booking = (
            db.query(models.Booking)
            .filter(models.Booking.id == active_booking_id)
            .first()
        )
        pending_booking = (
            db.query(models.Booking)
            .filter(models.Booking.id == pending_booking_id)
            .first()
        )

        if not active_booking or not pending_booking:
            await query.edit_message_text(
                text=f"{query.message.text_markdown}\n\n❌ Error: Could not find original bookings to swap.",
                parse_mode="Markdown",
            )
            return

        # Perform the swap
        active_booking.status = "PENDING_RELOCATION"
        pending_booking.status = "Active"
        db.commit()

        # Generate new text and a NEW keyboard with updated callback data
        new_text, new_keyboard = telegram_client.format_conflict_alert(
            prop_code=active_booking.property_code,
            active_booking=pending_booking,  # The roles are now swapped
            pending_booking=active_booking,
        )

        confirmation_text = f"✅ *Swap Successful!*\n\n{new_text}"
        await query.edit_message_text(
            text=confirmation_text, parse_mode="Markdown", reply_markup=new_keyboard
        )

    # --- NEW: Cancel Pending Relocation Action ---
    elif action == "cancel_pending_relocation":
        pending_booking_id = data[0]
        booking_to_cancel = (
            db.query(models.Booking)
            .filter(models.Booking.id == pending_booking_id)
            .first()
        )

        if not booking_to_cancel:
            await query.edit_message_text(
                text=f"{query.message.text_markdown}\n\n❌ Error: Could not find booking to cancel.",
                parse_mode="Markdown",
            )
            return

        if booking_to_cancel.status != "PENDING_RELOCATION":
            await query.edit_message_text(
                text=f"{query.message.text_markdown}\n\n⚠️ This booking is no longer pending relocation.",
                parse_mode="Markdown",
            )
            return

        booking_to_cancel.status = "Cancelled"
        db.commit()

        # Final resolution message with all buttons removed
        new_text = (
            f"{query.message.text_markdown}\n\n---\n"
            f"✅ *Conflict Resolved.*\nBooking for *{booking_to_cancel.guest_name}* has been cancelled."
        )
        await query.edit_message_text(
            text=new_text, parse_mode="Markdown", reply_markup=None
        )

    # --- Handle Email Action ---
    elif action == "handle_email":
        alert_id = int(data[0])
        alert = (
            db.query(models.EmailAlert).filter(models.EmailAlert.id == alert_id).first()
        )
        if alert and alert.status == "OPEN":
            alert.status = "HANDLED"
            alert.handled_by = query.from_user.full_name

            budapest_tz = pytz.timezone(config.TIMEZONE)
            alert.handled_at = datetime.datetime.now(budapest_tz)

            db.commit()

            new_text = telegram_client.format_handled_email_notification(
                alert, query.from_user.full_name
            )
            await query.edit_message_text(
                text=new_text, parse_mode="Markdown", reply_markup=None
            )
        else:
            await query.answer("This alert has already been handled.", show_alert=True)
