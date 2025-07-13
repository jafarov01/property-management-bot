# FILE: main.py
# ==============================================================================
# FINAL VERSION: Corrected the NameError by including all function definitions.
# ==============================================================================

import datetime
import re
import asyncio
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from sqlalchemy.orm import Session, joinedload
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.async_app import AsyncApp
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import telegram_client
import slack_parser
import models
from database import get_db, engine

# --- Database Initialization ---
models.Base.metadata.create_all(bind=engine)

# --- Application Instances ---
slack_app = AsyncApp(token=config.SLACK_BOT_TOKEN, signing_secret=config.SLACK_SIGNING_SECRET)
telegram_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
slack_handler = AsyncSlackRequestHandler(slack_app)
scheduler = AsyncIOScheduler(timezone="UTC")

# --- DYNAMIC HELP COMMAND MANUAL ---
COMMANDS_HELP_MANUAL = {
    "status": {"description": "Get a full summary of all property statuses.", "example": "/status"},
    "check": {"description": "Get a detailed status report for a single property.", "example": "/check A1"},
    "available": {"description": "List all properties that are clean and available.", "example": "/available"},
    "occupied": {"description": "List all properties that are currently occupied.", "example": "/occupied"},
    "pending_cleaning": {"description": "List all properties waiting to be cleaned.", "example": "/pending_cleaning"},
    "early_checkout": {"description": "Manually mark an occupied property as ready for cleaning.", "example": "/early_checkout C5"},
    "set_clean": {"description": "Manually mark a property as clean and available.", "example": "/set_clean D2"},
    "cancel_booking": {"description": "Cancel an active booking and make the property available.", "example": "/cancel_booking A1"},
    "edit_booking": {"description": "Edit details of an active booking (guest_name, due_payment, platform).", "example": "/edit_booking K4 guest_name Maria Garcia-Lopez"},
    "relocate": {"description": "Resolve an overbooking by moving a guest to an available room.", "example": "/relocate B3 A9"},
    "log_issue": {"description": "Log a new maintenance issue for a property.", "example": "/log_issue C5 Shower drain is clogged"},
    "block_property": {"description": "Block a property for maintenance.", "example": "/block_property G2 Repainting walls"},
    "unblock_property": {"description": "Unblock a property and make it available.", "example": "/unblock_property G2"},
    "booking_history": {"description": "Show the last 5 bookings for a property.", "example": "/booking_history A1"},
    "find_guest": {"description": "Find which property a guest is staying in.", "example": "/find_guest Smith"},
    "daily_revenue": {"description": "Calculate estimated revenue for a given date (defaults to today).", "example": "/daily_revenue 2025-07-13"},
    "help": {"description": "Show this help manual.", "example": "/help"}
}

# --- Scheduled Task ---
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
        summary_text = (f"Automated Midnight Task (00:05 UTC)\n\n"
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
        
        if "great reset" in message_text.lower():
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
                if prop_code == "UNKNOWN": continue
                prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
                if not prop or prop.status != "AVAILABLE":
                    existing_guest = None
                    prop_status = prop.status if prop else "NOT_FOUND"
                    if prop_status == "OCCUPIED":
                        active_booking = db.query(models.Booking).filter(models.Booking.property_id == prop.id, models.Booking.status == "Active").order_by(models.Booking.id.desc()).first()
                        if active_booking: existing_guest = active_booking.guest_name
                    booking_data['status'] = "PENDING_RELOCATION"
                    failed_booking = models.Booking(**booking_data)
                    db.add(failed_booking)
                    alert_text, reply_markup = telegram_client.format_checkin_error_alert(
                        property_code=prop_code,
                        new_guest=booking_data["guest_name"],
                        prop_status=prop_status,
                        existing_guest=existing_guest,
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
            checkout_date_for_cleaning_list = (datetime.date.fromisoformat(list_date_str) + datetime.timedelta(days=1)).isoformat()
            properties_to_clean = await slack_parser.parse_cleaning_list_with_ai(message_text)
            processed_for_cleaning = []
            for prop_code in properties_to_clean:
                prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
                if prop and prop.status == "OCCUPIED":
                    prop.status = "PENDING_CLEANING"
                    processed_for_cleaning.append(prop.code)
                    booking_to_update = db.query(models.Booking).filter(models.Booking.property_id == prop.id, models.Booking.status == "Active").order_by(models.Booking.id.desc()).first()
                    if booking_to_update:
                        booking_to_update.checkout_date = checkout_date_for_cleaning_list
                        booking_to_update.status = "Departed"
            db.commit()
            if processed_for_cleaning:
                summary_text = telegram_client.format_daily_list_summary([], [], sorted(processed_for_cleaning), list_date_str)
                await telegram_client.send_telegram_message(bot, summary_text, topic_name="GENERAL")
    finally:
        db.close()

# --- Register Slack Handler ---
@slack_app.event("message")
async def handle_message_events(body: dict, ack):
    await ack()
    asyncio.create_task(process_slack_message(body))

# --- Telegram Command Handlers ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = ["*Eivissa Operations Bot - Command Manual* 🤖\n"]
    for command, details in COMMANDS_HELP_MANUAL.items():
        help_text.append(f"*/{command}*")
        help_text.append(f"_{details['description']}_")
        help_text.append(f"Example: `{details['example']}`\n")
    await context.bot.send_message(chat_id=update.effective_chat.id, text="\n".join(help_text), parse_mode='Markdown')

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
        await update.message.reply_text("Usage: `/check [PROPERTY_CODE]`")
        return
    db = next(get_db())
    try:
        prop_code = context.args[0].upper()
        prop = db.query(models.Property).options(joinedload(models.Property.issues)).filter(models.Property.code == prop_code).first()
        active_booking = None
        if prop and prop.status != "AVAILABLE":
            active_booking = db.query(models.Booking).filter(models.Booking.property_id == prop.id).order_by(models.Booking.id.desc()).first()
        report = telegram_client.format_property_check(prop, active_booking, prop.issues if prop else [])
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def occupied_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        props = db.query(models.Property).filter(models.Property.status == "OCCUPIED").order_by(models.Property.code).all()
        report = telegram_client.format_occupied_list(props)
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def available_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        props = db.query(models.Property).filter(models.Property.status == "AVAILABLE").order_by(models.Property.code).all()
        report = telegram_client.format_available_list(props)
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def early_checkout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/early_checkout [PROPERTY_CODE]`")
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
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def set_clean_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/set_clean [PROPERTY_CODE]`")
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
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def relocate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: `/relocate [FROM_CODE] [TO_CODE]`")
        return
    db = next(get_db())
    try:
        from_code, to_code = context.args[0].upper(), context.args[1].upper()
        to_prop = db.query(models.Property).filter(models.Property.code == to_code).first()
        if not to_prop or to_prop.status != "AVAILABLE":
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Error: Property `{to_code}` is not available for relocation.", parse_mode='Markdown')
            return
        booking_to_relocate = db.query(models.Booking).filter(models.Booking.property_code == from_code, models.Booking.status == "PENDING_RELOCATION").order_by(models.Booking.id.desc()).first()
        if not booking_to_relocate:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Error: No booking found pending relocation for `{from_code}`.", parse_mode='Markdown')
            return
        to_prop.status = "OCCUPIED"
        booking_to_relocate.status = "Active"
        booking_to_relocate.property_id = to_prop.id
        booking_to_relocate.property_code = to_prop.code
        db.commit()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"✅ *Relocation Successful!*\nGuest *{booking_to_relocate.guest_name}* has been moved to `{to_code}`.", parse_mode='Markdown')
    finally:
        db.close()

async def pending_cleaning_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = next(get_db())
    try:
        props = db.query(models.Property).filter(models.Property.status == "PENDING_CLEANING").order_by(models.Property.code).all()
        report = telegram_client.format_pending_cleaning_list(props)
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def cancel_booking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/cancel_booking [PROPERTY_CODE]`")
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
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def edit_booking_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: `/edit_booking [CODE] [field] [new_value]`\nFields: `guest_name`, `due_payment`, `platform`")
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
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def log_issue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/log_issue [CODE] [description]`")
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
            await update.message.reply_text("Issue logged successfully in the #issues topic.")
            return
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def block_property_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/block_property [CODE] [reason]`")
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
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def unblock_property_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/unblock_property [CODE]`")
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
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def booking_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/booking_history [CODE]`")
        return
    db = next(get_db())
    try:
        prop_code = context.args[0].upper()
        bookings = db.query(models.Booking).filter(models.Booking.property_code == prop_code).order_by(models.Booking.checkin_date.desc()).limit(5).all()
        report = telegram_client.format_booking_history(prop_code, bookings)
        await update.message.reply_text(report, parse_mode='Markdown')
    finally:
        db.close()

async def find_guest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/find_guest [GUEST_NAME]`")
        return
    db = next(get_db())
    try:
        guest_name = " ".join(context.args)
        results = db.query(models.Booking).options(joinedload(models.Booking.property)).filter(models.Booking.guest_name.ilike(f"%{guest_name}%"), models.Booking.status == 'Active').all()
        report = telegram_client.format_find_guest_results(results)
        await update.message.reply_text(report, parse_mode='Markdown')
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
        await update.message.reply_text(report, parse_mode='Markdown')
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid date format. Please use `YYYY-MM-DD`.")
    finally:
        db.close()

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, data = query.data.split(":")
    if action == "show_available":
        db = next(get_db())
        try:
            props = db.query(models.Property).filter(models.Property.status == "AVAILABLE").order_by(models.Property.code).all()
            report = telegram_client.format_available_list(props, for_relocation_from=data)
            await query.edit_message_text(text=f"{query.message.text}\n\n{report}", parse_mode='Markdown')
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
telegram_app.add_handler(CallbackQueryHandler(button_callback_handler))

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(daily_midnight_task, 'cron', hour=0, minute=5)
    scheduler.start()
    print("APScheduler started, daily midnight task scheduled.")
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