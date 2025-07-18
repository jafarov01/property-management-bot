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

# @app.get("/_secret_migration_v5_add_reminders_sent")
# async def perform_migration(db: Session = Depends(get_db)):
#     """
#     A temporary, one-time endpoint to apply database schema changes.
#     This should be removed after the migration is successfully applied.
#     """
#     try:
#         # SQL command to add the new column if it doesn't already exist.
#         sql_command = text("""
#             DO $$
#             BEGIN
#                 IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
#                                WHERE table_name='email_alerts' AND column_name='reminders_sent') THEN
#                     ALTER TABLE email_alerts ADD COLUMN reminders_sent INTEGER NOT NULL DEFAULT 0;
#                 END IF;
#             END $$;
#         """)
#         db.execute(sql_command)
#         db.commit()
#         logging.info("Migration successful: 'reminders_sent' column ensured to exist.")
#         return {"status": "success", "message": "Migration applied or column already exists."}
#     except Exception as e:
#         # NOTE: db.rollback() is handled by the get_db's finally block
#         logging.error(f"Migration failed: {e}")
#         # Re-raise to let FastAPI's error handling catch it, or return a specific response
#         return {"status": "error", "message": str(e)}, 500

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
