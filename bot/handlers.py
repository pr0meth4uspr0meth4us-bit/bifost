import os
import logging
import requests
from pathlib import Path
from requests.auth import HTTPBasicAuth
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

log = logging.getLogger(__name__)

# --- CONFIGURATION ---
BIFROST_API_URL = os.getenv("BIFROST_API_URL", "http://localhost:8000")
# Use Root credentials for the Service, fallback to Client credentials
MY_CLIENT_ID = os.getenv("BIFROST_ROOT_CLIENT_ID") or os.getenv("BIFROST_CLIENT_ID")
MY_CLIENT_SECRET = os.getenv("BIFROST_ROOT_CLIENT_SECRET") or os.getenv("BIFROST_CLIENT_SECRET")
PAYMENT_GROUP_ID = os.getenv("PAYMENT_GROUP_ID")

# QR Code Path
BASE_DIR = Path(__file__).resolve().parent
QR_IMAGE_PATH = BASE_DIR / "assets" / "qr.jpg"

WAITING_PROOF = 1

# --- API HELPERS ---

def call_grant_premium(user_telegram_id, target_client_id):
    """Calls Bifrost Internal API to upgrade user role."""
    url = f"{BIFROST_API_URL}/internal/grant-premium"
    payload = {
        "telegram_id": str(user_telegram_id),
        "target_client_id": target_client_id
    }

    # Authenticate as the Bifrost Service itself
    auth = HTTPBasicAuth(MY_CLIENT_ID, MY_CLIENT_SECRET)

    try:
        res = requests.post(url, json=payload, auth=auth, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Failed to call Bifrost API: {e}")
        return False

# --- USER HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Step 1: User starts the bot with a payload (e.g. /start pay_finance_bot_5.00)
    """
    args = context.args

    # 1. Handle Empty Start (User just found the bot)
    if not args or not args[0].startswith("pay_"):
        await update.message.reply_text(
            "👋 <b>Bifrost Payment Gateway</b>\n\n"
            "Waiting for payment command...\n"
            "<i>(Go back to the Finance App and copy the code if the link didn't work)</i>",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    raw_arg = args[0].replace("pay_", "")

    # 2. Parse ID and Price
    target_app_id = raw_arg
    price = "5.00"

    if "_" in raw_arg:
        parts = raw_arg.rsplit('_', 1)
        try:
            float(parts[1])
            target_app_id = parts[0]
            price = parts[1]
        except ValueError:
            pass

    context.user_data['target_app'] = target_app_id

    msg = (
        f"💎 <b>Upgrade Request</b>\n"
        f"App: <code>{target_app_id}</code>\n"
        f"Amount: <b>${price}</b>\n\n"
        "1. Scan QR & Pay.\n"
        "2. Take a <b>Screenshot</b> of the receipt.\n"
        "3. <b>Send the photo here.</b>"
    )

    # Send QR Image if available, otherwise text
    if QR_IMAGE_PATH.exists():
        with open(QR_IMAGE_PATH, 'rb') as photo:
            await update.message.reply_photo(photo=photo, caption=msg, parse_mode='HTML')
    else:
        await update.message.reply_text(f"⚠️ [QR Missing]\n\n{msg}", parse_mode='HTML')

    return WAITING_PROOF

async def receive_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Step 2: User sends photo -> Bot forwards to Admin Group
    """
    user = update.effective_user

    # 1. Validate it is a photo
    if not update.message.photo:
        await update.message.reply_text("⚠️ Please send a <b>Photo</b> of the receipt.", parse_mode='HTML')
        return WAITING_PROOF

    # 2. Get the file and user data
    photo = update.message.photo[-1] # Largest size
    target_app = context.user_data.get('target_app', 'unknown')

    if not PAYMENT_GROUP_ID:
        await update.message.reply_text("⚠️ System Error: Admin Group not configured.")
        return ConversationHandler.END

    await update.message.reply_text("✅ Receipt received! Verification in progress...")

    # 3. Forward to Admin Group
    caption = (
        f"💰 <b>Payment Request</b>\n"
        f"User: {user.full_name} (ID: <code>{user.id}</code>)\n"
        f"App: <code>{target_app}</code>\n"
        f"Action: Verify Screenshot below."
    )

    # Callback data: pay_approve_USERID|APPID
    callback_data = f"{user.id}|{target_app}"

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{callback_data}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_menu_{callback_data}")
    ]]

    try:
        await context.bot.send_photo(
            chat_id=PAYMENT_GROUP_ID,
            photo=photo.file_id,
            caption=caption,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        log.error(f"Failed to forward to Admin Group: {e}")
        await update.message.reply_text("⚠️ Error contacting admin. Try again later.")
        return ConversationHandler.END

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the conversation."""
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END

# --- ADMIN ACTIONS ---

async def _verify_admin(update: Update):
    """
    Security: Only allow clicks from the Payment Group or known Admins.
    """
    chat_id = str(update.effective_chat.id)

    # Allow if message is IN the payment group
    # (Or you could check specific user IDs here)
    if chat_id == str(PAYMENT_GROUP_ID):
        return True

    await update.callback_query.answer("⛔ Unauthorized.", show_alert=True)
    return False

async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _verify_admin(update): return

    query = update.callback_query
    data_part = query.data.replace("pay_approve_", "")

    try:
        user_id, target_app = data_part.split('|', 1)
    except ValueError:
        await query.answer("❌ Error: Invalid Data")
        return

    await query.answer("Approving...")

    # Call Internal API
    success = call_grant_premium(user_id, target_app)

    if success:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ <b>APPROVED</b> by {update.effective_user.first_name}",
            parse_mode='HTML'
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 <b>Payment Accepted!</b>\n\nYour premium features are now unlocked."
            )
        except Exception:
            pass
    else:
        await query.answer("❌ API Error. Check Logs.", show_alert=True)

async def admin_reject_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _verify_admin(update): return
    query = update.callback_query
    data_part = query.data.replace("pay_reject_menu_", "")

    keyboard = [
        [InlineKeyboardButton("Bad Amount", callback_data=f"pay_reject_confirm_{data_part}|amount")],
        [InlineKeyboardButton("Fake/Blurry", callback_data=f"pay_reject_confirm_{data_part}|fake")],
        [InlineKeyboardButton("Duplicate", callback_data=f"pay_reject_confirm_{data_part}|dup")],
        [InlineKeyboardButton("🔙 Back", callback_data=f"pay_restore_{data_part}")]
    ]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_reject_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _verify_admin(update): return
    query = update.callback_query
    # Format: pay_reject_confirm_12345|finance|amount
    data_part = query.data.replace("pay_reject_confirm_", "")

    try:
        user_id, target_app, reason = data_part.split('|')
    except ValueError:
        await query.answer("❌ Data Error")
        return

    await query.edit_message_caption(
        caption=f"{query.message.caption}\n\n❌ <b>REJECTED ({reason})</b> by {update.effective_user.first_name}",
        parse_mode='HTML'
    )
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ Payment rejected.\nReason: {reason}\nPlease try again."
        )
    except Exception:
        pass

async def admin_restore_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _verify_admin(update): return
    query = update.callback_query
    data_part = query.data.replace("pay_restore_", "")

    # Restore original buttons
    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{data_part}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_menu_{data_part}")
    ]]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))