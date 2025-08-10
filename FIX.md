# FILE: requirements.txt
# ==============================================================================
# UPDATED: Upgraded APScheduler from v3 to v4.0.0a2, a modern version with
# native support for asynchronous operations. Removed the conflicting
# apscheduler_* packages and re-added psycopg2-binary for the scheduler.
# ==============================================================================
fastapi
uvicorn
sqlalchemy
asyncpg
psycopg2-binary
python-dotenv
slack_bolt
aiohttp
python-telegram-bot[ext]
apscheduler==4.0.0a2
google-generativeai
requests
pytz
```python
# FILE: app/scheduled_tasks.py
# ==============================================================================
# UPDATED: Re-configured the scheduler to use the original, synchronous
# SQLAlchemyJobStore. APScheduler v3 requires a synchronous driver, so this
# allows it to use psycopg2 while the rest of the app uses asyncpg.
# ==============================================================================
import logging
import datetime
import asyncio
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
# Use the original, synchronous job store
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from . import config, email_parser, models, telegram_client
from .utils.db_manager import db_session_manager

# --- FIX: Use the synchronous job store with the standard DATABASE_URL ---
# This allows the scheduler to manage its own synchronous connection pool
# without interfering with the main application's async pool.
jobstores = {
    "default": SQLAlchemyJobStore(url=config.DATABASE_URL)
}
scheduler = AsyncIOScheduler(jobstores=jobstores, timezone=config.TIMEZONE)


# --- Background AI Parsing Task ---
@db_session_manager
async def parse_email_in_background(alert_id: int, email_uid: str, *, db: AsyncSession):
    """This function is now called by the dedicated worker, not the scheduler."""
    logging.info(f"PARSER (Alert {alert_id}): Starting job.")
    try:
        logging.info(f"PARSER (Alert {alert_id}): Fetching email body for UID {email_uid}...")
        email_body = email_parser.fetch_email_body_by_uid(email_uid)
        
        if not email_body:
            logging.error(f"PARSER (Alert {alert_id}): FAILED to fetch email body.")
            stmt = update(models.EmailAlert).where(models.EmailAlert.id == alert_id).values(summary="Error: Could not fetch email body for parsing.")
            await db.execute(stmt)
            await db.commit()
            return

        logging.info(f"PARSER (Alert {alert_id}): Email body fetched successfully. Calling AI...")
        parsed_data = await email_parser.parse_booking_email_with_ai(email_body)
        logging.info(f"PARSER (Alert {alert_id}): AI call complete. Result category: {parsed_data.get('category')}")

        result = await db.execute(select(models.EmailAlert).filter(models.EmailAlert.id == alert_id))
        alert_to_update = result.scalar_one_or_none()
        if not alert_to_update:
            logging.error(f"PARSER (Alert {alert_id}): Could not find alert in DB to update after parsing.")
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
    """This task is a fast "producer"."""
    logging.info("PRODUCER: Running email check...")
    try:
        unread_emails_metadata = email_parser.fetch_unread_email_metadata()
        if not unread_emails_metadata:
            logging.info("PRODUCER: No new emails found.")
            return

        logging.info(f"PRODUCER: Found {len(unread_emails_metadata)} emails. Adding to queue.")
        bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

        for metadata in unread_emails_metadata:
            async with db.begin_nested():
                try:
                    new_alert = models.EmailAlert(
                        category="New Email",
                        summary=f"Subject: {metadata['subject']}",
                        email_uid=metadata['uid']
                    )
                    db.add(new_alert)
                    await db.flush()

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
        await db.commit()
    except Exception as e:
        logging.error("PRODUCER: Critical error in check_emails_task.", exc_info=e)


@db_session_manager
async def unhandled_issue_reminder_task(*, db: AsyncSession):
    """Checks for open issues older than 15 minutes and sends a reminder."""
    logging.info("Checking for unhandled issues for 15-minute reminder...")
    now = datetime.datetime.now(datetime.timezone.utc)
    reminder_threshold = now - datetime.timedelta(minutes=15)
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    stmt = select(models.EmailAlert).where(
        models.EmailAlert.status == models.EmailAlertStatus.OPEN,
        models.EmailAlert.reminders_sent == 0,
        models.EmailAlert.created_at <= reminder_threshold
    )
    result = await db.execute(stmt)
    open_alerts = result.scalars().all()

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

    stmt = select(models.Booking).where(
        models.Booking.status == models.BookingStatus.PENDING_RELOCATION,
        models.Booking.reminders_sent == 0,
        models.Booking.created_at <= reminder_threshold
    )
    result = await db.execute(stmt)
    pending_relocations = result.scalars().all()

    if pending_relocations:
        try:
            alert_text = telegram_client.format_unresolved_relocations_alert(pending_relocations)
            await telegram_client.send_telegram_message(bot, alert_text, topic_name="ISSUES")
            for booking in pending_relocations:
                booking.reminders_sent = 1
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
```python
# FILE: app/main.py
# ==============================================================================
# UPDATED: The scheduler startup and shutdown logic has been updated to match
# the API for APScheduler v4.
# ==============================================================================
import logging
import sys
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Depends
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from . import config, models, telegram_client
from .database import async_engine, get_db
from . import telegram_handlers
from . import slack_handler as slack_processor
from .scheduled_tasks import (
    scheduler, daily_midnight_task, daily_briefing_task,
    check_emails_task, unhandled_issue_reminder_task, parse_email_in_background
)

# --- Configure Logging ---
handler = logging.StreamHandler(sys.stdout)
handler.flush = sys.stdout.flush
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[handler]
)

# --- App Instances & Worker Queue ---
slack_app = AsyncApp(token=config.SLACK_BOT_TOKEN, signing_secret=config.SLACK_SIGNING_SECRET)
telegram_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
slack_handler = AsyncSlackRequestHandler(slack_app)
email_queue = asyncio.Queue()

async def email_parsing_worker(queue: asyncio.Queue):
    """A long-running worker that processes email parsing jobs from a queue sequentially."""
    logging.info("EMAIL WORKER: Starting up...")
    while True:
        try:
            alert_id, email_uid = await queue.get()
            logging.info(f"EMAIL WORKER: Picked up job for alert_id: {alert_id}, UID: {email_uid}")
            await parse_email_in_background(alert_id, email_uid)
            logging.info(f"EMAIL WORKER: Finished job for alert_id: {alert_id}.")
            queue.task_done()
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            logging.info("EMAIL WORKER: Shutdown signal received.")
            break
        except Exception as e:
            logging.error(f"EMAIL WORKER: CRITICAL UNHANDLED EXCEPTION: {e}", exc_info=True)
            await asyncio.sleep(5)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error("Exception caught by global error handler", exc_info=context.error)
    # ... error handling logic ...

# --- Application Lifespan (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("LIFESPAN: Application startup...")
    async with async_engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)
    
    worker_task = asyncio.create_task(email_parsing_worker(email_queue))

    command_mapping = {
        "help": telegram_handlers.help_command, "status": telegram_handlers.status_command,
        "check": telegram_handlers.check_command, "occupied": telegram_handlers.occupied_command,
        "available": telegram_handlers.available_command, "pending_cleaning": telegram_handlers.pending_cleaning_command,
        "relocate": telegram_handlers.relocate_command, "rename_property": telegram_handlers.rename_property_command,
        "set_clean": telegram_handlers.set_clean_command, "early_checkout": telegram_handlers.early_checkout_command,
        "cancel_booking": telegram_handlers.cancel_booking_command, "edit_booking": telegram_handlers.edit_booking_command,
        "log_issue": telegram_handlers.log_issue_command, "block_property": telegram_handlers.block_property_command,
        "unblock_property": telegram_handlers.unblock_property_command, "booking_history": telegram_handlers.booking_history_command,
        "find_guest": telegram_handlers.find_guest_command, "daily_revenue": telegram_handlers.daily_revenue_command,
        "relocations": telegram_handlers.relocations_command,
    }
    for command, handler_func in command_mapping.items():
        telegram_app.add_handler(CommandHandler(command, handler_func))

    telegram_app.add_handler(CallbackQueryHandler(telegram_handlers.button_callback_handler))
    telegram_app.add_error_handler(error_handler)

    # --- FIX: Use APScheduler v4 API ---
    scheduler.add_job(daily_midnight_task, 'cron', hour=0, minute=5, id="midnight_cleaner", replace_existing=True)
    scheduler.add_job(daily_briefing_task, 'cron', hour=10, minute=0, args=["Morning"], id="morning_briefing", replace_existing=True)
    scheduler.add_job(check_emails_task, 'interval', minutes=1, args=[email_queue], id="email_checker", replace_existing=True)
    scheduler.add_job(unhandled_issue_reminder_task, 'interval', minutes=5, id="issue_reminder", replace_existing=True)
    scheduler.start_in_background()
    logging.info("LIFESPAN: APScheduler and email worker started.")
    
    await telegram_app.initialize()
    await telegram_app.start()
    webhook_url = f"{config.WEBHOOK_URL}/telegram/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url)
    logging.info(f"LIFESPAN: Telegram webhook set.")
    
    yield
    
    logging.info("LIFESPAN: Application shutdown...")
    worker_task.cancel()
    await telegram_app.stop()
    await telegram_app.shutdown()
    # --- FIX: Use APScheduler v4 API ---
    await scheduler.shutdown()
    logging.info("LIFESPAN: All services shut down gracefully.")

# --- FastAPI App Initialization ---
app = FastAPI(lifespan=lifespan)

# --- Migration Endpoint (Remove after use) ---
@app.get("/_secret_migration_v1_add_email_uid")
async def perform_migration(db: AsyncSession = Depends(get_db)):
    try:
        command = text("ALTER TABLE email_alerts ADD COLUMN IF NOT EXISTS email_uid VARCHAR(255);")
        await db.execute(command)
        await db.commit()
        return {"status": "success", "message": "Migration applied."}
    except Exception as e:
        await db.rollback()
        return {"status": "error", "message": str(e)}, 500

# --- API Endpoints ---
@slack_app.event("message")
async def handle_message_events(body: dict, ack):
    await ack()
    asyncio.create_task(slack_processor.process_slack_message(payload=body, bot=telegram_app.bot))

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
