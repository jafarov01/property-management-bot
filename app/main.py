# FILE: app/main.py
# VERSION: 2.2 (Final Fix: Email Worker Queue)
# ==============================================================================
# UPDATED: Implemented a robust producer-consumer pattern for email processing.
# 1. An `asyncio.Queue` is created at startup.
# 2. A dedicated `email_parsing_worker` task is started that runs for the
#    entire application lifespan.
# 3. The scheduled `check_emails_task` now only adds jobs to this queue,
#    making it non-blocking and extremely fast.
# This architecture solves the rate-limiting and blocking issues permanently.
# ==============================================================================
import logging
import sys
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Depends
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from sqlalchemy.orm import Session
from sqlalchemy import text
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from . import config, models, telegram_client
from .database import engine, get_db
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

# --- Database & Application Instances ---
models.Base.metadata.create_all(bind=engine)
slack_app = AsyncApp(token=config.SLACK_BOT_TOKEN, signing_secret=config.SLACK_SIGNING_SECRET)
telegram_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
slack_handler = AsyncSlackRequestHandler(slack_app)

# --- NEW: Setup for Email Processing Queue ---
email_queue = asyncio.Queue()

async def email_parsing_worker(queue: asyncio.Queue):
    """
    A long-running worker that processes email parsing jobs from a queue sequentially.
    """
    logging.info("Email parsing worker started.")
    while True:
        try:
            # Wait for a job to appear in the queue
            alert_id, email_uid = await queue.get()
            logging.info(f"Worker picked up job for alert_id: {alert_id}")
            
            # Process the job
            await parse_email_in_background(alert_id, email_uid)
            
            # Mark the task as done
            queue.task_done()
            
            # Add a small delay to be respectful to the API
            await asyncio.sleep(2)
        except Exception as e:
            logging.error(f"Error in email parsing worker: {e}", exc_info=True)


# --- Global Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error("Exception caught by global error handler", exc_info=context.error)
    # ... error handling logic ...

# --- Application Lifespan (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the dedicated email parsing worker
    worker_task = asyncio.create_task(email_parsing_worker(email_queue))

    # Schedule all jobs, passing the queue to the email checker
    scheduler.add_job(daily_midnight_task, 'cron', hour=0, minute=5, id="midnight_cleaner", replace_existing=True)
    scheduler.add_job(daily_briefing_task, 'cron', hour=10, minute=0, args=["Morning"], id="morning_briefing", replace_existing=True)
    scheduler.add_job(check_emails_task, 'interval', minutes=1, args=[email_queue], id="email_checker", replace_existing=True)
    scheduler.add_job(unhandled_issue_reminder_task, 'interval', minutes=5, id="issue_reminder", replace_existing=True)
    scheduler.start()
    logging.info("APScheduler and email worker started.")
    
    await telegram_app.initialize()
    await telegram_app.start()
    webhook_url = f"{config.WEBHOOK_URL}/telegram/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url)
    logging.info(f"Telegram webhook set to: {webhook_url}")
    
    yield
    
    # Cleanly shut down
    worker_task.cancel()
    await telegram_app.stop()
    await telegram_app.shutdown()
    scheduler.shutdown()
    logging.info("Scheduler and worker shut down.")

# --- FastAPI App Initialization ---
app = FastAPI(lifespan=lifespan)

# --- Migration Endpoint (Remove after use) ---
@app.get("/_secret_migration_v1_add_email_uid")
async def perform_migration(db: Session = Depends(get_db)):
    try:
        command = text("ALTER TABLE email_alerts ADD COLUMN IF NOT EXISTS email_uid VARCHAR(255);")
        db.execute(command)
        db.commit()
        return {"status": "success", "message": "Migration applied."}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}, 500

# --- Register Handlers and Endpoints ---
# ... (rest of the file is unchanged)
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