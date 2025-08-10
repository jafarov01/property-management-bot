# FILE: app/utils/validators.py
# ==============================================================================
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from telegram import Update
from .. import models, telegram_client

async def get_property_from_context(update: Update, context_args: list, db: AsyncSession):
    """
    Validates command arguments and fetches a property from the database asynchronously.
    """
    if not context_args:
        usage_command = update.message.text.split(" ")[0]
        usage_example = f"Example: `{usage_command} A1`"
        error_message = telegram_client.format_simple_error(
            f"Property code is required.\n{usage_example}"
        )
        await update.message.reply_text(error_message, parse_mode="Markdown")
        return None

    prop_code = context_args[0].upper()
    
    stmt = select(models.Property).options(joinedload(models.Property.issues)).filter(models.Property.code == prop_code)
    result = await db.execute(stmt)
    prop = result.scalar_one_or_none()

    if not prop:
        error_message = telegram_client.format_simple_error(
            f"Property `{prop_code}` not found in the database."
        )
        await update.message.reply_text(error_message, parse_mode="Markdown")
        return None

    return prop