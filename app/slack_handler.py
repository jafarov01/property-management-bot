# FILE: app/slack_handler.py
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
        # Ignore messages from bots or without a user ID
        if "user" not in event:
            return

        user_id = event.get("user")
        # Process messages only from the designated users
        authorized_user_ids = [
            config.SLACK_USER_ID_OF_LIST_POSTER,
            config.SLACK_USER_ID_OF_SECOND_POSTER,
        ]
        if user_id not in authorized_user_ids:
            return

        message_text = event.get("text", "")
        channel_id = event.get("channel")
        message_ts = float(event.get("ts", time.time()))
        list_date_str = datetime.date.fromtimestamp(message_ts).isoformat()

        logging.info(
            f"MESSAGE RECEIVED from {user_id} in channel {channel_id}: {message_text[:50]}..."
        )

        all_prop_codes = [p.code for p in db.query(models.Property.code).all()]

        # --- Handle 'great reset' command for system initialization ---
        if "great reset" in message_text.lower():
            logging.warning(
                "'great reset' command detected. Wiping and reseeding the database."
            )
            # Remove all scheduled checkout reminders
            for job in scheduler.get_jobs():
                if job.id.startswith("checkout_reminder_"):
                    job.remove()
            # Cascade delete is configured in models, so this will clear related bookings/issues
            db.query(models.Property).delete()
            db.query(models.EmailAlert).delete()
            db.query(models.Relocation).delete()
            db.commit()

            # Seed the database with properties from the message
            properties_to_seed = await slack_parser.parse_cleaning_list_with_ai(
                message_text
            )
            count = 0
            for prop_code in properties_to_seed:
                if (
                    prop_code
                    and prop_code != "N/A"
                    and not db.query(models.Property)
                    .filter(models.Property.code == prop_code)
                    .first()
                ):
                    db.add(models.Property(code=prop_code, status="AVAILABLE"))
                    count += 1
            db.commit()
            await telegram_client.send_telegram_message(
                bot,
                f"✅ *System Initialized*\n\nSuccessfully seeded the database with `{count}` properties.",
                topic_name="GENERAL",
            )
            return

        # --- Handle Check-in Lists ---
        if channel_id == config.SLACK_CHECKIN_CHANNEL_ID:
            new_bookings_data = await slack_parser.parse_checkin_list_with_ai(
                message_text, list_date_str
            )
            processed_bookings = []
            for booking_data in new_bookings_data:
                try:
                    prop_code = booking_data["property_code"]
                    guest_name = booking_data["guest_name"]

                    if guest_name in ["N/A", "Unknown Guest"] or prop_code == "UNKNOWN":
                        logging.warning(
                            f"Skipping booking for {prop_code} due to missing guest name or code."
                        )
                        continue

                    if prop_code not in all_prop_codes:
                        suggestions = get_close_matches(
                            prop_code, all_prop_codes, n=3, cutoff=0.7
                        )
                        original_line = next(
                            (
                                line
                                for line in message_text.split("\n")
                                if line.strip().startswith(prop_code)
                            ),
                            message_text,
                        )
                        alert_text = telegram_client.format_invalid_code_alert(
                            prop_code, original_line, suggestions
                        )
                        await telegram_client.send_telegram_message(
                            bot, alert_text, topic_name="ISSUES"
                        )
                        continue

                    prop = (
                        db.query(models.Property)
                        .filter(models.Property.code == prop_code)
                        .with_for_update()
                        .first()
                    )

                    if prop.status != "AVAILABLE":
                        if prop.status == "OCCUPIED":
                            first_booking = (
                                db.query(models.Booking)
                                .filter(
                                    models.Booking.property_id == prop.id,
                                    models.Booking.status == "Active",
                                )
                                .order_by(models.Booking.id.desc())
                                .first()
                            )
                            booking_data["status"] = "PENDING_RELOCATION"
                            second_booking = models.Booking(
                                **booking_data, property_id=prop.id
                            )
                            db.add(second_booking)
                            db.commit()
                            alert_text, reply_markup = (
                                telegram_client.format_conflict_alert(
                                    prop.code, first_booking, second_booking
                                )
                            )
                            await telegram_client.send_telegram_message(
                                bot,
                                alert_text,
                                topic_name="ISSUES",
                                reply_markup=reply_markup,
                            )
                        else:
                            booking_data["status"] = "PENDING_RELOCATION"
                            failed_booking = models.Booking(
                                **booking_data, property_id=prop.id
                            )
                            db.add(failed_booking)
                            db.commit()
                            alert_text, reply_markup = (
                                telegram_client.format_checkin_error_alert(
                                    property_code=prop_code,
                                    new_guest=booking_data["guest_name"],
                                    prop_status=prop.status,
                                    maintenance_notes=prop.notes,
                                )
                            )
                            await telegram_client.send_telegram_message(
                                bot,
                                alert_text,
                                topic_name="ISSUES",
                                reply_markup=reply_markup,
                            )
                        continue

                    prop.status = "OCCUPIED"
                    db_booking = models.Booking(property_id=prop.id, **booking_data)
                    db.add(db_booking)
                    db.flush()
                    processed_bookings.append(db_booking)
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logging.error(
                        f"Error processing a single check-in line: {booking_data}",
                        exc_info=e,
                    )
                    await telegram_client.send_telegram_message(
                        bot,
                        f"⚠️ Failed to process one line of the check-in list: `{booking_data}`. Please check it manually.",
                        topic_name="ISSUES",
                    )

            if processed_bookings:
                summary_text = telegram_client.format_daily_list_summary(
                    processed_bookings, [], [], list_date_str
                )
                await telegram_client.send_telegram_message(
                    bot, summary_text, topic_name="GENERAL"
                )

        # --- Handle Cleaning Lists ---
        elif channel_id == config.SLACK_CLEANING_CHANNEL_ID:
            properties_to_process = await slack_parser.parse_cleaning_list_with_ai(
                message_text
            )
            success_codes = []
            warnings = []
            for prop_code in properties_to_process:
                prop = (
                    db.query(models.Property)
                    .filter(models.Property.code == prop_code)
                    .first()
                )
                if not prop:
                    warnings.append(
                        f"`{prop_code}`: Code not found in database (check for typo)."
                    )
                    continue

                if prop.status == "OCCUPIED":
                    prop.status = "PENDING_CLEANING"
                    booking_to_update = (
                        db.query(models.Booking)
                        .filter(
                            models.Booking.property_id == prop.id,
                            models.Booking.status == "Active",
                        )
                        .order_by(models.Booking.id.desc())
                        .first()
                    )
                    if booking_to_update:
                        booking_to_update.checkout_date = datetime.date.fromisoformat(
                            list_date_str
                        ) + datetime.timedelta(days=1)
                        booking_to_update.status = "Departed"
                    success_codes.append(prop.code)
                else:
                    warnings.append(
                        f"`{prop_code}`: Not processed, status was already `{prop.status}`."
                    )
            db.commit()
            receipt_message = telegram_client.format_cleaning_list_receipt(
                success_codes, warnings
            )
            await telegram_client.send_telegram_message(
                bot, receipt_message, topic_name="GENERAL"
            )

            # --- Dynamic Scheduling Logic for Late Posts ---
            if success_codes:
                budapest_tz = pytz.timezone(config.TIMEZONE)
                now_budapest = datetime.datetime.now(budapest_tz)

                if now_budapest.hour >= 0 and now_budapest.minute > 5:
                    # Query for ALL properties that are currently pending cleaning
                    all_pending_props = (
                        db.query(models.Property.code)
                        .filter(models.Property.status == "PENDING_CLEANING")
                        .all()
                    )
                    all_pending_codes = [code for code, in all_pending_props]

                    if not all_pending_codes:
                        logging.info(
                            "Late cleaning list detected, but no properties are pending cleaning."
                        )
                        return

                    run_time = now_budapest + datetime.timedelta(minutes=15)
                    job_id = f"late_cleaning_{now_budapest.strftime('%Y%m%d_%H%M%S')}"

                    # Schedule a job to clean ALL pending properties
                    scheduler.add_job(
                        set_properties_to_available,
                        "date",
                        run_date=run_time,
                        args=[
                            all_pending_codes,
                            f"On-Demand Cleaning Task ({now_budapest.strftime('%H:%M')})",
                        ],
                        id=job_id,
                    )
                    logging.info(
                        f"Late cleaning list detected. Scheduled task '{job_id}' to clean all {len(all_pending_codes)} pending properties at {run_time.strftime('%H:%M:%S')}."
                    )

                    # Update the confirmation message to reflect the new logic
                    schedule_confirm_msg = (
                        f"⚠️ *Late Cleaning List Detected*\n\n"
                        f"A task has been scheduled to mark all *{len(all_pending_codes)} pending properties* as `AVAILABLE` in 15 minutes (at approx. {run_time.strftime('%H:%M')})."
                    )
                    await telegram_client.send_telegram_message(
                        bot, schedule_confirm_msg, topic_name="GENERAL"
                    )

    except Exception as e:
        db.rollback()
        logging.critical("CRITICAL ERROR IN SLACK PROCESSOR", exc_info=e)
        await telegram_client.send_telegram_message(
            bot,
            f"🚨 A critical error occurred in the Slack message processor: `{e}`. Please review the logs.",
            topic_name="ISSUES",
        )
