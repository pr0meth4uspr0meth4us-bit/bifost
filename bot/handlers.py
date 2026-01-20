import os
import logging
import requests
from pathlib import Path
from requests.auth import HTTPBasicAuth
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

log = logging.getLogger(__name__)

# Config
BIFROST_API_URL = os.getenv("BIFROST_API_URL", "http://localhost:8000")
# Fallback to defaults if env vars are empty to prevent crash
MY_CLIENT_ID = os.getenv("BIFROST_ROOT_CLIENT_ID") or "finance_bot"
MY_CLIENT_SECRET = os.getenv("BIFROST_ROOT_CLIENT_SECRET") or "secret"

# QR Code Path
BASE_DIR = Path(__file__).resolve().parent
QR_IMAGE_PATH = BASE_DIR / "assets" / "qr.jpg"

WAITING_TRX_ID = 1

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles /start pay_CLIENTID_PRICE
    """
    args = context.args

    # --- DEBUGGING BLOCK: REMOVE IN PRODUCTION ---
    # This will tell you exactly what the bot sees.
    log.info(f"DEBUG: /start called. Args: {args}")
    # ---------------------------------------------

    # Case 1: No arguments received (User just typed /start)
    if not args or not args[0]:
        await update.message.reply_text(
            f"👋 <b>Bifrost Gatekeeper</b>\n"
            f"Status: Online\n"
            f"Debug: No parameters received.",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    payload = args[0]

    # Case 2: Argument exists but format is wrong
    if not payload.startswith("pay_"):
        await update.message.reply_text(
            f"⚠️ <b>Invalid Command</b>\n"
            f"Received: <code>{payload}</code>\n"
            f"Expected format: <code>pay_client_id_price</code>",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    # Clean the prefix
    raw_arg = payload.replace("pay_", "")

    # --- PARSING LOGIC ---
    # Attempt to split "client_id" and "price"
    # We look for the LAST underscore. If the part after it is a number, it's the price.
    target_app_id = raw_arg
    price = "5.00" # Default

    if "_" in raw_arg:
        try:
            # Split from the right, max 1 split
            parts = raw_arg.rsplit('_', 1)
            # Check if the right part is a valid float (price)
            float(parts[1])

            # If valid, assign variables
            target_app_id = parts[0]
            price = parts[1]
        except ValueError:
            # The last part wasn't a number (e.g. "my_client_id_v2")
            # So the whole thing is the ID
            target_app_id = raw_arg

    # Store in context for the next step (receiving the Trx ID)
    context.user_data['target_app'] = target_app_id
    context.user_data['expected_price'] = price

    msg = (
        f"💎 <b>Upgrade Request Detected</b>\n\n"
        f"📱 <b>App:</b> {target_app_id}\n"
        f"💵 <b>Amount:</b> ${price}\n\n"
        "<b>Steps to Pay:</b>\n"
        "1. Scan the QR code below.\n"
        "2. Make the transfer.\n"
        "3. Copy the <b>Transaction ID</b>.\n"
        "4. <b>Paste the Trx ID here.</b>"
    )

    # Send Image or Fallback Text
    if QR_IMAGE_PATH.exists():
        with open(QR_IMAGE_PATH, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=msg, parse_mode='HTML')
    else:
        await update.message.reply_text(f"⚠️ [QR Missing]\n\n{msg}", parse_mode='HTML')

    return WAITING_TRX_ID

async def receive_trx_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user = update.effective_user

    # Basic validation (simple digit check)
    if not user_input.isdigit() or len(user_input) < 4:
        await update.message.reply_text("⚠️ Invalid ID. Please enter only the digits (e.g. 17688...).")
        return WAITING_TRX_ID

    target_app = context.user_data.get('target_app', 'unknown')

    await update.message.reply_text("🔎 Verifying payment...")

    # CALL API
    url = f"{BIFROST_API_URL}/internal/payments/claim"
    payload = {
        "trx_input": user_input,
        "target_app_id": target_app,
        "identity_type": "telegram_id",
        "identity_value": str(user.id)
    }

    auth = HTTPBasicAuth(MY_CLIENT_ID, MY_CLIENT_SECRET)

    try:
        res = requests.post(url, json=payload, auth=auth, timeout=10)
        data = res.json()

        if res.status_code == 200 and data.get('success'):
            await update.message.reply_text(
                f"🎉 <b>Success!</b>\n\n{data['message']}\n"
                "Your account has been upgraded.",
                parse_mode='HTML'
            )
            return ConversationHandler.END
        else:
            error_msg = data.get('error', 'Unknown error')
            await update.message.reply_text(f"❌ Claim Failed: {error_msg}\nCheck the ID and try again.")
            return WAITING_TRX_ID

    except Exception as e:
        log.error(f"API Error: {e}")
        await update.message.reply_text("⚠️ System Error. Try again later.")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END