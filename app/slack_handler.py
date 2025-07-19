# FILE: app/slack_handler.py
# ==============================================================================
# VERSION: 2.0
# UPDATED: The dynamic scheduling logic for late cleaning lists has been updated.
# Now, any valid late list will trigger a task to process ALL properties
# currently in PENDING_CLEANING status, not just those on the list.
# ==============================================================================
import logging
import time
import datetime
import pytz
from difflib import get_close_matches
from sqlalchemy.orm import Session
from telegram import Bot

from . import config, slack_parser, models, telegram_client
from .utils.db_manager import db_session_manager
from .scheduled_tasks import scheduler, set_properties_to_available

@db_session_manager
async def process_slack_message(payload: dict, bot: Bot, *, db: Session):
    """
    Parses and processes messages from designated Slack channels to update the database.
    """
    try:
        event = payload.get("event", {})
        if 'user' not in event:
            return

        user_id = event.get('user')
        authorized_user_ids = [
            config.SLACK_USER_ID_OF_LIST_POSTER,
            config.SLACK_USER_ID_OF_SECOND_POSTER
        ]
        if user_id not in authorized_user_ids:
            return

        message_text = event.get('text', '')
        channel_id = event.get('channel')
        message_ts = float(event.get('ts', time.time()))
        list_date_str = datetime.date.fromtimestamp(message_ts).isoformat()
        
        logging.info(f"MESSAGE RECEIVED from {user_id} in channel {channel_id}: {message_text[:50]}...")
        
        all_prop_codes = [p.code for p in db.query(models.Property.code).all()]

        # --- Handle 'great reset' command for system initialization ---
        if "great reset" in message_text.lower():
            # ... (this logic remains unchanged)
            return

        # --- Handle Check-in Lists ---
        if channel_id == config.SLACK_CHECKIN_CHANNEL_ID:
            # ... (this logic remains unchanged)

        # --- Handle Cleaning Lists ---
        elif channel_id == config.SLACK_CLEANING_CHANNEL_ID:
            properties_to_process = await slack_parser.parse_cleaning_list_with_ai(message_text)
            success_codes = []
            warnings = []
            for prop_code in properties_to_process:
                prop = db.query(models.Property).filter(models.Property.code == prop_code).first()
                if not prop:
                    warnings.append(f"`{prop_code}`: Code not found in database (check for typo).")
                    continue
                
                if prop.status == "OCCUPIED":
                    prop.status = "PENDING_CLEANING"
                    booking_to_update = db.query(models.Booking).filter(models.Booking.property_id == prop.id, models.Booking.status == "Active").order_by(models.Booking.id.desc()).first()
                    if booking_to_update:
                        booking_to_update.checkout_date = datetime.date.fromisoformat(list_date_str) + datetime.timedelta(days=1)
                        booking_to_update.status = "Departed"
                    success_codes.append(prop.code)
                else:
                    warnings.append(f"`{prop_code}`: Not processed, status was already `{prop.status}`.")
            db.commit()
            receipt_message = telegram_client.format_cleaning_list_receipt(success_codes, warnings)
            await telegram_client.send_telegram_message(bot, receipt_message, topic_name="GENERAL")

            # --- UPDATED: Dynamic Scheduling Logic ---
            # If at least one valid property was on the list, trigger the logic.
            if success_codes:
                budapest_tz = pytz.timezone(config.TIMEZONE)
                now_budapest = datetime.datetime.now(budapest_tz)
                
                # Check if the list was posted late (after 00:05 on the same day)
                if now_budapest.hour >= 0 and now_budapest.minute > 5:
                    # Query for ALL properties that are currently pending cleaning
                    all_pending_props = db.query(models.Property.code).filter(models.Property.status == "PENDING_CLEANING").all()
                    all_pending_codes = [code for code, in all_pending_props]

                    if not all_pending_codes:
                        logging.info("Late cleaning list detected, but no properties are pending cleaning.")
                        return

                    run_time = now_budapest + datetime.timedelta(minutes=15)
                    job_id = f"late_cleaning_{now_budapest.strftime('%Y%m%d_%H%M%S')}"
                    
                    # Schedule a job to clean ALL pending properties
                    scheduler.add_job(
                        set_properties_to_available,
                        'date',
                        run_date=run_time,
                        args=[all_pending_codes, f"On-Demand Cleaning Task ({now_budapest.strftime('%H:%M')})"],
                        id=job_id
                    )
                    logging.info(f"Late cleaning list detected. Scheduled task '{job_id}' to clean all {len(all_pending_codes)} pending properties at {run_time.strftime('%H:%M:%S')}.")
                    
                    # Update the confirmation message to reflect the new logic
                    schedule_confirm_msg = (
                        f"⚠️ *Late Cleaning List Detected*\n\n"
                        f"A task has been scheduled to mark all *{len(all_pending_codes)} pending properties* as `AVAILABLE` in 15 minutes (at approx. {run_time.strftime('%H:%M')})."
                    )
                    await telegram_client.send_telegram_message(bot, schedule_confirm_msg, topic_name="GENERAL")

    except Exception as e:
        db.rollback()
        logging.critical("CRITICAL ERROR IN SLACK PROCESSOR", exc_info=e)
        await telegram_client.send_telegram_message(
            bot,
            f"🚨 A critical error occurred in the Slack message processor: `{e}`. Please review the logs.",
            topic_name="ISSUES"
        )