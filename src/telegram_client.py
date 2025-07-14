# FILE: telegram_client.py
# ==============================================================================
# UPDATED: The email notification format now includes the reservation number.
# ==============================================================================

import datetime
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import TELEGRAM_TARGET_CHAT_ID, TELEGRAM_TOPIC_IDS

async def send_telegram_message(bot: telegram.Bot, text: str, topic_name: str = "GENERAL", reply_markup=None, parse_mode: str = 'Markdown'):
    """Sends a message to a specific topic and returns the sent message object."""
    topic_id = TELEGRAM_TOPIC_IDS.get(topic_name)
    message_thread_id_to_send = topic_id if topic_name != "GENERAL" else None
    
    return await bot.send_message(
        chat_id=TELEGRAM_TARGET_CHAT_ID,
        text=text,
        message_thread_id=message_thread_id_to_send,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )

def format_email_notification(parsed_data: dict, alert_id: int) -> tuple:
    """Formats a high-priority, interactive notification including a summary and reservation number."""
    category = parsed_data.get("category", "Uncategorized Email")
    guest = parsed_data.get("guest_name")
    prop = parsed_data.get("property_code")
    platform = parsed_data.get("platform")
    summary = parsed_data.get("summary")
    reservation_number = parsed_data.get("reservation_number") # <-- New field
    
    title = f"‼️ *URGENT EMAIL: {category}* ‼️"
    platform_info = f"from *{platform or 'Unknown'}*"
    
    message = [f"{title} {platform_info}"]

    if summary:
        message.append(f"\n*Summary:* _{summary}_")

    details = []
    if guest: details.append(f"  - **Guest:** {guest}")
    if reservation_number: details.append(f"  - **Reservation #:** `{reservation_number}`") # <-- New line
    if prop: details.append(f"  - **Property:** `{prop}`")
    
    if details:
        message.append("\n*Details:*")
        message.extend(details)

    keyboard = [[
        InlineKeyboardButton("✅ Mark as Handled", callback_data=f"handle_email:{alert_id}")
    ]]
    
    return "\n".join(message), InlineKeyboardMarkup(keyboard)

# ... (The rest of the file remains exactly the same) ...

def format_daily_list_summary(checkins: list, cleanings: list, pending_cleanings: list, date_str: str) -> str:
    date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
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

def format_conflict_alert(prop_code: str, first_booking, second_booking) -> tuple:
    readable_date = datetime.datetime.now().strftime('%B %d, %Y')
    alert_text = (
        f"*{readable_date}*\n🚨 *OVERBOOKING CONFLICT* for `{prop_code}` 🚨\n\n"
        f"Two bookings exist for the same property. Please choose which guest to relocate.\n\n"
        f"1️⃣ *First Guest (Currently Active):*\n"
        f"  - Name: *{first_booking.guest_name}*\n"
        f"  - Platform: `{first_booking.platform}`\n\n"
        f"2️⃣ *Second Guest (Pending Relocation):*\n"
        f"  - Name: *{second_booking.guest_name}*\n"
        f"  - Platform: `{second_booking.platform}`\n\n"
        f"To resolve, use `/relocate {prop_code} [new_room] [YYYY-MM-DD]`."
    )
    keyboard = [[
        InlineKeyboardButton(f"Keep 2nd Guest (Relocate {first_booking.guest_name})", callback_data=f"swap_relocation:{first_booking.id}:{second_booking.id}"),
    ], [
        InlineKeyboardButton("Show Available Rooms", callback_data=f"show_available:{prop_code}")
    ]]
    return alert_text, InlineKeyboardMarkup(keyboard)

def format_checkin_error_alert(property_code: str, new_guest: str, prop_status: str, maintenance_notes: str = None) -> tuple:
    readable_date = datetime.datetime.now().strftime('%B %d, %Y')
    title = f"🚨 *CHECK-IN FAILED* for `{property_code}` 🚨"
    reason = ""
    if prop_status == "PENDING_CLEANING":
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

def format_handled_email_notification(original_text: str, handler_name: str) -> str:
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    cleaned_text = original_text.replace("‼️ *URGENT EMAIL:", "📧 *").replace("* ‼️", "*")
    return f"{cleaned_text}\n\n---\n✅ *Handled by {handler_name} at {timestamp}*"

def format_email_reminder() -> str:
    return "🚨🚨 *REMINDER: ACTION STILL REQUIRED* 🚨🚨\nThe alert above has not been handled yet. Please review and take action."

def format_available_list(available_props: list, for_relocation_from: str = None) -> str:
    if not available_props:
        return "❌ No properties are currently available."
    message = ["✅ *Available Properties:*"]
    codes = sorted([prop.code for prop in available_props])
    message.append(f"`{', '.join(codes)}`")
    if for_relocation_from:
        message.append(f"\n_To relocate from `{for_relocation_from}`, type:_ `/relocate {for_relocation_from} [new_room] [YYYY-MM-DD]`")
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
    date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d')
    readable_date = date_obj.strftime('%B %d, %Y')
    return (
        f"💰 *Revenue Report for {readable_date}*\n\n"
        f"Total Calculated Revenue: *€{total_revenue:.2f}*\n"
        f"From `{booking_count}` bookings."
    )

def format_checkout_reminder_alert(guest_name: str, property_code: str, checkout_date: str) -> str:
    return (
        f"‼️ *HIGH PRIORITY REMINDER* ‼️\n\n"
        f"A relocated guest, *{guest_name}*, is scheduled to check out from property `{property_code}` tomorrow, *{checkout_date}*.\n\n"
        f"Please ensure you **add `{property_code}` to tomorrow's cleaning list**."
    )

def format_relocation_history(relocations: list) -> str:
    if not relocations:
        return "✅ No relocation history found."
    message = ["📖 *Recent Relocation History:*\n"]
    for r in relocations:
        date_str = r.relocated_at.strftime('%Y-%m-%d')
        message.append(f"- `{date_str}`: *{r.guest_name}* was moved from `{r.original_property_code}` to `{r.new_property_code}`.")
    return "\n".join(message)

def format_daily_briefing(time_of_day: str, occupied: int, pending_cleaning: int, maintenance: int, available: int) -> str:
    readable_date = datetime.datetime.now().strftime('%B %d, %Y')
    return (
        f"*{time_of_day} Briefing - {readable_date}*\n\n"
        f"Here is the current operational status:\n"
        f"➡️ Occupied: `{occupied}`\n"
        f"⏳ Pending Cleaning: `{pending_cleaning}`\n"
        f"🛠️ Maintenance: `{maintenance}`\n"
        f"✅ Available: `{available}`"
    )

def format_cleaning_list_receipt(success_codes: list, warnings: list) -> str:
    message = ["✅ *Cleaning List Processed*"]
    if success_codes:
        message.append(f"\nThe following {len(success_codes)} properties were correctly marked as `PENDING_CLEANING`:")
        message.append(f"`{', '.join(sorted(success_codes))}`")
    else:
        message.append("\nNo properties were updated.")
    if warnings:
        message.append("\n\n⚠️ *Warnings (These were NOT processed):*")
        for warning in warnings:
            message.append(f"  - {warning}")
    return "\n".join(message)

def format_invalid_code_alert(invalid_code: str, original_message: str, suggestions: list = None) -> str:
    alert_text = (
        f"❓ *Invalid Property Code Detected*\n\n"
        f"An operation was attempted for property code `{invalid_code}`, but this code does not exist in the database.\n\n"
    )
    if suggestions:
        alert_text += f"*Did you mean one of these?* `{', '.join(suggestions)}`\n\n"
    alert_text += f"The original message was:\n`{original_message}`\n\nPlease check for a typo and re-submit."
    return alert_text
