import os
import logging
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from dotenv import load_dotenv

# Ensure safe env loading
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / '.env'
if not ENV_FILE.exists():
    ENV_FILE = BASE_DIR.parent / '.env'
load_dotenv(dotenv_path=ENV_FILE)

from handlers import (
    start_command, receive_trx_id, cancel, WAITING_TRX_ID
)
from group_listener import aba_message_handler

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

    # 1. GROUP LISTENER
    # Catches ABA receipts in the Payment Group
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, aba_message_handler))

    # 2. USER CLAIM CONVERSATION
    payment_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            WAITING_TRX_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_trx_id)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )

    app.add_handler(payment_conv)

    logger.info("⚡ Bifrost Bot is listening...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()