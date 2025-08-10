# FILE: app/scheduled_tasks.py
# VERSION: 6.4 (Diagnostic Logging)
# ==============================================================================
# UPDATED: Added extensive logging to the `parse_email_in_background` function
# to trace every step of the AI summarization process. This will show us
# exactly where the process is failing in the Render logs.
# ==============================================================================
import logging
import datetime
import asyncio
from sqlalchemy.orm import Session
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from . import config, email_parser, models, telegram_client
from .utils.db_manager import db_session_manager

# --- Scheduler Instance ---
jobstores = {"default": SQLAlchemyJobStore(url=config.DATABASE_URL)}
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=config.TIMEZONE)


# --- Background AI Parsing Task ---
@db_session_manager
async def parse_email_in_background(alert_id: int, email_uid: str, *, db: Session):
    """
    This function is now called by the dedicated worker, not the scheduler.
    """
    logging.info(f"PARSER (Alert {alert_id}): Starting job.")
    try:
        logging.info(f"PARSER (Alert {alert_id}): Fetching email body for UID {email_uid}...")
        email_body = email_parser.fetch_email_body_by_uid(email_uid)
        
        if not email_body:
            logging.error(f"PARSER (Alert {alert_id}): FAILED to fetch email body.")
            db.query(models.EmailAlert).filter(models.EmailAlert.id == alert_id).update(
                {"summary": "Error: Could not fetch email body for parsing."}
            )
            db.commit()
            return

        logging.info(f"PARSER (Alert {alert_id}): Email body fetched successfully. Calling AI...")
        parsed_data = await email_parser.parse_booking_email_with_ai(email_body)
        logging.info(f"PARSER (Alert {alert_id}): AI call complete. Result category: {parsed_data.get('category')}")

        alert_to_update = db.query(models.EmailAlert).filter(models.EmailAlert.id == alert_id).first()
        if not alert_to_update:
            logging.error(f"PARSER (Alert {alert_id}): Could not find alert in DB to update after parsing.")
            return

        # Update the alert record with AI data
        if parsed_data and parsed_data.get("category") not in ["Parsing Failed", "Parsing Exception"]:
            alert_to_update.category = parsed_data.get("category", "Uncategorized")
            alert_to_update.summary = parsed_data.get("summary")
            alert_to_update.guest_name = parsed_data.get("guest_name")
            alert_to_update.property_code = parsed_data.get("property_code")
            alert_to_update.platform = parsed_data.get("platform")
            alert_to_update.reservation_number = parsed_data.get("reservation_number")
            alert_to_update.deadline = parsed_data.get("deadline")
        else:
            failure_summary = parsed_data.get("summary", "No summary provided by parser.")
            alert_to_update.summary = f"AI Parsing Failed: {failure_summary}"
            alert_to_update.category = "PARSING_FAILED"
            bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
            alert_text = telegram_client.format_parsing_failure_alert(failure_summary)
            await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES")

        logging.info(f"PARSER (Alert {alert_id}): Updating DB record...")
        db.commit()
        logging.info(f"PARSER (Alert {alert_id}): DB record updated.")

        # Edit the original Telegram message
        if alert_to_update.telegram_message_id and alert_to_update.status == models.EmailAlertStatus.OPEN:
            try:
                logging.info(f"PARSER (Alert {alert_id}): Attempting to edit Telegram message {alert_to_update.telegram_message_id}...")
                bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
                new_text, new_reply_markup = telegram_client.format_email_notification(alert_to_update)
                await bot.edit_message_text(
                    chat_id=config.TELEGRAM_TARGET_CHAT_ID,
                    message_id=alert_to_update.telegram_message_id,
                    text=new_text,
                    reply_markup=new_reply_markup,
                    parse_mode="Markdown"
                )
                logging.info(f"PARSER (Alert {alert_id}): Telegram message edited successfully.")
            except Exception as e:
                logging.error(f"PARSER (Alert {alert_id}): FAILED to edit Telegram message.", exc_info=True)

    except Exception as e:
        logging.error(f"PARSER (Alert {alert_id}): CRITICAL error in job.", exc_info=True)
        db.rollback()


# --- Scheduled Task Functions ---

@db_session_manager
async def check_emails_task(queue: asyncio.Queue, *, db: Session):
    """
    This task is a fast "producer".
    """
    logging.info("PRODUCER: Running email check...")
    try:
        unread_emails_metadata = email_parser.fetch_unread_email_metadata()
        if not unread_emails_metadata:
            logging.info("PRODUCER: No new emails found.")
            return

        logging.info(f"PRODUCER: Found {len(unread_emails_metadata)} emails. Adding to queue.")
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

        for metadata in unread_emails_metadata:
            with db.begin_nested():
                try:
                    new_alert = models.EmailAlert(
                        category="New Email",
                        summary=f"Subject: {metadata['subject']}",
                        email_uid=metadata['uid']
                    )
                    db.add(new_alert)
                    db.flush()

                    notification_text, reply_markup = telegram_client.format_email_notification(new_alert)
                    sent_message = await telegram_client.send_telegram_message(
                        bot,
                        notification_text,
                        topic_name="EMAILS",
                        reply_markup=reply_markup,
                    )

                    if sent_message:
                        new_alert.telegram_message_id = sent_message.message_id
                        if email_parser.mark_email_as_read_by_uid(metadata['uid']):
                            await queue.put((new_alert.id, metadata['uid']))
                            logging.info(f"PRODUCER: Job for alert {new_alert.id} (UID {metadata['uid']}) added to queue.")
                        else:
                            raise Exception(f"Failed to mark email UID {metadata['uid']} as read.")
                    else:
                        raise Exception("Failed to send Telegram notification for new email.")
                except Exception as e:
                    logging.error(f"PRODUCER: Failed to queue job for email UID {metadata.get('uid')}.", exc_info=e)
        db.commit()
    except Exception as e:
        logging.error("PRODUCER: Critical error in check_emails_task.", exc_info=e)

# ... (rest of the file is unchanged)
@db_session_manager
async def unhandled_issue_reminder_task(*, db: Session):
    logging.info("Checking for unhandled issues for 15-minute reminder...")
    now = datetime.datetime.now(datetime.timezone.utc)
    reminder_threshold = now - datetime.timedelta(minutes=15)
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    open_alerts = db.query(models.EmailAlert).filter(
        models.EmailAlert.status == "OPEN",
        models.EmailAlert.reminders_sent == 0,
        models.EmailAlert.created_at <= reminder_threshold
    ).all()
    for alert in open_alerts:
        try:
            reminder_text = telegram_client.format_email_reminder()
            await bot.send_message(
                chat_id=config.TELEGRAM_TARGET_CHAT_ID,
                text=reminder_text,
                message_thread_id=config.TELEGRAM_TOPIC_IDS.get("EMAILS"),
                reply_to_message_id=alert.telegram_message_id,
                parse_mode="Markdown",
            )
            alert.reminders_sent = 1
            logging.info(f"Sent 15-min reminder for email alert {alert.id}")
        except Exception as e:
            logging.error(f"Could not send reminder for alert {alert.id}", exc_info=e)
    pending_relocations = db.query(models.Booking).filter(
        models.Booking.status == "PENDING_RELOCATION",
        models.Booking.reminders_sent == 0,
        models.Booking.created_at <= reminder_threshold
    ).all()
    if pending_relocations:
        try:
            alert_text = telegram_client.format_unresolved_relocations_alert(pending_relocations)
            await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES")
            for booking in pending_relocations:
                booking.reminders_sent = 1
            logging.info(f"Sent 15-min reminder for {len(pending_relocations)} pending relocations.")
        except Exception as e:
            logging.error("Could not send pending relocation reminder.", exc_info=e)
    db.commit()

async def send_checkout_reminder(guest_name: str, property_code: str, checkout_date: str):
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    report = telegram_client.format_checkout_reminder_alert(guest_name, property_code, checkout_date)
    await telegram_client.send_telegram_message(bot, report, topic_name="ISSUES")
    logging.info(f"Sent checkout reminder for {guest_name} in {property_code}.")

@db_session_manager
async def daily_briefing_task(time_of_day: str, *, db: Session):
    logging.info(f"Running {time_of_day} briefing...")
    occupied = db.query(models.Property).filter(models.Property.status == "OCCUPIED").count()
    pending = db.query(models.Property).filter(models.Property.status == "PENDING_CLEANING").count()
    maintenance = db.query(models.Property).filter(models.Property.status == "MAINTENANCE").count()
    available = db.query(models.Property).filter(models.Property.status == "AVAILABLE").count()
    report = telegram_client.format_daily_briefing(time_of_day, occupied, pending, maintenance, available)
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    await telegram_client.send_telegram_message(bot, report, topic_name="GENERAL")

@db_session_manager
async def daily_midnight_task(*, db: Session):
    logging.info("Running midnight task...")
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    try:
        props_to_make_available = db.query(models.Property).filter(
            models.Property.status == "PENDING_CLEANING"
        ).all()
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
        await telegram_client.send_telegram_message(bot, summary_text, topic_name="GENERAL")
        logging.info(f"Midnight Task: Set {len(prop_codes)} properties to AVAILABLE.")
    except Exception as e:
        logging.error("Error during midnight task", exc_info=e)
        await telegram_client.send_telegram_message(
            bot, f"🚨 Error in scheduled midnight task: {e}", topic_name="ISSUES"
        )
