# bot/handlers/admin.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from ..config import Config
from ..services import call_grant_premium, get_app_details, check_admin_permission


async def _verify_admin(update: Update, target_client_id=None):
    """
    Security Check. Allows access if:
    1. The message is in the Payment Group (Chat ID check).
    2. OR The User is a verified Admin of the target_client_id (App Admin).
    """
    user = update.effective_user
    chat_id = str(update.effective_chat.id)

    # 1. Check Global Admin Group
    if Config.PAYMENT_GROUP_ID and chat_id == str(Config.PAYMENT_GROUP_ID):
        return True

    # 2. Check App-Specific Admin Permission (If we know the target app)
    if target_client_id:
        is_app_admin = check_admin_permission(str(user.id), target_client_id)
        if is_app_admin:
            return True

    await update.callback_query.answer("⛔ Unauthorized. You are not an admin for this app.", show_alert=True)
    return False


async def admin_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_part = query.data.replace("pay_approve_", "")

    try:
        user_id, target_app_client_id = data_part.split('|', 1)
    except ValueError:
        await query.answer("❌ Error: Invalid Data")
        return

    # Pass target_app to verification
    if not await _verify_admin(update, target_client_id=target_app_client_id): return

    await query.answer("Approving...")

    # 1. Grant the Role in DB (Handles both ObjectId and Telegram ID)
    success = call_grant_premium(user_id, target_app_client_id)

    if success:
        # 2. Fetch Friendly Name for Display
        app_doc = get_app_details(target_app_client_id)
        display_name = app_doc.get('app_name', target_app_client_id) if app_doc else target_app_client_id

        # 3. Update Admin Message
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ <b>APPROVED</b> by {update.effective_user.first_name}",
            parse_mode='HTML'
        )

        # 4. Notify User (Safely)
        if user_id.isdigit():
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 <b>Payment Accepted!</b>\n\nYour features are now unlocked for App: <b>{display_name}</b>.",
                    parse_mode='HTML'
                )
            except Exception:
                pass
        else:
            # Web user - webhook handles notification
            pass

    else:
        await query.answer("❌ API Error. Check Logs.", show_alert=True)


async def admin_reject_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_part = query.data.replace("pay_reject_menu_", "")

    # Extract app id from data_part to check permissions (data_part = "user_id|client_id")
    try:
        _, target_app = data_part.split('|', 1)
    except ValueError:
        await query.answer("❌ Data Error")
        return

    if not await _verify_admin(update, target_client_id=target_app): return

    keyboard = [
        [InlineKeyboardButton("Bad Amount", callback_data=f"pay_reject_confirm_{data_part}|amount")],
        [InlineKeyboardButton("Fake/Blurry", callback_data=f"pay_reject_confirm_{data_part}|fake")],
        [InlineKeyboardButton("Duplicate", callback_data=f"pay_reject_confirm_{data_part}|dup")],
        [InlineKeyboardButton("🔙 Back", callback_data=f"pay_restore_{data_part}")]
    ]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_reject_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data_part = query.data.replace("pay_reject_confirm_", "")

    try:
        user_id, target_app, reason = data_part.split('|')
    except ValueError:
        await query.answer("❌ Data Error")
        return

    if not await _verify_admin(update, target_client_id=target_app): return

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
    query = update.callback_query
    data_part = query.data.replace("pay_restore_", "")

    try:
        _, target_app = data_part.split('|', 1)
    except ValueError:
        await query.answer("❌ Data Error")
        return

    if not await _verify_admin(update, target_client_id=target_app): return

    keyboard = [[
        InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{data_part}"),
        InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_menu_{data_part}")
    ]]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))