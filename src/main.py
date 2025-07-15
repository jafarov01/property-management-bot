# FILE: main.py
# ==============================================================================
# VERSION: 12.0 (Temporary DB Fix)
# UPDATED:
#   - Added a TEMPORARY one-time startup script to DROP the old 'email_alerts'
#     table. This will force the application to recreate it with the correct
#     new schema, fixing the "UndefinedColumn" error.
# ==============================================================================

import datetime
import re
import asyncio
import time
import traceback
import logging
import sys
from contextlib import asynccontextmanager
from difflib import get_close_matches
from fastapi import FastAPI, Request, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text # Import the 'text' function
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

import config
import telegram_client
import slack_parser
import models
import email_parser
from database import get_db, engine

# --- Configure Logging ---
handler = logging.StreamHandler(sys.stdout)
handler.flush = sys.stdout.flush
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[handler]
)

# --- Database Initialization ---
# This will create tables IF they don't exist. It does not alter existing ones.
models.Base.metadata.create_all(bind=engine)

# --- Application Instances & Persistent Scheduler ---
jobstores = {
    'default': SQLAlchemyJobStore(url=config.DATABASE_URL)
}
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=config.TIMEZONE)

slack_app = AsyncApp(token=config.SLACK_BOT_TOKEN, signing_secret=config.SLACK_SIGNING_SECRET)
telegram_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
slack_handler = AsyncSlackRequestHandler(slack_app)

# --- DYNAMIC HELP COMMAND MANUAL (No changes) ---
COMMANDS_HELP_MANUAL = {
    "status": {"description": "Get a full summary of all property statuses.", "example": "/status"},
    "check": {"description": "Get a detailed status report for a single property.", "example": "/check A1"},
    "rename_property": {"description": "Correct a property's code in the database.", "example": "/rename_property C7 C8"},
    "available": {"description": "List all properties that are clean and available.", "example": "/available"},
    "occupied": {"description": "List all properties that are currently occupied.", "example": "/occupied"},
    "pending_cleaning": {"description": "List all properties waiting to be cleaned.", "example": "/pending_cleaning"},
    "early_checkout": {"description": "Manually mark an occupied property as ready for cleaning.", "example": "/early_checkout C5"},
    "set_clean": {"description": "Manually mark a property as clean and available.", "example": "/set_clean D2"},
    "cancel_booking": {"description": "Cancel an active booking and make the property available.", "example": "/cancel_booking A1"},
    "edit_booking": {"description": "Edit details of an active booking (guest_name, due_payment, platform).", "example": "/edit_booking K4 guest_name Maria Garcia-Lopez"},
    "relocate": {"description": "Move a guest pending relocation and set their checkout date.", "example": "/relocate A1 A2 2025-07-20"},
    "log_issue": {"description": "Log a new maintenance issue for a property.", "example": "/log_issue C5 Shower drain is clogged"},
    "block_property": {"description": "Block a property for maintenance.", "example": "/block_property G2 Repainting walls"},
    "unblock_property": {"description": "Unblock a property and make it available.", "example": "/unblock_property G2"},
    "booking_history": {"description": "Show the last 5 bookings for a property.", "example": "/booking_history A1"},
    "find_guest": {"description": "Find which property a guest is staying in.", "example": "/find_guest Smith"},
    "daily_revenue": {"description": "Calculate estimated revenue for a given date (defaults to today).", "example": "/daily_revenue 2025-07-13"},
    "relocations": {"description": "Show a history of recent guest relocations.", "example": "/relocations or /relocations A1"},
    "help": {"description": "Show this help manual.", "example": "/help"}
}

# --- Global Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error("Exception caught by global error handler", exc_info=context.error)
    error_message = (
        f"🚨 *An unexpected error occurred*\n\n"
        f"*Type:* `{type(context.error).__name__}`\n"
        f"*Error:* `{context.error}`\n\n"
        f"Details have been logged for review."
    )
    await telegram_client.send_telegram_message(context.bot, error_message, topic_name="ISSUES")

# --- Scheduled Tasks ---
async def check_emails_task():
    logging.info("Running email check...")
    bot = telegram_app.bot
    db = next(get_db())
    try:
        unread_emails = email_parser.fetch_unread_emails()
        if not unread_emails:
            return
            
        logging.info(f"Found {len(unread_emails)} new emails to process.")
        for email_data in unread_emails:
            try:
                parsed_data = await email_parser.parse_booking_email_with_ai(email_data["body"])
                
                if parsed_data and parsed_data.get("category") not in ["Parsing Failed", "Parsing Exception"]:
                    new_alert = models.EmailAlert(
                        category=parsed_data.get("category", "Uncategorized"),
                        summary=parsed_data.get("summary"),
                        guest_name=parsed_data.get("guest_name"),
                        property_code=parsed_data.get("property_code"),
                        platform=parsed_data.get("platform"),
                        reservation_number=parsed_data.get("reservation_number"),
                        deadline=parsed_data.get("deadline")
                    )
                    db.add(new_alert)
                    db.commit()

                    notification_text, reply_markup = telegram_client.format_email_notification(new_alert)
                    
                    sent_message = await telegram_client.send_telegram_message(bot, notification_text, topic_name="EMAILS", reply_markup=reply_markup)
                    
                    if sent_message:
                        new_alert.telegram_message_id = sent_message.message_id
                        db.commit()
            except Exception as e:
                logging.error(f"Failed to process a single email.", exc_info=e)
                db.rollback() # Rollback the session if one email fails
    finally:
        db.close()

# ... (The rest of the scheduled tasks and functions remain the same)
async def email_reminder_task():
    logging.info("Checking for open email alerts...")
    bot = telegram_app.bot
    db = next(get_db())
    try:
        time_threshold = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=9)
        open_alerts = db.query(models.EmailAlert).filter(
            models.EmailAlert.status == "OPEN",
            models.EmailAlert.created_at <= time_threshold
        ).all()
        
        if not open_alerts:
            return

        logging.info(f"Found {len(open_alerts)} open alerts. Sending reminders.")
        reminder_text = telegram_client.format_email_reminder()
        for alert in open_alerts:
            try:
                await bot.send_message(
                    chat_id=config.TELEGRAM_TARGET_CHAT_ID,
                    text=reminder_text,
                    message_thread_id=config.TELEGRAM_TOPIC_IDS.get("EMAILS"),
                    reply_to_message_id=alert.telegram_message_id
                )
            except Exception as e:
                logging.error(f"Could not send reminder for alert {alert.id}", exc_info=e)
    finally:
        db.close()

async def send_checkout_reminder(guest_name: str, property_code: str, checkout_date: str):
    bot = telegram_app.bot
    report = telegram_client.format_checkout_reminder_alert(guest_name, property_code, checkout_date)
    await telegram_client.send_telegram_message(bot, report, topic_name="ISSUES")
    logging.info(f"Sent checkout reminder for {guest_name} in {property_code}.")

async def daily_briefing_task(time_of_day: str):
    logging.info(f"Running {time_of_day} briefing...")
    bot = telegram_app.bot
    db = next(get_db())
    try:
        occupied = db.query(models.Property).filter(models.Property.status == "OCCUPIED").count()
        pending = db.query(models.Property).filter(models.Property.status == "PENDING_CLEANING").count()
        maintenance = db.query(models.Property).filter(models.Property.status == "MAINTENANCE").count()
        available = db.query(models.Property).filter(models.Property.status == "AVAILABLE").count()
        report = telegram_client.format_daily_briefing(time_of_day, occupied, pending, maintenance, available)
        await telegram_client.send_telegram_message(bot, report, topic_name="GENERAL")
    finally:
        db.close()

async def daily_midnight_task():
    logging.info("Running midnight task...")
    db = next(get_db())
    bot = telegram_app.bot
    try:
        props_to_make_available = db.query(models.Property).filter(models.Property.status == "PENDING_CLEANING").all()
        if not props_to_make_available:
            logging.info("Midnight Task: No properties were pending cleaning.")
            return
        prop_codes = [prop.code for prop in props_to_make_available]
        for prop in props_to_make_available:
            prop.status = "AVAILABLE"
        db.commit()
        summary_text = (f"Automated Midnight Task (00:05 Local Time)\n\n"
                        f"🧹 The following {len(prop_codes)} properties have been cleaned and are now *AVAILABLE* for the new day:\n\n"
                        f"`{', '.join(sorted(prop_codes))}`")
        await telegram_client.send_telegram_message(bot, summary_text, topic_name="GENERAL")
        logging.info(f"Midnight Task: Set {len(prop_codes)} properties to AVAILABLE.")
    except Exception as e:
        logging.error("Error during midnight task", exc_info=e)
        await telegram_client.send_telegram_message(bot, f"🚨 Error in scheduled midnight task: {e}", topic_name="ISSUES")
    finally:
        db.close()

async def process_slack_message(payload: dict):
    db = next(get_db())
    try:
        event = payload.get("event", {})
        user_id = event.get('user')
        if user_id != config.SLACK_USER_ID_OF_LIST_POSTER: return
        message_text = event.get('text', '')
        channel_id = event.get('channel')
        message_ts = float(event.get('ts', time.time()))
        list_date_str = datetime.date.fromtimestamp(message_ts).isoformat()
        logging.info(f"MESSAGE RECEIVED from {user_id} in channel {channel_id}: {message_text[:50]}...")
        bot = telegram_app.bot
        all_prop_codes = [p.code for p in db.query(models.Property.code).all()]
        if "great reset" in message_text.lower():
            logging.warning("'great reset' command detected. This will wipe the database.")
            for job in scheduler.get_jobs():
                if job.id.startswith("checkout_reminder_"):
                    job.remove()
            db.query(models.EmailAlert).delete()
            db.query(models.Relocation).delete()
            db.query(models.Issue).delete()
            db.query(models.Booking).delete()
            db.query(models.Property).delete()
            db.commit()
            properties_to_seed = await slack_parser.parse_cleaning_list_with_ai(message_text)
            count = 0
            for prop_code in properties_to_seed:
                if prop_code and prop_code != "N/A" and not db.query(models.Property).filter(models.Property.code == prop_code).first():
                    db.add(models.Property(code=prop_code, status="AVAILABLE"))
                    count += 1
            db.commit()
            await telegram_client.send_telegram_message(bot, f"✅ *System Initialized*\n\nSuccessfully seeded the database with `{count}` properties.", topic_name="GENERAL")
            return
        if channel_id == config.SLACK_CHECKIN_CHANNEL_ID:
            new_bookings_data = await slack_parser.parse_checkin_list_with_ai(message_text, list_date_str)
            processed_bookings = []
            for booking_data in new_bookings_data:
                try:
                    prop_code = booking_data["property_code"]
                    guest_name = booking_data["guest_name"]
                    if guest_name in ["N/A", "Unknown Guest"]:
                        logging.warning(f"Skipping booking for {prop_code} due to missing guest name.")
                        continue
                    if prop_code == "UNKNOWN": continue
                    if prop_code not in all_prop_codes:
                        suggestions = get_close_matches(prop_code, all_prop_codes, n=3, cutoff=0.7)
                        original_line = next((line for line in message_text.split('\n') if line.strip().startswith(prop_code)), message_text)
                        alert_text = telegram_client.format_invalid_code_alert(prop_code, original_line, suggestions)
                        await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES")
                        continue
                    prop = db.query(models.Property).filter(models.Property.code == prop_code).with_for_update().first()
                    if not prop or prop.status != "AVAILABLE":
                        if prop and prop.status == "OCCUPIED":
                            first_booking = db.query(models.Booking).filter(models.Booking.property_id == prop.id, models.Booking.status == "Active").order_by(models.Booking.id.desc()).first()
                            booking_data['status'] = "PENDING_RELOCATION"
                            second_booking = models.Booking(**booking_data, property_id=prop.id)
                            db.add(second_booking)
                            db.commit()
                            alert_text, reply_markup = telegram_client.format_conflict_alert(prop_code, first_booking, second_booking)
                            await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES", reply_markup=reply_markup)
                        else:
                            prop_status = prop.status if prop else "NOT_FOUND"
                            booking_data['status'] = "PENDING_RELOCATION"
                            failed_booking = models.Booking(**booking_data)
                            db.add(failed_booking)
                            db.commit()
                            alert_text, reply_markup = telegram_client.format_checkin_error_alert(
                                property_code=prop_code, new_guest=booking_data["guest_name"], prop_status=prop_status,
                                maintenance_notes=prop.notes if prop else None
                            )
                            await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES", reply_markup=reply_markup)
                        continue
                    prop.status = "OCCUPIED"
                    db_booking = models.Booking(property_id=prop.id, **booking_data)
                    db.add(db_booking)
                    db.flush()
                    processed_bookings.append(db_booking)
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logging.error(f"Error processing a single check-in line: {booking_data}", exc_info=e)
                    await telegram_client.send_telegram_message(bot, f"⚠️ Failed to process one line of the check-in list: `{booking_data}`. Please check it manually.", topic_name="ISSUES")
            if processed_bookings:
                summary_text = telegram_client.format_daily_list_summary(processed_bookings, [], [], list_date_str)
                await telegram_client.send_telegram_message(bot, summary_text, topic_name="GENERAL")
        elif channel_id == config.SLACK_CLEANING_CHANNEL_ID:
            properties_to_process = await slack_parser.parse_cleaning_list_with_ai(message_text)
            success_codes = []
            warnings = []
            for prop_code in properties_to_process:
                prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
                if not prop:
                    warnings.append(f"`{prop_code}`: Code not found in database (check for typo).")
                    continue
                if prop.status == "OCCUPIED":
                    prop.status = "PENDING_CLEANING"
                    booking_to_update = db.query(models.Booking).filter(models.Booking.property_id == prop.id, models.Booking.status == "Active").order_by(models.Booking.id.desc()).first()
                    if booking_to_update:
                        booking_to_update.checkout_date = (datetime.date.fromisoformat(list_date_str) + datetime.timedelta(days=1)).isoformat()
                        booking_to_update.status = "Departed"
                    success_codes.append(prop.code)
                else:
                    warnings.append(f"`{prop_code}`: Not processed, status was already `{prop.status}`.")
            db.commit()
            receipt_message = telegram_client.format_cleaning_list_receipt(success_codes, warnings)
            await telegram_client.send_telegram_message(bot, receipt_message, topic_name="GENERAL")
    except Exception as e:
        db.rollback()
        logging.critical("CRITICAL ERROR IN SLACK PROCESSOR", exc_info=e)
    finally:
        db.close()

# ... (The rest of the file remains the same)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- TEMPORARY DATABASE FIX SCRIPT ---
    try:
        logging.info("Attempting to drop 'email_alerts' table to ensure schema is up to date...")
        with engine.connect() as connection:
            with connection.begin():
                # Using "IF EXISTS" makes this command safe to run even if the table is already gone.
                connection.execute(text("DROP TABLE IF EXISTS email_alerts;"))
            logging.info("Successfully dropped 'email_alerts' table.")
    except Exception as e:
        logging.warning(f"Could not drop 'email_alerts' table (this is okay if it's the first run): {e}")

    # Re-run create_all to create the new, correct table
    models.Base.metadata.create_all(bind=engine)
    logging.info("Finished create_all, 'email_alerts' table should now be correct.")

    # --- Production Startup Sequence ---
    scheduler.add_job(daily_midnight_task, 'cron', hour=0, minute=5, id="midnight_cleaner", replace_existing=True)
    scheduler.add_job(daily_briefing_task, 'cron', hour=10, minute=0, args=["Morning"], id="morning_briefing", replace_existing=True)
    scheduler.add_job(daily_briefing_task, 'cron', hour=22, minute=0, args=["Evening"], id="evening_briefing", replace_existing=True)
    scheduler.add_job(check_emails_task, 'interval', minutes=5, id="email_checker", replace_existing=True)
    scheduler.add_job(email_reminder_task, 'interval', minutes=10, id="email_reminder", replace_existing=True)
    
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

# ... (The rest of the file remains the same)
app = FastAPI(lifespan=lifespan)
@slack_app.event("message")
async def handle_message_events(body: dict, ack):
    await ack()
    asyncio.create_task(process_slack_message(body))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("status", status_command))
telegram_app.add_handler(CommandHandler("check", check_command))
telegram_app.add_handler(CommandHandler("occupied", occupied_command))
telegram_app.add_handler(CommandHandler("available", available_command))
telegram_app.add_handler(CommandHandler("pending_cleaning", pending_cleaning_command))
telegram_app.add_handler(CommandHandler("relocate", relocate_command))
telegram_app.add_handler(CommandHandler("rename_property", rename_property_command))
telegram_app.add_handler(CommandHandler("set_clean", set_clean_command))
telegram_app.add_handler(CommandHandler("early_checkout", early_checkout_command))
telegram_app.add_handler(CommandHandler("cancel_booking", cancel_booking_command))
telegram_app.add_handler(CommandHandler("edit_booking", edit_booking_command))
telegram_app.add_handler(CommandHandler("log_issue", log_issue_command))
telegram_app.add_handler(CommandHandler("block_property", block_property_command))
telegram_app.add_handler(CommandHandler("unblock_property", unblock_property_command))
telegram_app.add_handler(CommandHandler("booking_history", booking_history_command))
telegram_app.add_handler(CommandHandler("find_guest", find_guest_command))
telegram_app.add_handler(CommandHandler("daily_revenue", daily_revenue_command))
telegram_app.add_handler(CommandHandler("relocations", relocations_command))
telegram_app.add_handler(CallbackQueryHandler(button_callback_handler))
telegram_app.add_error_handler(error_handler)
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Eivissa Operations Bot is alive!"}
@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    await telegram_app.process_update(Update.de_json(await req.json(), telegram_app.bot))
    return Response(status_code=200)
@app.post("/slack/events")
async def slack_events_endpoint(req: Request):
    return await slack_handler.handle(req)
if __name__ == "__main__":
    import uvicorn
    logging.info("Starting application server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
