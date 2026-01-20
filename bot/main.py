import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv

# Import Handlers
from handlers import (
    start_command,
    receive_proof,
    admin_approve,
    admin_reject_menu,
    admin_reject_confirm,
    admin_restore_menu,
    cancel,
    WAITING_PROOF
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("bifrost-bot")

def main():
    token = os.getenv("BIFROST_BOT_TOKEN")
    if not token:
        logger.critical("BIFROST_BOT_TOKEN not found!")
        return

    app = Application.builder().token(token).build()

    # The Payment Conversation
    payment_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            WAITING_PROOF: [MessageHandler(filters.PHOTO, receive_proof)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    )

    app.add_handler(payment_conv)

    # Admin Callbacks (The Secure Check happens inside these handlers)
    app.add_handler(CallbackQueryHandler(admin_approve, pattern="^pay_approve_"))
    app.add_handler(CallbackQueryHandler(admin_reject_menu, pattern="^pay_reject_menu_"))
    app.add_handler(CallbackQueryHandler(admin_reject_confirm, pattern="^pay_reject_confirm_"))
    app.add_handler(CallbackQueryHandler(admin_restore_menu, pattern="^pay_restore_"))

    logger.info("⚡ Bifrost Bot is listening...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()