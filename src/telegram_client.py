# FILE: telegram_client.py
# ==============================================================================

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import TELEGRAM_TARGET_CHAT_ID, TELEGRAM_TOPIC_IDS

async def send_telegram_message(bot: telegram.Bot, text: str, topic_name: str = "GENERAL", reply_markup=None, parse_mode: str = 'Markdown'):
    topic_id = TELEGRAM_TOPIC_IDS.get(topic_name)
    message_thread_id_to_send = topic_id if topic_name != "GENERAL" else None
    await bot.send_message(
        chat_id=TELEGRAM_TARGET_CHAT_ID,
        text=text,
        message_thread_id=message_thread_id_to_send,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )

def format_daily_list_summary(checkins: list, cleanings: list, pending_cleanings: list, date_str: str) -> str:
    from datetime import datetime
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    readable_date = date_obj.strftime('%B %d, %Y')
    message = [f"*{readable_date}*", f"✅ *Daily Lists Processed*"]
    if checkins:
        message.append(f"\n➡️ *New Check-ins Logged ({len(checkins)}):*")
        for booking in checkins:
            prop_code = booking.property.code if booking.property else booking.property_code
            message.append(f"  • `{prop_code}` - {booking.guest_name}")
    if cleanings:
        message.append(f"\n🧹 *Properties Marked as AVAILABLE ({len(cleanings)}):*")
        message.append(f"  • `{'`, `'.join(cleanings)}`")
    if pending_cleanings:
        message.append(f"\n⏳ *Properties Marked as PENDING CLEANING ({len(pending_cleanings)}):*")
        message.append(f"  • `{'`, `'.join(pending_cleanings)}`")
    return "\n".join(message)

def format_overbooking_alert(property_code: str, new_guest: str, existing_guest: str, date_str: str) -> tuple:
    from datetime import datetime
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    readable_date = date_obj.strftime('%B %d, %Y')
    alert_text = (
        f"*{readable_date}*\n🚨 *OVERBOOKING DETECTED* 🚨\n\n"
        f"Property `{property_code}` is currently occupied by *{existing_guest}*.\n\n"
        f"Cannot check in new guest: *{new_guest}*.\n\n"
        f"This booking is now pending relocation. Please take action!"
    )
    keyboard = [[
        InlineKeyboardButton("Show Available Rooms", callback_data=f"show_available:{property_code}"),
        InlineKeyboardButton("Suggest Relocation", switch_inline_query_current_chat=f"/relocate {property_code} "),
    ]]
    return alert_text, InlineKeyboardMarkup(keyboard)

def format_available_list(available_props: list, for_relocation_from: str = None) -> str:
    if not available_props:
        return "❌ No properties are currently available."
    message = ["✅ *Available Properties:*"]
    codes = sorted([prop.code for prop in available_props])
    message.append(f"`{', '.join(codes)}`")
    if for_relocation_from:
        message.append(f"\n_To relocate from `{for_relocation_from}`, type:_ `/relocate {for_relocation_from} [new_room]`")
    return "\n".join(message)

def format_status_report(total: int, occupied: int, available: int, pending_cleaning: int, maintenance: int) -> str:
    return (
        f"📊 *Current System Status*\n\n"
        f"Total Properties: `{total}`\n"
        f"➡️ Occupied: `{occupied}`\n"
        f"⏳ Pending Cleaning: `{pending_cleaning}`\n"
        f"🛠️ Maintenance: `{maintenance}`\n"
        f"✅ Available: `{available}`"
    )

def format_property_check(prop, active_booking, issues) -> str:
    if not prop:
        return "❌ Property code not found in the database."
    
    status_emoji = {
        "AVAILABLE": "✅",
        "OCCUPIED": "➡️",
        "PENDING_CLEANING": "⏳",
        "MAINTENANCE": "🛠️"
    }.get(prop.status, "❓")

    message = [f"{status_emoji} *{prop.code}* Status: `{prop.status}`"]
    if prop.status == "OCCUPIED" and active_booking:
        message.append(f"  • Guest: *{active_booking.guest_name}*")
        message.append(f"  • Check-in: `{active_booking.checkin_date}`")
        message.append(f"  • Platform: `{active_booking.platform}`")
    elif prop.status == "PENDING_CLEANING" and active_booking:
        message.append(f"  • Previous Guest: *{active_booking.guest_name}*")
        message.append(f"  • Expected Checkout: `{active_booking.checkout_date}`")
    elif prop.status == "MAINTENANCE":
        message.append(f"  • Reason: _{prop.notes or 'No reason specified.'}_")
    
    if issues:
        message.append("\n*Recent Issues:*")
        for issue in issues:
            message.append(f"  - `{issue.reported_at}`: {issue.description}")

    return "\n".join(message)

def format_occupied_list(occupied_props: list) -> str:
    if not occupied_props:
        return "✅ All properties are currently available."
    message = ["🏨 *Currently Occupied Properties:*"]
    codes = sorted([prop.code for prop in occupied_props])
    message.append(f"`{', '.join(codes)}`")
    return "\n".join(message)

def format_simple_success(message: str) -> str:
    return f"✅ *Success*\n{message}"

def format_simple_error(message: str) -> str:
    return f"❌ *Error*\n{message}"

def format_booking_history(prop_code: str, bookings: list) -> str:
    if not bookings:
        return f"No booking history found for `{prop_code}`."
    message = [f"📖 *Booking History for {prop_code}*"]
    for b in bookings:
        message.append(f"  - `{b.checkin_date}` to `{b.checkout_date or 'Present'}`: *{b.guest_name}*")
    return "\n".join(message)

def format_find_guest_results(results: list) -> str:
    if not results:
        return "❌ No active guest found matching that name."
    message = ["🔍 *Guest Search Results:*"]
    for booking in results:
        message.append(f"  • *{booking.guest_name}* is in property `{booking.property.code}`")
    return "\n".join(message)

def format_pending_cleaning_list(props: list) -> str:
    if not props:
        return "✅ No properties are currently pending cleaning."
    message = ["⏳ *Properties Pending Cleaning:*"]
    codes = sorted([prop.code for prop in props])
    message.append(f"`{', '.join(codes)}`")
    return "\n".join(message)

def format_daily_revenue_report(date_str: str, total_revenue: float, booking_count: int) -> str:
    from datetime import datetime
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    readable_date = date_obj.strftime('%B %d, %Y')
    return (
        f"💰 *Revenue Report for {readable_date}*\n\n"
        f"Total Calculated Revenue: *€{total_revenue:.2f}*\n"
        f"From `{booking_count}` bookings."
    )

def format_checkin_error_alert(property_code: str, new_guest: str, prop_status: str, existing_guest: str = None, maintenance_notes: str = None) -> tuple:
    """Generates a context-aware alert when a check-in fails."""
    from datetime import datetime
    readable_date = datetime.now().strftime('%B %d, %Y')
    
    title = f"🚨 *CHECK-IN FAILED* for `{property_code}` 🚨"
    reason = ""

    if prop_status == "OCCUPIED":
        reason = f"Property is currently occupied by *{existing_guest or 'an existing guest'}*."
    elif prop_status == "PENDING_CLEANING":
        reason = "Property is awaiting cleaning and is not yet available."
    elif prop_status == "MAINTENANCE":
        reason = f"Property is blocked for *MAINTENANCE*.\nReason: _{maintenance_notes or 'No reason specified.'}_"
    else:
        reason = f"Property is in an unbookable state: `{prop_status}`."

    alert_text = (
        f"*{readable_date}*\n{title}\n\n"
        f"{reason}\n\n"
        f"Cannot check in new guest: *{new_guest}*.\n\n"
        f"This booking is now pending relocation. Please take action!"
    )
    
    keyboard = [[
        InlineKeyboardButton("Show Available Rooms", callback_data=f"show_available:{property_code}"),
        InlineKeyboardButton("Suggest Relocation", switch_inline_query_current_chat=f"/relocate {property_code} "),
    ]]
    return alert_text, InlineKeyboardMarkup(keyboard)