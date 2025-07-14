# FILE: main.py
# ==============================================================================
# FINAL VERSION: Implements the complete, interactive Email Watchdog feature
# with database logging, actionable buttons, and a reminder system.
# This file is complete with no placeholders.
# ==============================================================================

import datetime
import re
import asyncio
import time
from contextlib import asynccontextmanager
from difflib import get_close_matches
from fastapi import FastAPI, Request, Response
from sqlalchemy.orm import Session, joinedload
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
import email_parser  # Import the new email parser
from database import get_db, engine

# --- Database Initialization ---
models.Base.metadata.create_all(bind=engine)

# --- Application Instances & Persistent Scheduler ---
jobstores = {
    'default': SQLAlchemyJobStore(url=config.DATABASE_URL)
}
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=config.TIMEZONE)

slack_app = AsyncApp(token=config.SLACK_BOT_TOKEN, signing_secret=config.SLACK_SIGNING_SECRET)
telegram_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
slack_handler = AsyncSlackRequestHandler(slack_app)

# --- DYNAMIC HELP COMMAND MANUAL ---
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

# --- Scheduled Tasks ---
async def check_emails_task():
    """Fetches, parses, and logs unread emails, then sends an interactive alert."""
    print("Running email check...")
    bot = telegram_app.bot
    db = next(get_db())
    try:
        unread_emails = email_parser.fetch_unread_emails()
        if not unread_emails:
            print("No new emails found.")
            return
            
        print(f"Found {len(unread_emails)} new emails to process.")
        for email_data in unread_emails:
            parsed_data = await email_parser.parse_booking_email_with_ai(email_data["body"])
            
            if parsed_data and parsed_data.get("category") not in ["Parsing Failed", "Parsing Exception"]:
                # 1. Create the alert record in the database
                new_alert = models.EmailAlert(category=parsed_data.get("category", "Uncategorized"))
                db.add(new_alert)
                db.commit() # Commit to get the new_alert.id

                # 2. Format the message with the button
                notification_text, reply_markup = telegram_client.format_email_notification(parsed_data, new_alert.id)
                
                # 3. Send the message and get its ID
                sent_message = await telegram_client.send_telegram_message(bot, notification_text, topic_name="EMAILS", reply_markup=reply_markup)
                
                # 4. Save the Telegram message ID to our database record
                if sent_message:
                    new_alert.telegram_message_id = sent_message.message_id
                    db.commit()
    finally:
        db.close()

async def email_reminder_task():
    """Checks for open email alerts and sends reminders."""
    print("Checking for open email alerts...")
    bot = telegram_app.bot
    db = next(get_db())
    try:
        open_alerts = db.query(models.EmailAlert).filter(models.EmailAlert.status == "OPEN").all()
        if not open_alerts:
            return

        print(f"Found {len(open_alerts)} open alerts. Sending reminders.")
        for alert in open_alerts:
            # Fetch the original message to include in the reminder
            try:
                original_message = await bot.forward_message(
                    chat_id=config.TELEGRAM_TARGET_CHAT_ID,
                    from_chat_id=config.TELEGRAM_TARGET_CHAT_ID,
                    message_id=alert.telegram_message_id
                )
                reminder_text = telegram_client.format_email_reminder("See original alert above.")
                await telegram_client.send_telegram_message(bot, reminder_text, topic_name="EMAILS")
                await original_message.delete() # Delete the forwarded message to keep chat clean
            except Exception as e:
                print(f"Could not send reminder for alert {alert.id}: {e}")
    finally:
        db.close()

async def send_checkout_reminder(guest_name: str, property_code: str, checkout_date: str):
    bot = telegram_app.bot
    report = telegram_client.format_checkout_reminder_alert(guest_name, property_code, checkout_date)
    await telegram_client.send_telegram_message(bot, report, topic_name="ISSUES")
    print(f"Sent checkout reminder for {guest_name} in {property_code}.")

async def daily_briefing_task(time_of_day: str):
    print(f"Running {time_of_day} briefing...")
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
    db = next(get_db())
    bot = telegram_app.bot
    try:
        props_to_make_available = db.query(models.Property).filter(models.Property.status == "PENDING_CLEANING").all()
        if not props_to_make_available:
            print("Midnight Task: No properties were pending cleaning.")
            return
        prop_codes = [prop.code for prop in props_to_make_available]
        for prop in props_to_make_available:
            prop.status = "AVAILABLE"
        db.commit()
        summary_text = (f"Automated Midnight Task (00:05 Local Time)\n\n"
                        f"🧹 The following {len(prop_codes)} properties have been cleaned and are now *AVAILABLE* for the new day:\n\n"
                        f"`{', '.join(sorted(prop_codes))}`")
        await telegram_client.send_telegram_message(bot, summary_text, topic_name="GENERAL")
        print(f"Midnight Task: Set {len(prop_codes)} properties to AVAILABLE.")
    except Exception as e:
        print(f"Error during midnight task: {e}")
        await telegram_client.send_telegram_message(bot, f"🚨 Error in scheduled midnight task: {e}", topic_name="ISSUES")
    finally:
        db.close()

# --- Core Logic Functions (Slack) ---
async def process_slack_message(payload: dict):
    try:
        db = next(get_db())
        try:
            event = payload.get("event", {})
            user_id = event.get('user')
            if user_id != config.SLACK_USER_ID_OF_LIST_POSTER: return

            message_text = event.get('text', '')
            channel_id = event.get('channel')
            
            message_ts = float(event.get('ts', time.time()))
            list_date_str = datetime.date.fromtimestamp(message_ts).isoformat()

            print(f"MESSAGE RECEIVED from {user_id} in channel {channel_id}: {message_text[:50]}...")
            bot = telegram_app.bot
            
            all_prop_codes = [p.code for p in db.query(models.Property.code).all()]

            if "great reset" in message_text.lower():
                for job in scheduler.get_jobs():
                    if job.id.startswith("checkout_reminder_") or job.id.startswith("email_reminder_"):
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
                    prop_code = booking_data["property_code"]
                    guest_name = booking_data["guest_name"]

                    if guest_name in ["N/A", "Unknown Guest"]:
                        print(f"Skipping booking for {prop_code} due to missing guest name.")
                        continue
                    if prop_code == "UNKNOWN": continue

                    if prop_code not in all_prop_codes:
                        suggestions = get_close_matches(prop_code, all_prop_codes, n=3, cutoff=0.7)
                        original_line = next((line for line in message_text.split('\n') if line.strip().startswith(prop_code)), message_text)
                        alert_text = telegram_client.format_invalid_code_alert(prop_code, original_line, suggestions)
                        await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES")
                        continue

                    prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
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
                if processed_bookings:
                    summary_text = telegram_client.format_daily_list_summary(processed_bookings, [], [], list_date_str)
                    await telegram_client.send_telegram_message(bot, summary_text, topic_name="GENERAL")

            elif channel_id == config.SLACK_CLEANING_CHANNEL_ID:
                properties_to_process = await slack_parser.parse_cleaning_list_with_ai(message_text)
                success_codes = []
                warnings = []
                for prop_code in properties_to_process:
                    if prop_code not in all_prop_codes:
                        warnings.append(f"`{prop_code}`: Code not found in database (check for typo).")
                        continue
                    
                    prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
                    if prop.status == "OCCUPIED":
                        prop.status = "PENDING_CLEANING"
                        success_codes.append(prop.code)
                        booking_to_update = db.query(models.Booking).filter(models.Booking.property_id == prop.id, models.Booking.status == "Active").order_by(models.Booking.id.desc()).first()
                        if booking_to_update:
                            booking_to_update.checkout_date = (datetime.date.fromisoformat(list_date_str) + datetime.timedelta(days=1)).isoformat()
                            booking_to_update.status = "Departed"
                    else:
                        warnings.append(f"`{prop_code}`: Not processed, status was already `{prop.status}`.")
                
                db.commit()
                receipt_message = telegram_client.format_cleaning_list_receipt(success_codes, warnings)
                await telegram_client.send_telegram_message(bot, receipt_message, topic_name="GENERAL")
        finally:
            db.close()
    except Exception as e:
        print(f"!!!!!! CRITICAL ERROR IN SLACK PROCESSOR !!!!!!")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

# --- Register Slack Handler ---
@slack_app.event("message")
async def handle_message_events(body: dict, ack):
    await ack()
    asyncio.create_task(process_slack_message(body))

# --- Telegram Command Handlers ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text=telegram_client.format_help_manual(COMMANDS_HELP_MANUAL), parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        total = db.query(models.Property).count()
        occupied = db.query(models.Property).filter(models.Property.status == "OCCUPIED").count()
        available = db.query(models.Property).filter(models.Property.status == "AVAILABLE").count()
        pending = db.query(models.Property).filter(models.Property.status == "PENDING_CLEANING").count()
        maintenance = db.query(models.Property).filter(models.Property.status == "MAINTENANCE").count()
        report = telegram_client.format_status_report(total, occupied, available, pending, maintenance)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/check [PROPERTY_CODE]`")
        return
    db = next(get_db())
    try:
        prop_code = context.args[0].upper()
        prop = db.query(models.Property).options(joinedload(models.Property.issues)).filter(models.Property.code == prop_code).first()
        active_booking = None
        if prop and prop.status != "AVAILABLE":
            active_booking = db.query(models.Booking).filter(models.Booking.property_id == prop.id).order_by(models.Booking.id.desc()).first()
        report = telegram_client.format_property_check(prop, active_booking, prop.issues if prop else [])
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def occupied_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        props = db.query(models.Property).filter(models.Property.status == "OCCUPIED").order_by(models.Property.code).all()
        report = telegram_client.format_occupied_list(props)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def available_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        props = db.query(models.Property).filter(models.Property.status == "AVAILABLE").order_by(models.Property.code).all()
        report = telegram_client.format_available_list(props)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def early_checkout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/early_checkout [PROPERTY_CODE]`")
        return
    db = next(get_db())
    try:
        prop_code = context.args[0].upper()
        prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
        if not prop:
            report = telegram_client.format_simple_error(f"Property `{prop_code}` not found.")
        elif prop.status != "OCCUPIED":
            report = telegram_client.format_simple_error(f"Property `{prop_code}` is currently `{prop.status}`, not OCCUPIED.")
        else:
            prop.status = "PENDING_CLEANING"
            db.commit()
            report = telegram_client.format_simple_success(f"Property `{prop_code}` has been checked out and is now *PENDING_CLEANING*.")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def set_clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/set_clean [PROPERTY_CODE]`")
        return
    db = next(get_db())
    try:
        prop_code = context.args[0].upper()
        prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
        if not prop:
            report = telegram_client.format_simple_error(f"Property `{prop_code}` not found.")
        elif prop.status != "PENDING_CLEANING":
            report = telegram_client.format_simple_error(f"Property `{prop_code}` is currently `{prop.status}`, not PENDING_CLEANING.")
        else:
            prop.status = "AVAILABLE"
            db.commit()
            report = telegram_client.format_simple_success(f"Property `{prop_code}` has been manually set to *AVAILABLE*.")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def rename_property_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/rename_property [OLD_CODE] [NEW_CODE]`")
        return
    db = next(get_db())
    try:
        old_code, new_code = context.args[0].upper(), context.args[1].upper()
        
        if db.query(models.Property).filter(models.Property.code == new_code).first():
            report = telegram_client.format_simple_error(f"Cannot rename: Property `{new_code}` already exists.")
            await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
            return

        prop_to_rename = db.query(models.Property).filter(models.Property.code == old_code).first()
        if not prop_to_rename:
            report = telegram_client.format_simple_error(f"Property `{old_code}` not found.")
        else:
            prop_to_rename.code = new_code
            db.query(models.Booking).filter(models.Booking.property_code == old_code).update({"property_code": new_code})
            db.commit()
            report = telegram_client.format_simple_success(f"Property `{old_code}` has been successfully renamed to `{new_code}`.")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def relocate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 3:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/relocate [FROM_CODE] [TO_CODE] [YYYY-MM-DD]`")
        return
    db = next(get_db())
    try:
        from_code, to_code, checkout_date_str = context.args[0].upper(), context.args[1].upper(), context.args[2]
        try:
            checkout_date = datetime.date.fromisoformat(checkout_date_str)
        except ValueError:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ Error: Invalid date format. Please use `YYYY-MM-DD`.")
            return
        to_prop = db.query(models.Property).filter(models.Property.code == to_code).first()
        if not to_prop or to_prop.status != "AVAILABLE":
            report = telegram_client.format_simple_error(f"Property `{to_code}` is not available for relocation.")
        else:
            booking_to_relocate = db.query(models.Booking).filter(models.Booking.property_code == from_code, models.Booking.status == "PENDING_RELOCATION").order_by(models.Booking.id.desc()).first()
            if not booking_to_relocate:
                report = telegram_client.format_simple_error(f"No booking found pending relocation for `{from_code}`.")
            else:
                log_entry = models.Relocation(
                    booking_id=booking_to_relocate.id, guest_name=booking_to_relocate.guest_name,
                    original_property_code=from_code, new_property_code=to_code
                )
                db.add(log_entry)
                to_prop.status = "OCCUPIED"
                booking_to_relocate.status = "Active"
                booking_to_relocate.property_id = to_prop.id
                booking_to_relocate.property_code = to_prop.code
                booking_to_relocate.checkout_date = checkout_date
                reminder_datetime = datetime.datetime.combine(checkout_date - datetime.timedelta(days=1), datetime.time(18, 0))
                scheduler.add_job(
                    send_checkout_reminder, 'date', run_date=reminder_datetime,
                    args=[booking_to_relocate.guest_name, to_code, checkout_date_str],
                    id=f"checkout_reminder_{booking_to_relocate.id}", replace_existing=True
                )
                db.commit()
                report = telegram_client.format_simple_success(
                    f"Relocation Successful!\n"
                    f"Guest *{booking_to_relocate.guest_name}* has been moved to `{to_code}`.\n"
                    f"A checkout reminder has been scheduled for *{reminder_datetime.strftime('%Y-%m-%d %H:%M')}*."
                )
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def pending_cleaning_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        props = db.query(models.Property).filter(models.Property.status == "PENDING_CLEANING").order_by(models.Property.code).all()
        report = telegram_client.format_pending_cleaning_list(props)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def cancel_booking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/cancel_booking [PROPERTY_CODE]`")
        return
    db = next(get_db())
    try:
        prop_code = context.args[0].upper()
        prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
        if not prop:
            report = telegram_client.format_simple_error(f"Property `{prop_code}` not found.")
        elif prop.status != "OCCUPIED":
            report = telegram_client.format_simple_error(f"Property `{prop_code}` is not occupied.")
        else:
            booking = db.query(models.Booking).filter(models.Booking.property_id == prop.id, models.Booking.status == "Active").first()
            if booking:
                booking.status = "Cancelled"
                prop.status = "AVAILABLE"
                db.commit()
                report = telegram_client.format_simple_success(f"Booking for *{booking.guest_name}* in `{prop_code}` has been cancelled. The property is now available.")
            else:
                report = telegram_client.format_simple_error(f"No active booking found for `{prop_code}`.")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def edit_booking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/edit_booking [CODE] [field] [new_value]`\nFields: `guest_name`, `due_payment`, `platform`")
        return
    db = next(get_db())
    try:
        prop_code, field, new_value = context.args[0].upper(), context.args[1].lower(), " ".join(context.args[2:])
        prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
        if not prop or prop.status != "OCCUPIED":
            report = telegram_client.format_simple_error(f"Property `{prop_code}` not found or is not occupied.")
        else:
            booking = db.query(models.Booking).filter(models.Booking.property_id == prop.id, models.Booking.status == "Active").first()
            if not booking:
                report = telegram_client.format_simple_error(f"No active booking found for `{prop_code}`.")
            elif field not in ["guest_name", "due_payment", "platform"]:
                report = telegram_client.format_simple_error(f"Invalid field `{field}`. Use `guest_name`, `due_payment`, or `platform`.")
            else:
                setattr(booking, field, new_value)
                db.commit()
                report = telegram_client.format_simple_success(f"Booking for `{prop_code}` updated: `{field}` is now *{new_value}*.")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def log_issue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/log_issue [CODE] [description]`")
        return
    db = next(get_db())
    try:
        prop_code, description = context.args[0].upper(), " ".join(context.args[1:])
        prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
        if not prop:
            report = telegram_client.format_simple_error(f"Property `{prop_code}` not found.")
        else:
            new_issue = models.Issue(property_id=prop.id, description=description)
            db.add(new_issue)
            db.commit()
            report = telegram_client.format_simple_success(f"New issue logged for `{prop_code}`: _{description}_")
            await telegram_client.send_telegram_message(context.bot, report, topic_name="ISSUES")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="Issue logged successfully in the #issues topic.")
            return
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def block_property_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/block_property [CODE] [reason]`")
        return
    db = next(get_db())
    try:
        prop_code, reason = context.args[0].upper(), " ".join(context.args[1:])
        prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
        if not prop:
            report = telegram_client.format_simple_error(f"Property `{prop_code}` not found.")
        elif prop.status == "OCCUPIED":
            report = telegram_client.format_simple_error(f"Cannot block `{prop_code}`, it is currently occupied.")
        else:
            prop.status = "MAINTENANCE"
            prop.notes = reason
            db.commit()
            report = telegram_client.format_simple_success(f"Property `{prop_code}` is now blocked for *MAINTENANCE*.\nReason: _{reason}_")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def unblock_property_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/unblock_property [CODE]`")
        return
    db = next(get_db())
    try:
        prop_code = context.args[0].upper()
        prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
        if not prop:
            report = telegram_client.format_simple_error(f"Property `{prop_code}` not found.")
        elif prop.status != "MAINTENANCE":
            report = telegram_client.format_simple_error(f"Property `{prop_code}` is not under maintenance.")
        else:
            prop.status = "AVAILABLE"
            prop.notes = None
            db.commit()
            report = telegram_client.format_simple_success(f"Property `{prop_code}` has been unblocked and is now *AVAILABLE*.")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def booking_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/booking_history [CODE]`")
        return
    db = next(get_db())
    try:
        prop_code = context.args[0].upper()
        bookings = db.query(models.Booking).filter(models.Booking.property_code == prop_code).order_by(models.Booking.checkin_date.desc()).limit(5).all()
        report = telegram_client.format_booking_history(prop_code, bookings)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def find_guest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Usage: `/find_guest [GUEST_NAME]`")
        return
    db = next(get_db())
    try:
        guest_name = " ".join(context.args)
        results = db.query(models.Booking).options(joinedload(models.Booking.property)).filter(models.Booking.guest_name.ilike(f"%{guest_name}%"), models.Booking.status == 'Active').all()
        report = telegram_client.format_find_guest_results(results)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def daily_revenue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        date_str = context.args[0] if context.args else datetime.date.today().isoformat()
        target_date = datetime.date.fromisoformat(date_str)
        bookings = db.query(models.Booking).filter(models.Booking.checkin_date == target_date).all()
        total_revenue = 0.0
        for b in bookings:
            numbers = re.findall(r'\d+\.?\d*', b.due_payment)
            if numbers:
                total_revenue += float(numbers[0])
        report = telegram_client.format_daily_revenue_report(date_str, total_revenue, len(bookings))
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    except (ValueError, IndexError):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="Invalid date format. Please use `YYYY-MM-DD`.")
    finally:
        db.close()

async def relocations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        query = db.query(models.Relocation).order_by(models.Relocation.relocated_at.desc())
        if context.args:
            prop_code = context.args[0].upper()
            query = query.filter((models.Relocation.original_property_code == prop_code) | (models.Relocation.new_property_code == prop_code))
        history = query.limit(10).all()
        report = telegram_client.format_relocation_history(history)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=report, parse_mode='Markdown')
    finally:
        db.close()

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, *data = query.data.split(":")
    
    if action == "show_available":
        db = next(get_db())
        try:
            props = db.query(models.Property).filter(models.Property.status == "AVAILABLE").order_by(models.Property.code).all()
            report = telegram_client.format_available_list(props, for_relocation_from=data[0])
            await query.edit_message_text(text=f"{query.message.text}\n\n{report}", parse_mode='Markdown')
        finally:
            db.close()
            
    elif action == "swap_relocation":
        db = next(get_db())
        try:
            first_booking_id, second_booking_id = data[0], data[1]
            first_booking = db.query(models.Booking).filter(models.Booking.id == first_booking_id).first()
            second_booking = db.query(models.Booking).filter(models.Booking.id == second_booking_id).first()
            if not first_booking or not second_booking:
                await query.edit_message_text(text=f"{query.message.text}\n\n❌ Error: Could not find original bookings to swap.", parse_mode='Markdown')
                return
            first_booking.status = "PENDING_RELOCATION"
            second_booking.status = "Active"
            db.commit()
            new_text = (
                f"✅ *Swap Successful!*\n\n"
                f"*{second_booking.guest_name}* is now the active guest in `{second_booking.property_code}`.\n"
                f"*{first_booking.guest_name}* is now pending relocation.\n\n"
                f"To resolve, use `/relocate {first_booking.property_code} [new_room] [YYYY-MM-DD]`."
            )
            await query.edit_message_text(text=new_text, parse_mode='Markdown')
        finally:
            db.close()

    elif action == "handle_email":
        db = next(get_db())
        try:
            alert_id = int(data[0])
            alert = db.query(models.EmailAlert).filter(models.EmailAlert.id == alert_id).first()
            if alert and alert.status == "OPEN":
                alert.status = "HANDLED"
                alert.handled_by = query.from_user.full_name
                alert.handled_at = datetime.datetime.now(datetime.timezone.utc)
                db.commit()
                
                # Edit the original message to show it's handled
                new_text = telegram_client.format_handled_email_notification(query.message.text_markdown, query.from_user.full_name)
                await query.edit_message_text(text=new_text, parse_mode='Markdown', reply_markup=None)
            else:
                # If already handled, just inform the user without changing the message
                await query.answer("This alert has already been handled.", show_alert=True)
        finally:
            db.close()

# --- App Lifecycle and Registration ---
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(daily_midnight_task, 'cron', hour=0, minute=5, id="midnight_cleaner", replace_existing=True)
    scheduler.add_job(daily_briefing_task, 'cron', hour=10, minute=0, args=["Morning"], id="morning_briefing", replace_existing=True)
    scheduler.add_job(daily_briefing_task, 'cron', hour=22, minute=0, args=["Evening"], id="evening_briefing", replace_existing=True)
    scheduler.add_job(check_emails_task, 'interval', minutes=5, id="email_checker", replace_existing=True)
    scheduler.add_job(email_reminder_task, 'interval', minutes=10, id="email_reminder", replace_existing=True)
    
    scheduler.start()
    print("APScheduler started with all tasks scheduled.")
    await telegram_app.initialize()
    await telegram_app.start()
    webhook_url = f"{config.WEBHOOK_URL}/telegram/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url)
    print(f"Telegram webhook set to: {webhook_url}")
    yield
    await telegram_app.stop()
    await telegram_app.shutdown()
    scheduler.shutdown()
    print("Telegram webhook deleted and scheduler shut down.")

app = FastAPI(lifespan=lifespan)

@app.post("/telegram/webhook")
async def telegram_webhook(req: Request):
    await telegram_app.process_update(Update.de_json(await req.json(), telegram_app.bot))
    return Response(status_code=200)

@app.post("/slack/events")
async def slack_events_endpoint(req: Request):
    return await slack_handler.handle(req)

if __name__ == "__main__":
    import uvicorn
    print("Starting application server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
