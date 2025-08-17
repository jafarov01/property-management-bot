# FILE: app/scheduled_tasks.py
from dotenv import load_dotenv
load_dotenv()
import logging
import datetime
import asyncio
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import config, email_parser, models, telegram_client
from .utils.db_manager import db_session_manager

scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)

# --- Background AI Parsing Task ---
@db_session_manager
async def parse_email_in_background(alert_id: int, email_uid: str, *, db: AsyncSession):
    """This function is now called by the dedicated worker, not the scheduler."""
    logging.info(f"PARSER (Alert {alert_id}): Starting job.")
    try:
        result = await db.execute(select(models.EmailAlert).filter(models.EmailAlert.id == alert_id))
        alert_to_update = result.scalar_one_or_none()
        
        if not alert_to_update:
            logging.error(f"PARSER (Alert {alert_id}): CRITICAL - Could not find alert in DB to update after parsing. The job will be dropped.")
            return

        logging.info(f"PARSER (Alert {alert_id}): Fetching email body for UID {email_uid}...")
        email_body = email_parser.fetch_email_body_by_uid(email_uid)
        
        if not email_body:
            logging.error(f"PARSER (Alert {alert_id}): FAILED to fetch email body.")
            alert_to_update.summary="Error: Could not fetch email body for parsing."
            await db.commit()
            return

        logging.info(f"PARSER (Alert {alert_id}): Email body fetched successfully. Calling AI...")
        parsed_data = await email_parser.parse_booking_email_with_ai(email_body)
        logging.info(f"PARSER (Alert {alert_id}): AI call complete. Result category: {parsed_data.get('category')}")

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
        await db.commit()
        logging.info(f"PARSER (Alert {alert_id}): DB record updated.")

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
        await db.rollback()

# --- Scheduled Task Functions ---

@db_session_manager
async def check_emails_task(queue: asyncio.Queue, *, db: AsyncSession):
    """This task is a fast "producer". It now ensures commits before queueing."""
    logging.info("PRODUCER: Running email check...")
    try:
        unread_emails_metadata = email_parser.fetch_unread_email_metadata()
        if not unread_emails_metadata:
            logging.info("PRODUCER: No new emails found.")
            return

        logging.info(f"PRODUCER: Found {len(unread_emails_metadata)} emails. Processing...")
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        
        alerts_to_queue = []
        for metadata in unread_emails_metadata:
            new_alert = models.EmailAlert(
                category="New Email",
                summary=f"Subject: {metadata['subject']}",
                email_uid=metadata['uid']
            )
            db.add(new_alert)
            alerts_to_queue.append((new_alert, metadata['uid']))

        await db.commit()
        logging.info(f"PRODUCER: Committed {len(alerts_to_queue)} new alert records to the database.")

        for alert, uid in alerts_to_queue:
            try:
                await db.refresh(alert)
                notification_text, reply_markup = telegram_client.format_email_notification(alert)
                sent_message = await telegram_client.send_telegram_message(
                    bot, notification_text, topic_name="EMAILS", reply_markup=reply_markup
                )
                if sent_message:
                    alert.telegram_message_id = sent_message.message_id
                    await db.commit()
                    if email_parser.mark_email_as_read_by_uid(uid):
                        await queue.put((alert.id, uid))
                        logging.info(f"PRODUCER: Job for alert {alert.id} (UID {uid}) added to queue.")
                    else:
                        raise Exception(f"Failed to mark email UID {uid} as read.")
                else:
                    raise Exception("Failed to send Telegram notification for new email.")
            except Exception as e:
                logging.error(f"PRODUCER: Failed to queue job for email UID {uid}.", exc_info=e)
                
    except Exception as e:
        logging.error("PRODUCER: Critical error in check_emails_task.", exc_info=e)


@db_session_manager
async def unhandled_issue_reminder_task(*, db: AsyncSession):
    """Checks for open issues older than 15 minutes and sends a consolidated reminder."""
    logging.info("Checking for unhandled issues for 15-minute reminder...")
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    
    # --- Consolidated Email Alert Reminder ---
    fifteen_minutes_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
    stmt = select(models.EmailAlert).where(
        models.EmailAlert.status == models.EmailAlertStatus.OPEN,
        models.EmailAlert.reminders_sent == 0,
        models.EmailAlert.created_at <= fifteen_minutes_ago
    )
    result = await db.execute(stmt)
    open_alerts = result.scalars().all()

    if open_alerts:
        try:
            # Send one summary message instead of spamming
            reminder_text = f"🚨 *REMINDER: {len(open_alerts)} unhandled email alerts require attention.*"
            await telegram_client.send_telegram_message(bot, reminder_text, topic_name="EMAILS")
            
            # Update all alerts in a single query
            alert_ids = [alert.id for alert in open_alerts]
            update_stmt = update(models.EmailAlert).where(models.EmailAlert.id.in_(alert_ids)).values(reminders_sent=1)
            await db.execute(update_stmt)
            logging.info(f"Sent consolidated 15-min reminder for {len(open_alerts)} email alerts.")
        except Exception as e:
            logging.error(f"Could not send consolidated reminder for {len(open_alerts)} alerts", exc_info=e)

    # --- Consolidated Relocation Reminder ---
    stmt = select(models.Booking).where(
        models.Booking.status == models.BookingStatus.PENDING_RELOCATION,
        models.Booking.reminders_sent == 0,
        models.Booking.created_at <= fifteen_minutes_ago
    )
    result = await db.execute(stmt)
    pending_relocations = result.scalars().all()

    if pending_relocations:
        try:
            # This alert is already consolidated, so we just send it
            alert_text = telegram_client.format_unresolved_relocations_alert(pending_relocations)
            await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES")

            booking_ids = [booking.id for booking in pending_relocations]
            update_stmt = update(models.Booking).where(models.Booking.id.in_(booking_ids)).values(reminders_sent=1)
            await db.execute(update_stmt)
            logging.info(f"Sent 15-min reminder for {len(pending_relocations)} pending relocations.")
        except Exception as e:
            logging.error("Could not send pending relocation reminder.", exc_info=e)

    await db.commit()


async def send_checkout_reminder(guest_name: str, property_code: str, checkout_date: str):
    """Sends a high-priority checkout reminder for a relocated guest."""
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    report = telegram_client.format_checkout_reminder_alert(guest_name, property_code, checkout_date)
    await telegram_client.send_telegram_message(bot, report, topic_name="ISSUES")
    logging.info(f"Sent checkout reminder for {guest_name} in {property_code}.")


@db_session_manager
async def daily_briefing_task(time_of_day: str, *, db: AsyncSession):
    """Sends a daily status briefing to the GENERAL topic."""
    logging.info(f"Running {time_of_day} briefing...")
    occupied_res = await db.execute(select(func.count(models.Property.id)).where(models.Property.status == models.PropertyStatus.OCCUPIED))
    pending_res = await db.execute(select(func.count(models.Property.id)).where(models.Property.status == models.PropertyStatus.PENDING_CLEANING))
    maintenance_res = await db.execute(select(func.count(models.Property.id)).where(models.Property.status == models.PropertyStatus.MAINTENANCE))
    available_res = await db.execute(select(func.count(models.Property.id)).where(models.Property.status == models.PropertyStatus.AVAILABLE))
    
    report = telegram_client.format_daily_briefing(
        time_of_day, 
        occupied_res.scalar_one(), 
        pending_res.scalar_one(), 
        maintenance_res.scalar_one(), 
        available_res.scalar_one()
    )
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    await telegram_client.send_telegram_message(bot, report, topic_name="GENERAL")


@db_session_manager
async def daily_midnight_task(*, db: AsyncSession):
    """Sets all PENDING_CLEANING properties to AVAILABLE for the new day."""
    logging.info("Running midnight task...")
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    try:
        stmt = select(models.Property).where(models.Property.status == models.PropertyStatus.PENDING_CLEANING)
        result = await db.execute(stmt)
        props_to_make_available = result.scalars().all()

        if not props_to_make_available:
            logging.info("Midnight Task: No properties were pending cleaning.")
            return
        
        prop_codes = [prop.code for prop in props_to_make_available]
        
        update_stmt = update(models.Property).\
            where(models.Property.status == models.PropertyStatus.PENDING_CLEANING).\
            values(status=models.PropertyStatus.AVAILABLE)
        await db.execute(update_stmt)
        await db.commit()
        
        summary_text = (
            f"Automated Midnight Task (00:05 Local Time)\n\n"
            f"🧹 The following {len(prop_codes)} properties have been cleaned and are now *AVAILABLE* for the new day:\n\n"
            f"`{', '.join(sorted(prop_codes))}`"
        )
        await telegram_client.send_telegram_message(bot, summary_text, topic_name="GENERAL")
        logging.info(f"Midnight Task: Set {len(prop_codes)} properties to AVAILABLE.")
    except Exception as e:
        logging.error("Error during midnight task", exc_info=e)
        await db.rollback()
        await telegram_client.send_telegram_message(
            bot, f"🚨 Error in scheduled midnight task: {e}", topic_name="ISSUES"
        )