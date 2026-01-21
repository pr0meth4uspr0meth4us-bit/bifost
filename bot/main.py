import sys
import os

# --- PATH FIX: Add project root to sys.path ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler

# Import Central Config
from config import Config

# Absolute imports
from bot.handlers import (
    start_command, receive_proof, cancel,
    admin_approve, admin_reject_menu, admin_reject_confirm, admin_restore_menu,
    WAITING_PROOF
)
from bot.persistence import MongoPersistence

# Configure logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("bifrost-bot")

def create_bifrost_bot():
    """
    Factory function to build the PTB Application.
    Used by both Webhooks (Production) and Polling (Local).
    """
    if not Config.BIFROST_BOT_TOKEN or not Config.MONGO_URI:
        logger.critical("Missing BIFROST_BOT_TOKEN or MONGO_URI in Config!")
        return None

    # 1. Setup Persistence (MongoDB)
    persistence = MongoPersistence(mongo_uri=Config.MONGO_URI)

    # 2. Build App
    app = Application.builder().token(Config.BIFROST_BOT_TOKEN).persistence(persistence).build()

    # 3. Register Handlers
    payment_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command), # Handles deep links
            CommandHandler("pay", start_command)    # Handles manual commands
        ],
        states={WAITING_PROOF: [MessageHandler(filters.PHOTO, receive_proof)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True,
        name="payment_flow",
        persistent=True
    )

    app.add_handler(payment_conv)
    app.add_handler(CallbackQueryHandler(admin_approve, pattern="^pay_approve_"))
    app.add_handler(CallbackQueryHandler(admin_reject_menu, pattern="^pay_reject_menu_"))
    app.add_handler(CallbackQueryHandler(admin_reject_confirm, pattern="^pay_reject_confirm_"))
    app.add_handler(CallbackQueryHandler(admin_restore_menu, pattern="^pay_restore_"))

    return app

async def process_webhook_update(update_json):
    """PRODUCTION ENTRY POINT (Flask)"""
    app = create_bifrost_bot()
    if not app:
        return

    await app.initialize()

    try:
        update = Update.de_json(update_json, app.bot)
        await app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}")
    finally:
        await app.shutdown()

def run_polling():
    """LOCAL DEV ENTRY POINT"""
    app = create_bifrost_bot()
    if not app:
        return

    logger.info("⚡ Starting Local Polling Mode... (Press Ctrl+C to stop)")
    app.run_polling(drop_pending_updates=True, close_loop=False)

if __name__ == "__main__":
    run_polling()