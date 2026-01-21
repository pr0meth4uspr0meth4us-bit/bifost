import logging
import requests
from pathlib import Path
from requests.auth import HTTPBasicAuth
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

# Import from central config
from config import Config

# Helper to access DB for app names
from bot.group_listener import get_db

log = logging.getLogger(__name__)

# QR Code Path
BASE_DIR = Path(__file__).resolve().parent
QR_IMAGE_PATH = BASE_DIR / "assets" / "qr.jpg"

WAITING_PROOF = 1


# --- API HELPERS ---

def call_grant_premium(user_telegram_id, target_client_id):
    """Calls Bifrost Internal API to upgrade user role."""
    url = f"{Config.BIFROST_API_URL}/internal/grant-premium"
    payload = {
        "telegram_id": str(user_telegram_id),
        "target_client_id": target_client_id
    }

    # Authenticate as the Bifrost Service itself
    auth = HTTPBasicAuth(Config.BIFROST_ROOT_CLIENT_ID, Config.BIFROST_ROOT_CLIENT_SECRET)

    try:
        res = requests.post(url, json=payload, auth=auth, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Failed to call Bifrost API: {e}")
        return False


def get_app_details(client_id):
    """Fetches App Name to display nicely in the Bot."""
    try:
        db = get_db()
        app = db.applications.find_one({"client_id": client_id})
        return app
    except Exception as e:
        log.error(f"DB Error fetching app details: {e}")
        return None


# --- USER HANDLERS ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles /start <payload> OR /pay <payload>.
    Supports two modes:
    1. Enterprise (Secure): Payload is a Transaction ID (e.g., 'tx-a1b2c3...')
    2. Legacy (Insecure): Payload is 'client_id__price__...' (Retained for backward compat)
    """
    args = context.args
    payload = args[0] if args else None

    if not payload:
        await update.message.reply_text(
            "👋 <b>Bifrost Payment Gateway</b>\n\n"
            "Please use the payment button provided in your app.\n"
            "Or use: <code>/pay [transaction_id]</code>",
            parse_mode='HTML'
        )
        return ConversationHandler.END

    ctx_data = {}

    try:
        # --- MODE 1: SECURE DATABASE LOOKUP (Enterprise) ---
        if payload.startswith("tx-"):
            db = get_db()
            tx = db.transactions.find_one({"transaction_id": payload})

            if not tx:
                await update.message.reply_text("❌ Error: Invalid or expired Transaction ID.")
                return ConversationHandler.END

            if tx.get('status') == 'completed':
                await update.message.reply_text("✅ This transaction is already completed.")
                return ConversationHandler.END

            # Fetch App Details for Branding
            app_doc = db.applications.find_one({"_id": tx['app_id']})
            app_name = app_doc.get('app_name') if app_doc else "Unknown App"
            client_id = app_doc.get('client_id') if app_doc else "unknown"

            # Populate Context from DB (TRUSTED DATA)
            ctx_data = {
                "client_id": client_id,
                "app_name": app_name,
                "amount": tx['amount'],
                "duration": tx.get('duration', '1m'),
                "target_role": tx.get('target_role', 'premium'),
                "ref_id": tx.get('client_ref_id', 'N/A'),
                "transaction_id": payload  # Store the ID to link proof later
            }

        # --- MODE 2: LEGACY PARAMETER PARSING (Deprecated/Insecure) ---
        else:
            # Normalize separator
            clean_payload = payload.replace("|", "__").replace(" ", "__")
            parts = clean_payload.split("__")

            if len(parts) < 2:
                await update.message.reply_text("❌ Invalid format.")
                return ConversationHandler.END

            # Parse Logic (Keep existing logic here)
            client_id = parts[0]
            price = parts[1]
            duration = parts[2] if len(parts) > 2 else "1m"
            target_role = parts[3] if len(parts) > 3 else "premium_user"
            ref_id = parts[4] if len(parts) > 4 else "N/A"

            # Lookup Name
            db = get_db()
            app_doc = db.applications.find_one({"client_id": client_id})
            app_name = app_doc.get('app_name', 'Unknown App') if app_doc else 'Unknown'

            ctx_data = {
                "client_id": client_id,
                "app_name": app_name,
                "amount": price,
                "duration": duration,
                "target_role": target_role,
                "ref_id": ref_id
            }

        # --- COMMON UI GENERATION ---

        # Save to user context
        context.user_data['payment_context'] = ctx_data

        # Friendly Duration
        dur_map = {'1m': '1 Month', '3m': '3 Months', '6m': '6 Months', '1y': '1 Year', 'lifetime': 'Lifetime'}
        duration_text = dur_map.get(ctx_data['duration'], ctx_data['duration'])

        msg = (
            f"💎 <b>Secure Payment via Bifrost</b>\n"
            f"────────────────\n"
            f"📱 <b>App:</b> {ctx_data['app_name']}\n"
            f"🏷 <b>Plan:</b> {ctx_data['target_role'].replace('_', ' ').title()}\n"
            f"⏳ <b>Duration:</b> {duration_text}\n"
            f"💵 <b>Total:</b> ${ctx_data['amount']}\n"
            f"🧾 <b>Ref:</b> <code>{ctx_data['ref_id']}</code>\n"
            f"────────────────\n\n"
            "1. <b>Scan QR</b> code below.\n"
            "2. Make the transfer.\n"
            "3. <b>Send a Screenshot</b> of the receipt here."
        )

        if QR_IMAGE_PATH.exists():
            with open(QR_IMAGE_PATH, 'rb') as photo:
                await update.message.reply_photo(photo=photo, caption=msg, parse_mode='HTML')
        else:
            await update.message.reply_text(f"⚠️ [QR Missing]\n\n{msg}", parse_mode='HTML')

        return WAITING_PROOF

    except Exception as e:
        log.error(f"Handler error: {e}")
        await update.message.reply_text("❌ System Error.")
        return ConversationHandler.END


async def receive_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2: User sends photo -> Bot forwards to Admin Group"""
    user = update.effective_user

    if not update.message.photo:
        await update.message.reply_text("⚠️ Please send a <b>Photo</b> of the receipt.", parse_mode='HTML')
        return WAITING_PROOF

    photo = update.message.photo[-1]

    # Retrieve Context
    pay_ctx = context.user_data.get('payment_context', {})
    target_app = pay_ctx.get('client_id') or context.user_data.get('target_app', 'unknown')
    app_name = pay_ctx.get('app_name', target_app)
    amount = pay_ctx.get('amount', '?')

    if not Config.PAYMENT_GROUP_ID:
        await update.message.reply_text("⚠️ System Error: Admin Group not configured.")
        return ConversationHandler.END

    await update.message.reply_text("✅ Receipt received! Verification in progress...")

    caption = (
        f"💰 <b>Payment Request</b>\n"
        f"User: {user.full_name} (ID: <code>{user.id}</code>)\n"
        f"App: <b>{app_name}</b>\n"
        f"Amount: ${amount}\n"
        f"Action: Verify Screenshot below."
    )

    callback_data = f"{user.id}|{target_app}"

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{callback_data}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_menu_{callback_data}")
    ]]

    try:
        await context.bot.send_photo(
            chat_id=Config.PAYMENT_GROUP_ID,
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
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END


# --- ADMIN ACTIONS ---

async def _verify_admin(update: Update):
    """Security: Only allow clicks from the Payment Group."""
    chat_id = str(update.effective_chat.id)
    if chat_id == str(Config.PAYMENT_GROUP_ID):
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

    success = call_grant_premium(user_id, target_app)

    if success:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ <b>APPROVED</b> by {update.effective_user.first_name}",
            parse_mode='HTML'
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 <b>Payment Accepted!</b>\n\nYour features are now unlocked for App: {target_app}."
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

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{data_part}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_menu_{data_part}")
    ]]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))