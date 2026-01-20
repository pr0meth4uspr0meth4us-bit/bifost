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
MY_CLIENT_ID = os.getenv("BIFROST_ROOT_CLIENT_ID") or os.getenv("BIFROST_CLIENT_ID")
MY_CLIENT_SECRET = os.getenv("BIFROST_ROOT_CLIENT_SECRET") or os.getenv("BIFROST_CLIENT_SECRET")

# --- LOCAL IMAGE PATH ---
# Looks for: bifrost/bot/assets/qr.jpg
BASE_DIR = Path(__file__).resolve().parent
QR_IMAGE_PATH = BASE_DIR / "assets" / "qr.jpg"
# ------------------------

WAITING_TRX_ID = 1

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or not args[0].startswith("pay_"):
        await update.message.reply_text("👋 Bifrost Payment System Online.")
        return ConversationHandler.END

    raw_arg = args[0].replace("pay_", "")

    # Parse ID and Price
    target_app_id = raw_arg
    price = "5.00"

    # Robust parsing
    if "_" in raw_arg:
        parts = raw_arg.rsplit('_', 1)
        try:
            float(parts[1])
            target_app_id = parts[0]
            price = parts[1]
        except ValueError:
            pass

    context.user_data['target_app'] = target_app_id
    context.user_data['expected_price'] = price

    msg = (
        f"💎 <b>Upgrade: {target_app_id}</b>\n"
        f"Amount Due: <b>${price}</b>\n\n"
        "1. Scan the QR code below.\n"
        "2. Make the transfer.\n"
        "3. Copy the <b>Transaction ID</b> (Trx ID).\n"
        "4. <b>Paste the Trx ID here</b> (or just the last 6 digits)."
    )

    # --- SEND LOCAL IMAGE ---
    if QR_IMAGE_PATH.exists():
        try:
            # We open the file in binary read mode ('rb')
            with open(QR_IMAGE_PATH, 'rb') as photo_file:
                await update.message.reply_photo(
                    photo=photo_file,
                    caption=msg,
                    parse_mode='HTML'
                )
        except Exception as e:
            log.error(f"Error sending local QR: {e}")
            await update.message.reply_text(f"⚠️ Error loading QR code.\n\n{msg}", parse_mode='HTML')
    else:
        log.warning(f"QR Image not found at {QR_IMAGE_PATH}")
        await update.message.reply_text(
            f"⚠️ System Warning: QR Code image missing.\n\n{msg}",
            parse_mode='HTML'
        )

    return WAITING_TRX_ID

async def receive_trx_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user = update.effective_user

    # 1. Input Validation
    if not user_input.isdigit() or len(user_input) < 6:
        await update.message.reply_text("⚠️ Invalid format. Please enter at least the last 6 digits.")
        return WAITING_TRX_ID

    target_app = context.user_data.get('target_app')

    await update.message.reply_text("🔎 Verifying payment...")

    # 2. CALL UNIVERSAL CLAIM API
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
            # Keep them in loop to retry digits
            await update.message.reply_text(f"❌ Claim Failed: {error_msg}\nPlease check your Trx ID and try again.")
            return WAITING_TRX_ID

    except Exception as e:
        log.error(f"API Error: {e}")
        await update.message.reply_text("⚠️ System Error. Try again later.")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END