import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from requests.auth import HTTPBasicAuth

log = logging.getLogger(__name__)

# Config
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
BIFROST_API_URL = os.getenv("BIFROST_API_URL")
MY_CLIENT_ID = os.getenv("BIFROST_CLIENT_ID")
MY_CLIENT_SECRET = os.getenv("BIFROST_CLIENT_SECRET")
PAYMENT_QR_URL = "https://placehold.co/400x400/png?text=Bifrost+Pay+5+USD"

WAITING_PROOF = 1

def call_grant_premium(user_telegram_id, target_client_id):
    """Calls Bifrost Internal API to upgrade user role."""
    url = f"{BIFROST_API_URL}/internal/grant-premium"
    payload = {
        "telegram_id": str(user_telegram_id),
        "target_client_id": target_client_id
    }
    auth = HTTPBasicAuth(MY_CLIENT_ID, MY_CLIENT_SECRET)

    try:
        res = requests.post(url, json=payload, auth=auth, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Failed to call Bifrost API: {e}")
        return False

# --- USER FLOW ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    # Expected arg: pay_finance_bot_5.00
    if not args or not args[0].startswith("pay_"):
        await update.message.reply_text("👋 I am the Bifrost Gatekeeper.")
        return ConversationHandler.END

    raw_arg = args[0].replace("pay_", "")

    # Try to split by the last underscore to get Price
    try:
        # Splits "finance_bot_5.00" into ["finance_bot", "5.00"]
        target_app_id, price = raw_arg.rsplit('_', 1)
    except ValueError:
        # Fallback if no price provided
        target_app_id = raw_arg
        price = "5.00"

    context.user_data['target_app'] = target_app_id
    context.user_data['price'] = price # Store for later if needed

    # Dynamic Message
    msg = (
        f"💎 <b>Secure Payment Gateway</b>\n\n"
        f"App: <b>{target_app_id}</b>\n"
        f"Amount Due: <b>${price}</b>\n\n"
        "1. Scan the QR code below.\n"
        "2. Make the transfer.\n"
        "3. <b>Send the screenshot here.</b>"
    )

    # Optional: Update QR URL to include amount if your QR generator supports it
    # dynamic_qr = f"https://payway-qr-gen.com?amount={price}..."

    await update.message.reply_photo(
        photo=PAYMENT_QR_URL,
        caption=msg,
        parse_mode='HTML'
    )
    return WAITING_PROOF

async def receive_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not update.message.photo:
        await update.message.reply_text("Please send a photo of the receipt.")
        return WAITING_PROOF

    photo = update.message.photo[-1] # Largest size
    target_app = context.user_data.get('target_app', 'unknown')

    if not ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ System Error: Admin ID not configured.")
        return ConversationHandler.END

    await update.message.reply_text("✅ Receipt received! Waiting for admin approval...")

    # Forward to Admin
    caption = (
        f"💰 <b>Payment Request</b>\n"
        f"Target App ID: <code>{target_app}</code>\n"
        f"User: {user.full_name} (ID: <code>{user.id}</code>)\n"
    )

    # Payload: action_userid|targetApp
    # We use a pipe delimiter to pack data into callback_data
    callback_data_base = f"{user.id}|{target_app}"

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{callback_data_base}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_menu_{callback_data_base}")
    ]]

    await context.bot.send_photo(
        chat_id=ADMIN_CHAT_ID,
        photo=photo.file_id,
        caption=caption,
        parse_mode='HTML',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END

# --- ADMIN FLOW (SECURED) ---

async def _verify_admin(update: Update):
    """The Critical Security Check: Ensures clicker is ADMIN_CHAT_ID"""
    if str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await update.callback_query.answer("⛔ SECURITY ALERT: Unauthorized Access.", show_alert=True)
        return False
    return True

async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _verify_admin(update): return

    query = update.callback_query
    # Format: pay_approve_12345|finance_id
    data_part = query.data.replace("pay_approve_", "")
    user_id, target_app = data_part.split('|')

    await query.answer("Approving...")

    # 1. Call Internal API
    success = call_grant_premium(user_id, target_app)

    if success:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ <b>APPROVED</b>",
            parse_mode='HTML'
        )
        # Notify User
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 <b>Payment Accepted!</b>\n\nYour premium features are now unlocked."
            )
        except Exception:
            pass
    else:
        await query.answer("❌ API Error: Check Bifrost logs", show_alert=True)

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
    # Format: 12345|finance|amount
    data_part = query.data.replace("pay_reject_confirm_", "")
    user_id, target_app, reason = data_part.split('|')

    await query.edit_message_caption(
        caption=f"{query.message.caption}\n\n❌ <b>REJECTED ({reason})</b>",
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

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{data_part}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_menu_{data_part}")
    ]]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))