# FILE: app/main.py
# VERSION: 2.1 (With Migration Endpoint)
# ==============================================================================
# UPDATED: Added a temporary, secret endpoint to perform a database migration.
# This endpoint, `/_secret_migration_v1_add_email_uid`, will add the missing
# `email_uid` column to the `email_alerts` table to resolve the startup error.
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
    check_emails_task, unhandled_issue_reminder_task
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

# --- Global Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error("Exception caught by global error handler", exc_info=context.error)
    # ... error handling logic ...

# --- Application Lifespan (Startup/Shutdown) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... scheduler logic ...
    scheduler.add_job(daily_midnight_task, 'cron', hour=0, minute=5, id="midnight_cleaner", replace_existing=True)
    scheduler.add_job(daily_briefing_task, 'cron', hour=10, minute=0, args=["Morning"], id="morning_briefing", replace_existing=True)
    scheduler.add_job(check_emails_task, 'interval', minutes=1, id="email_checker", replace_existing=True)
    scheduler.add_job(unhandled_issue_reminder_task, 'interval', minutes=5, id="issue_reminder", replace_existing=True)
    scheduler.start()
    logging.info("APScheduler started.")
    
    await telegram_app.initialize()
    await telegram_app.start()
    webhook_url = f"{config.WEBHOOK_URL}/telegram/webhook"
    await telegram_app.bot.set_webhook(url=webhook_url)
    logging.info(f"Telegram webhook set to: {webhook_url}")
    
    yield
    
    await telegram_app.stop()
    await telegram_app.shutdown()
    scheduler.shutdown()
    logging.info("Scheduler shut down.")

# --- FastAPI App Initialization ---
app = FastAPI(lifespan=lifespan)

# --- BEGIN TEMPORARY MIGRATION ENDPOINT ---
# TODO: REMOVE THIS ENDPOINT AFTER SUCCESSFULLY RUNNING IT ONCE
@app.get("/_secret_migration_v1_add_email_uid")
async def perform_migration(db: Session = Depends(get_db)):
    """
    A temporary, one-time endpoint to add the `email_uid` column to the
    `email_alerts` table.
    """
    try:
        # The SQL command to add the new column.
        # It's safe to run even if the column already exists.
        command = text("ALTER TABLE email_alerts ADD COLUMN IF NOT EXISTS email_uid VARCHAR(255);")
        db.execute(command)
        db.commit()
        logging.info("Migration successful: email_uid column added to email_alerts.")
        return {"status": "success", "message": "Migration applied: 'email_uid' column added."}
    except Exception as e:
        logging.error(f"Migration failed: {e}")
        db.rollback()
        return {"status": "error", "message": str(e)}, 500
# --- END TEMPORARY MIGRATION ENDPOINT ---


# --- Register Telegram Handlers ---
command_mapping = {
    "help": telegram_handlers.help_command, "status": telegram_handlers.status_command,
    "check": telegram_handlers.check_command, # ... other commands
}
for command, handler_func in command_mapping.items():
    telegram_app.add_handler(CommandHandler(command, handler_func))
telegram_app.add_handler(CallbackQueryHandler(telegram_handlers.button_callback_handler))
telegram_app.add_error_handler(error_handler)

# --- Register Slack Handler ---
@slack_app.event("message")
async def handle_message_events(body: dict, ack):
    await ack()
    asyncio.create_task(slack_processor.process_slack_message(payload=body, bot=telegram_app.bot))

# --- API Endpoints ---
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
