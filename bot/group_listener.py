import logging
import re
import os
from telegram import Update
from telegram.ext import ContextTypes
from pymongo import MongoClient
from datetime import datetime

# Setup direct DB access (Bot listens directly)
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "bifrost_db")

# Regex to parse ABA receipt:
# "$5.00 paid by Name... Trx. ID: 12345"
ABA_PATTERN = re.compile(
    r"\$(\d+\.?\d*)\s+paid by\s+(.+?)\s+via.*Trx\. ID:\s*(\d+)",
    re.IGNORECASE | re.DOTALL
)

logger = logging.getLogger("bifrost-listener")

def get_db():
    client = MongoClient(MONGO_URI)
    return client[DB_NAME]

async def aba_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Listens to messages in the Payment Group.
    If it looks like an ABA receipt, saves it to DB.
    """
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
            # Check for duplicates before inserting
            exists = db.payment_logs.find_one({"trx_id": trx_id})
            if not exists:
                db.payment_logs.insert_one({
                    "trx_id": trx_id,
                    "amount": float(amount_str),
                    "currency": "USD", # Defaulting to USD based on regex '$'
                    "payer_name": payer_name,
                    "raw_text": msg,
                    "status": "unclaimed",
                    "claimed_by_account_id": None,
                    "created_at": datetime.utcnow()
                })
                logger.info("✅ Payment stored in DB.")
        except Exception as e:
            logger.error(f"Failed to save payment: {e}")