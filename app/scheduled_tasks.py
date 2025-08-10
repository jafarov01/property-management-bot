# FILE: app/scheduled_tasks.py
# VERSION: 6.0 (Refactored for Immediate-Notify & Spec Alignment)
# ==============================================================================
# UPDATED: This file has been heavily refactored to align with the spec.
#
# 1. `check_emails_task` now implements the "immediate-notify-first" pattern.
#    It quickly fetches metadata, creates a basic alert, notifies Telegram,
#    and then triggers a background task for heavy AI parsing.
# 2. A new background task, `parse_email_in_background`, has been created to
#    handle the AI parsing and update the original alert.
# 3. `email_reminder_task` is now `unhandled_issue_reminder_task` and sends a
#    single reminder after 15 minutes for BOTH open emails and pending
#    relocations, as per the specification.
# 4. The email check interval is now more frequent to improve responsiveness.
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
    A background task to perform heavy AI parsing on an email.
    It fetches the email body, calls the AI, and updates the existing alert record.
    """
    logging.info(f"Starting background parsing for alert_id: {alert_id}")
    try:
        email_body = email_parser.fetch_email_body_by_uid(email_uid)
        if not email_body:
            logging.error(f"Could not fetch email body for UID {email_uid}. Aborting parse.")
            db.query(models.EmailAlert).filter(models.EmailAlert.id == alert_id).update(
                {"summary": "Error: Could not fetch email body for parsing."}
            )
            db.commit()
            return

        parsed_data = await email_parser.parse_booking_email_with_ai(email_body)

        alert_to_update = db.query(models.EmailAlert).filter(models.EmailAlert.id == alert_id).first()
        if not alert_to_update:
            logging.error(f"Could not find alert {alert_id} to update after parsing.")
            return

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
            # Optionally send a failure alert to the #issues topic
            bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
            alert_text = telegram_client.format_parsing_failure_alert(failure_summary)
            await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES")

        db.commit()
        logging.info(f"Successfully parsed and updated alert_id: {alert_id}")

    except Exception as e:
        logging.error(f"Critical error during background parsing for alert {alert_id}", exc_info=e)
        db.rollback()


# --- Scheduled Task Functions ---

@db_session_manager
async def check_emails_task(*, db: Session):
    """
    Periodically fetches unread email metadata and creates initial alerts.
    This is the first step in the "immediate-notify-first" workflow.
    """
    logging.info("Running email metadata check...")
    try:
        unread_emails_metadata = email_parser.fetch_unread_email_metadata()
        if not unread_emails_metadata:
            return

        logging.info(f"Found {len(unread_emails_metadata)} new emails to process.")
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

        for metadata in unread_emails_metadata:
            with db.begin_nested():
                try:
                    # 1. Create a basic alert record immediately with minimal info
                    new_alert = models.EmailAlert(
                        category="New Email",
                        summary=f"Subject: {metadata['subject']}",
                        # Store the UID to fetch the body later
                        email_uid=metadata['uid']
                    )
                    db.add(new_alert)
                    db.flush()  # Assigns an ID to new_alert

                    # 2. Send the initial, interactive notification to Telegram
                    notification_text, reply_markup = telegram_client.format_email_notification(new_alert)
                    sent_message = await telegram_client.send_telegram_message(
                        bot,
                        notification_text,
                        topic_name="EMAILS",
                        reply_markup=reply_markup,
                    )

                    # 3. If notification is successful, update the alert and mark email as read
                    if sent_message:
                        new_alert.telegram_message_id = sent_message.message_id
                        # Mark email as read ONLY after DB and Telegram success
                        if email_parser.mark_email_as_read_by_uid(metadata['uid']):
                            logging.info(f"Successfully marked email UID {metadata['uid']} as read.")
                        else:
                            # If marking as read fails, we must roll back to retry this email later.
                            raise Exception(f"Failed to mark email UID {metadata['uid']} as read.")
                    else:
                        raise Exception("Failed to send Telegram notification for new email.")

                    # 4. Schedule the heavy AI parsing to run in the background
                    asyncio.create_task(parse_email_in_background(new_alert.id, metadata['uid']))

                except Exception as e:
                    logging.error(f"Failed to process email UID {metadata.get('uid')}. It will be retried.", exc_info=e)
                    # The `with db.begin_nested()` block will automatically roll back on any exception.
                    # The email remains unread and will be picked up on the next run.
        db.commit()
    except Exception as e:
        logging.error("Critical error in check_emails_task.", exc_info=e)


@db_session_manager
async def unhandled_issue_reminder_task(*, db: Session):
    """
    Checks for any open issues (Email Alerts or Pending Relocations) older than
    15 minutes and sends a single, one-time reminder.
    """
    logging.info("Checking for unhandled issues for 15-minute reminder...")
    now = datetime.datetime.now(datetime.timezone.utc)
    reminder_threshold = now - datetime.timedelta(minutes=15)
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    # --- Check for Open Email Alerts ---
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

    # --- Check for Pending Relocations ---
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
    """Sends a high-priority checkout reminder for a relocated guest."""
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    report = telegram_client.format_checkout_reminder_alert(guest_name, property_code, checkout_date)
    await telegram_client.send_telegram_message(bot, report, topic_name="ISSUES")
    logging.info(f"Sent checkout reminder for {guest_name} in {property_code}.")


@db_session_manager
async def daily_briefing_task(time_of_day: str, *, db: Session):
    """Sends a daily status briefing to the GENERAL topic."""
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
    """Sets all PENDING_CLEANING properties to AVAILABLE for the new day."""
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
