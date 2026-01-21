from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from ..config import Config
from ..services import call_grant_premium

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