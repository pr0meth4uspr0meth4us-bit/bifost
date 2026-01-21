import logging
import re
from telegram import Update
from telegram.ext import ContextTypes
from pymongo import MongoClient
from datetime import datetime

# Central Config
from config import Config

# Regex: "$5.00 paid by Name... Trx. ID: 12345"
ABA_PATTERN = re.compile(
    r"\$(\d+\.?\d*)\s+paid by\s+(.+?)\s+via.*Trx\. ID:\s*(\d+)",
    re.IGNORECASE | re.DOTALL
)

logger = logging.getLogger("bifrost-listener")

def get_db():
    client = MongoClient(Config.MONGO_URI)
    return client[Config.DB_NAME]

async def aba_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Listens to messages in the Payment Group."""
    chat_id = str(update.effective_chat.id)

    # Use Config to check if this is the correct group
    if Config.PAYMENT_GROUP_ID and chat_id != str(Config.PAYMENT_GROUP_ID):
        return

    msg = update.effective_message.text
    if not msg:
        return

    match = ABA_PATTERN.search(msg)
    if match:
        amount_str = match.group(1)
        payer_name = match.group(2)
        trx_id = match.group(3)

        logger.info(f"💸 Detected Payment: {amount_str} from {payer_name} (ID: {trx_id})")

        try:
            db = get_db()
            exists = db.payment_logs.find_one({"trx_id": trx_id})
            if not exists:
                db.payment_logs.insert_one({
                    "trx_id": trx_id,
                    "amount": float(amount_str),
                    "currency": "USD",
                    "payer_name": payer_name,
                    "raw_text": msg,
                    "source_group_id": chat_id,
                    "status": "unclaimed",
                    "claimed_by_account_id": None,
                    "created_at": datetime.utcnow()
                })
                logger.info("✅ Payment stored in DB.")
        except Exception as e:
            logger.error(f"Failed to save payment: {e}")