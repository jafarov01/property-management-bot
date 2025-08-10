# FILE: app/telegram_handlers.py
import datetime
import re
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from telegram import Update
from telegram.ext import ContextTypes
import pytz
from . import models, telegram_client, config
from .utils.db_manager import db_session_manager
from .utils.validators import get_property_from_context
from .scheduled_tasks import scheduler, send_checkout_reminder

# --- DYNAMIC HELP COMMAND MANUAL ---
COMMANDS_HELP_MANUAL = {
    "status": {
        "description": "Get a full summary of all property statuses.",
        "example": "/status",
    },
    "check": {
        "description": "Get a detailed status report for a single property.",
        "example": "/check A1",
    },
    "rename_property": {
        "description": "Correct a property's code in the database.",
        "example": "/rename_property C7 C8",
    },
    "available": {
        "description": "List all properties that are clean and available.",
        "example": "/available",
    },
    "occupied": {
        "description": "List all properties that are currently occupied.",
        "example": "/occupied",
    },
    "pending_cleaning": {
        "description": "List all properties waiting to be cleaned.",
        "example": "/pending_cleaning",
    },
    "early_checkout": {
        "description": "Manually mark an occupied property as ready for cleaning.",
        "example": "/early_checkout C5",
    },
    "set_clean": {
        "description": "Manually mark a property as clean and available.",
        "example": "/set_clean D2",
    },
    "cancel_booking": {
        "description": "Cancel an active booking and make the property available.",
        "example": "/cancel_booking A1",
    },
    "edit_booking": {
        "description": "Edit details of an active booking (guest_name, due_payment, platform).",
        "example": "/edit_booking K4 guest_name Maria Garcia-Lopez",
    },
    "relocate": {
        "description": "Move a guest pending relocation and set their checkout date.",
        "example": "/relocate A1 A2 2025-07-20",
    },
    "log_issue": {
        "description": "Log a new maintenance issue for a property.",
        "example": "/log_issue C5 Shower drain is clogged",
    },
    "block_property": {
        "description": "Block a property for maintenance.",
        "example": "/block_property G2 Repainting walls",
    },
    "unblock_property": {
        "description": "Unblock a property and make it available.",
        "example": "/unblock_property G2",
    },
    "booking_history": {
        "description": "Show the last 5 bookings for a property.",
        "example": "/booking_history A1",
    },
    "find_guest": {
        "description": "Find which property a guest is staying in.",
        "example": "/find_guest Smith",
    },
    "daily_revenue": {
        "description": "Calculate estimated revenue for a given date (defaults to today).",
        "example": "/daily_revenue 2025-07-13",
    },
    "relocations": {
        "description": "Show a history of recent guest relocations.",
        "example": "/relocations or /relocations A1",
    },
    "help": {"description": "Show this help manual.", "example": "/help"},
}

# --- Telegram Command Handlers ---


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the full command manual."""
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="\n".join(
            [
                "*Eivissa Operations Bot - Command Manual* 🤖\n",
                *[
                    f"*/{command}*\n_{details['description']}_\nExample: `{details['example']}`\n"
                    for command, details in COMMANDS_HELP_MANUAL.items()
                ],
            ]
        ),
        parse_mode="Markdown",
    )


@db_session_manager
async def status_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Sends a summary of all property statuses."""
    total_res = await db.execute(select(func.count(models.Property.id)))
    occupied_res = await db.execute(select(func.count(models.Property.id)).where(models.Property.status == models.PropertyStatus.OCCUPIED))
    available_res = await db.execute(select(func.count(models.Property.id)).where(models.Property.status == models.PropertyStatus.AVAILABLE))
    pending_res = await db.execute(select(func.count(models.Property.id)).where(models.Property.status == models.PropertyStatus.PENDING_CLEANING))
    maintenance_res = await db.execute(select(func.count(models.Property.id)).where(models.Property.status == models.PropertyStatus.MAINTENANCE))

    report = telegram_client.format_status_report(
        total_res.scalar_one(), occupied_res.scalar_one(), available_res.scalar_one(), pending_res.scalar_one(), maintenance_res.scalar_one()
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def check_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Gets a detailed status report for a single property."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    active_booking = None
    if prop.status != models.PropertyStatus.AVAILABLE:
        res = await db.execute(
            select(models.Booking)
            .filter(models.Booking.property_id == prop.id)
            .order_by(models.Booking.id.desc())
        )
        active_booking = res.scalars().first()
        
    report = telegram_client.format_property_check(prop, active_booking, prop.issues)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def occupied_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Lists all currently occupied properties."""
    res = await db.execute(
        select(models.Property)
        .filter(models.Property.status == models.PropertyStatus.OCCUPIED)
        .order_by(models.Property.code)
    )
    props = res.scalars().all()
    report = telegram_client.format_occupied_list(props)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def available_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Lists all clean and available properties."""
    res = await db.execute(
        select(models.Property)
        .filter(models.Property.status == models.PropertyStatus.AVAILABLE)
        .order_by(models.Property.code)
    )
    props = res.scalars().all()
    report = telegram_client.format_available_list(props)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def early_checkout_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Manually marks an occupied property as PENDING_CLEANING."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    if prop.status != models.PropertyStatus.OCCUPIED:
        report = telegram_client.format_simple_error(
            f"Property `{prop.code}` is currently `{prop.status}`, not OCCUPIED."
        )
    else:
        prop.status = models.PropertyStatus.PENDING_CLEANING
        await db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{prop.code}` has been checked out and is now *PENDING_CLEANING*."
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def set_clean_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Manually marks a property as clean and AVAILABLE."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    if prop.status != models.PropertyStatus.PENDING_CLEANING:
        report = telegram_client.format_simple_error(
            f"Property `{prop.code}` is currently `{prop.status}`, not PENDING_CLEANING."
        )
    else:
        prop.status = models.PropertyStatus.AVAILABLE
        await db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{prop.code}` has been manually set to *AVAILABLE*."
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def rename_property_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Renames a property's code in the database."""
    if len(context.args) != 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/rename_property [OLD_CODE] [NEW_CODE]`",
        )
        return

    old_code, new_code = context.args[0].upper(), context.args[1].upper()

    res = await db.execute(select(models.Property).filter(models.Property.code == new_code))
    if res.scalars().first():
        report = telegram_client.format_simple_error(
            f"Cannot rename: Property `{new_code}` already exists."
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
        )
        return

    res = await db.execute(select(models.Property).filter(models.Property.code == old_code))
    prop_to_rename = res.scalars().first()
    if not prop_to_rename:
        report = telegram_client.format_simple_error(
            f"Property `{old_code}` not found."
        )
    else:
        prop_to_rename.code = new_code
        await db.execute(
            update(models.Booking)
            .filter(models.Booking.property_code == old_code)
            .values(property_code=new_code)
        )
        await db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{old_code}` has been successfully renamed to `{new_code}`."
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def relocate_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Moves a guest pending relocation to an available room."""
    if len(context.args) != 3:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/relocate [FROM_CODE] [TO_CODE] [YYYY-MM-DD]`",
        )
        return

    from_code, to_code, checkout_date_str = (
        context.args[0].upper(),
        context.args[1].upper(),
        context.args[2],
    )
    try:
        checkout_date = datetime.date.fromisoformat(checkout_date_str)
    except ValueError:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ Error: Invalid date format. Please use `YYYY-MM-DD`.",
        )
        return

    res = await db.execute(select(models.Property).filter(models.Property.code == to_code))
    to_prop = res.scalars().first()
    if not to_prop or to_prop.status != models.PropertyStatus.AVAILABLE:
        report = telegram_client.format_simple_error(
            f"Property `{to_code}` is not available for relocation."
        )
    else:
        res = await db.execute(
            select(models.Booking)
            .filter(
                models.Booking.property_code == from_code,
                models.Booking.status == models.BookingStatus.PENDING_RELOCATION,
            )
            .order_by(models.Booking.id.desc())
        )
        booking_to_relocate = res.scalars().first()
        if not booking_to_relocate:
            report = telegram_client.format_simple_error(
                f"No booking found pending relocation for `{from_code}`."
            )
        else:
            log_entry = models.Relocation(
                booking_id=booking_to_relocate.id,
                guest_name=booking_to_relocate.guest_name,
                original_property_code=from_code,
                new_property_code=to_code,
            )
            db.add(log_entry)
            to_prop.status = models.PropertyStatus.OCCUPIED
            booking_to_relocate.status = models.BookingStatus.ACTIVE
            booking_to_relocate.property_id = to_prop.id
            booking_to_relocate.property_code = to_prop.code
            booking_to_relocate.checkout_date = checkout_date
            reminder_datetime = datetime.datetime.combine(
                checkout_date - datetime.timedelta(days=1), datetime.time(18, 0)
            )
            scheduler.add_job(
                send_checkout_reminder,
                "date",
                run_date=reminder_datetime,
                args=[booking_to_relocate.guest_name, to_code, checkout_date_str],
                id=f"checkout_reminder_{booking_to_relocate.id}",
                replace_existing=True,
            )
            await db.commit()
            report = telegram_client.format_simple_success(
                f"Relocation Successful!\n"
                f"Guest *{booking_to_relocate.guest_name}* has been moved to `{to_code}`.\n"
                f"A checkout reminder has been scheduled for *{reminder_datetime.strftime('%Y-%m-%d %H:%M')}*."
            )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def pending_cleaning_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Lists all properties waiting to be cleaned."""
    res = await db.execute(
        select(models.Property)
        .filter(models.Property.status == models.PropertyStatus.PENDING_CLEANING)
        .order_by(models.Property.code)
    )
    props = res.scalars().all()
    report = telegram_client.format_pending_cleaning_list(props)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def cancel_booking_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Cancels an active booking and makes the property available."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    if prop.status != models.PropertyStatus.OCCUPIED:
        report = telegram_client.format_simple_error(
            f"Property `{prop.code}` is not occupied."
        )
    else:
        res = await db.execute(
            select(models.Booking)
            .filter(
                models.Booking.property_id == prop.id, 
                models.Booking.status == models.BookingStatus.ACTIVE
            )
        )
        booking = res.scalars().first()
        if booking:
            booking.status = models.BookingStatus.CANCELLED
            prop.status = models.PropertyStatus.AVAILABLE
            await db.commit()
            report = telegram_client.format_simple_success(
                f"Booking for *{booking.guest_name}* in `{prop.code}` has been cancelled. The property is now available."
            )
        else:
            report = telegram_client.format_simple_error(
                f"No active booking found for `{prop.code}`."
            )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def edit_booking_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Edits details of an active booking."""
    if len(context.args) < 3:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/edit_booking [CODE] [field] [new_value]`\nFields: `guest_name`, `due_payment`, `platform`",
        )
        return

    prop_code = context.args[0].upper()
    res = await db.execute(select(models.Property).filter(models.Property.code == prop_code))
    prop = res.scalars().first()

    if not prop or prop.status != models.PropertyStatus.OCCUPIED:
        report = telegram_client.format_simple_error(
            f"Property `{prop_code}` not found or is not occupied."
        )
    else:
        field = context.args[1].lower()
        new_value = " ".join(context.args[2:])
        res = await db.execute(
            select(models.Booking)
            .filter(
                models.Booking.property_id == prop.id, 
                models.Booking.status == models.BookingStatus.ACTIVE
            )
        )
        booking = res.scalars().first()
        if not booking:
            report = telegram_client.format_simple_error(
                f"No active booking found for `{prop_code}`."
            )
        elif field not in ["guest_name", "due_payment", "platform"]:
            report = telegram_client.format_simple_error(
                f"Invalid field `{field}`. Use `guest_name`, `due_payment`, or `platform`."
            )
        else:
            setattr(booking, field, new_value)
            await db.commit()
            report = telegram_client.format_simple_success(
                f"Booking for `{prop_code}` updated: `{field}` is now *{new_value}*."
            )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def log_issue_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Logs a new maintenance issue for a property."""
    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/log_issue [CODE] [description]`",
        )
        return

    prop = await get_property_from_context(update, context.args[:1], db)
    if not prop:
        return

    description = " ".join(context.args[1:])
    new_issue = models.Issue(property_id=prop.id, description=description)
    db.add(new_issue)
    await db.commit()
    report = telegram_client.format_simple_success(
        f"New issue logged for `{prop.code}`: _{description}_"
    )
    await telegram_client.send_telegram_message(
        context.bot, report, topic_name="ISSUES"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Issue logged successfully in the #issues topic.",
    )


@db_session_manager
async def block_property_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Blocks a property for maintenance."""
    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Usage: `/block_property [CODE] [reason]`",
        )
        return

    prop = await get_property_from_context(update, context.args[:1], db)
    if not prop:
        return

    if prop.status == models.PropertyStatus.OCCUPIED:
        report = telegram_client.format_simple_error(
            f"Cannot block `{prop.code}`, it is currently occupied."
        )
    else:
        reason = " ".join(context.args[1:])
        prop.status = models.PropertyStatus.MAINTENANCE
        prop.notes = reason
        await db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{prop.code}` is now blocked for *MAINTENANCE*.\nReason: _{reason}_"
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def unblock_property_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Unblocks a property and makes it available."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    if prop.status != models.PropertyStatus.MAINTENANCE:
        report = telegram_client.format_simple_error(
            f"Property `{prop.code}` is not under maintenance."
        )
    else:
        prop.status = models.PropertyStatus.AVAILABLE
        prop.notes = None
        await db.commit()
        report = telegram_client.format_simple_success(
            f"Property `{prop.code}` has been unblocked and is now *AVAILABLE*."
        )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def booking_history_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Shows the last 5 bookings for a property."""
    prop = await get_property_from_context(update, context.args, db)
    if not prop:
        return

    res = await db.execute(
        select(models.Booking)
        .filter(models.Booking.property_code == prop.code)
        .order_by(models.Booking.checkin_date.desc())
        .limit(5)
    )
    bookings = res.scalars().all()
    report = telegram_client.format_booking_history(prop.code, bookings)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def find_guest_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Finds which property a guest is staying in."""
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, text="Usage: `/find_guest [GUEST_NAME]`"
        )
        return

    guest_name = " ".join(context.args)
    res = await db.execute(
        select(models.Booking)
        .options(joinedload(models.Booking.property))
        .filter(
            models.Booking.guest_name.ilike(f"%{guest_name}%"),
            models.Booking.status == models.BookingStatus.ACTIVE,
        )
    )
    results = res.scalars().all()
    report = telegram_client.format_find_guest_results(results)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def daily_revenue_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Calculates estimated revenue for a given date."""
    try:
        date_str = (
            context.args[0] if context.args else datetime.date.today().isoformat()
        )
        target_date = datetime.date.fromisoformat(date_str)
    except (ValueError, IndexError):
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Invalid date format. Please use `YYYY-MM-DD`.",
        )
        return

    res = await db.execute(
        select(models.Booking)
        .filter(models.Booking.checkin_date == target_date)
    )
    bookings = res.scalars().all()
    total_revenue = 0.0
    for b in bookings:
        # Use regex to find the first number (integer or float) in the payment string
        numbers = re.findall(r"\d+\.?\d*", b.due_payment)
        if numbers:
            total_revenue += float(numbers[0])
    report = telegram_client.format_daily_revenue_report(
        date_str, total_revenue, len(bookings)
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def relocations_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Shows a history of recent guest relocations."""
    query = select(models.Relocation).order_by(models.Relocation.relocated_at.desc())
    if context.args:
        prop_code = context.args[0].upper()
        query = query.filter(
            (models.Relocation.original_property_code == prop_code)
            | (models.Relocation.new_property_code == prop_code)
        )
    res = await db.execute(query.limit(10))
    history = res.scalars().all()
    report = telegram_client.format_relocation_history(history)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=report, parse_mode="Markdown"
    )


@db_session_manager
async def button_callback_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE, db: AsyncSession
):
    """Handles all callback queries from inline buttons."""
    query = update.callback_query
    await query.answer()
    action, *data = query.data.split(":")

    # --- Show Available Rooms Action ---
    if action == "show_available":
        prop_code = data[0]
        res = await db.execute(
            select(models.Property)
            .filter(models.Property.status == models.PropertyStatus.AVAILABLE)
            .order_by(models.Property.code)
        )
        props = res.scalars().all()
        report = telegram_client.format_available_list(
            props, for_relocation_from=prop_code
        )

        # This check prevents an error if the user clicks the button multiple times.
        if report not in query.message.text:
            # Re-applying `query.message.reply_markup` ensures buttons persist.
            await query.edit_message_text(
                text=f"{query.message.text_markdown}\n\n{report}",
                parse_mode="Markdown",
                reply_markup=query.message.reply_markup,
            )

    # --- Swap Relocation Action ---
    elif action == "swap_relocation":
        active_booking_id, pending_booking_id = data[0], data[1]
        res1 = await db.execute(select(models.Booking).filter(models.Booking.id == active_booking_id))
        active_booking = res1.scalars().first()
        res2 = await db.execute(select(models.Booking).filter(models.Booking.id == pending_booking_id))
        pending_booking = res2.scalars().first()

        if not active_booking or not pending_booking:
            await query.edit_message_text(
                text=f"{query.message.text_markdown}\n\n❌ Error: Could not find original bookings to swap.",
                parse_mode="Markdown",
            )
            return

        # Perform the swap
        active_booking.status = models.BookingStatus.PENDING_RELOCATION
        pending_booking.status = models.BookingStatus.ACTIVE
        await db.commit()

        # Generate new text and a NEW keyboard with updated callback data
        new_text, new_keyboard = telegram_client.format_conflict_alert(
            prop_code=active_booking.property_code,
            active_booking=pending_booking,  # The roles are now swapped
            pending_booking=active_booking,
        )

        confirmation_text = f"✅ *Swap Successful!*\n\n{new_text}"
        await query.edit_message_text(
            text=confirmation_text, parse_mode="Markdown", reply_markup=new_keyboard
        )

    # --- NEW: Cancel Pending Relocation Action ---
    elif action == "cancel_pending_relocation":
        pending_booking_id = data[0]
        res = await db.execute(select(models.Booking).filter(models.Booking.id == pending_booking_id))
        booking_to_cancel = res.scalars().first()

        if not booking_to_cancel:
            await query.edit_message_text(
                text=f"{query.message.text_markdown}\n\n❌ Error: Could not find booking to cancel.",
                parse_mode="Markdown",
            )
            return

        if booking_to_cancel.status != models.BookingStatus.PENDING_RELOCATION:
            await query.edit_message_text(
                text=f"{query.message.text_markdown}\n\n⚠️ This booking is no longer pending relocation.",
                parse_mode="Markdown",
            )
            return

        booking_to_cancel.status = models.BookingStatus.CANCELLED
        await db.commit()

        # Final resolution message with all buttons removed
        new_text = (
            f"{query.message.text_markdown}\n\n---\n"
            f"✅ *Conflict Resolved.*\nBooking for *{booking_to_cancel.guest_name}* has been cancelled."
        )
        await query.edit_message_text(
            text=new_text, parse_mode="Markdown", reply_markup=None
        )

    # --- Handle Email Action ---
    elif action == "handle_email":
        alert_id = int(data[0])
        res = await db.execute(select(models.EmailAlert).filter(models.EmailAlert.id == alert_id))
        alert = res.scalars().first()
        if alert and alert.status == models.EmailAlertStatus.OPEN:
            alert.status = models.EmailAlertStatus.HANDLED
            alert.handled_by = query.from_user.full_name

            budapest_tz = pytz.timezone(config.TIMEZONE)
            alert.handled_at = datetime.datetime.now(budapest_tz)

            await db.commit()

            new_text = telegram_client.format_handled_email_notification(
                alert, query.from_user.full_name
            )
            await query.edit_message_text(
                text=new_text, parse_mode="Markdown", reply_markup=None
            )
        else:
            await query.answer("This alert has already been handled.", show_alert=True)
