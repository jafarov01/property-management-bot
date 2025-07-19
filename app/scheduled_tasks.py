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
