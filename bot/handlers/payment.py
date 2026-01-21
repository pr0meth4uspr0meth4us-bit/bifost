import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from ..config import Config

log = logging.getLogger(__name__)

WAITING_PROOF = 1


async def receive_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2: User sends photo -> Bot forwards to Admin Group"""
    user = update.effective_user

    if not update.message.photo:
        await update.message.reply_text("⚠️ Please send a <b>Photo</b> of the receipt.", parse_mode='HTML')
        return WAITING_PROOF

    photo = update.message.photo[-1]
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