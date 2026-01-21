import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from dotenv import load_dotenv

# Load env
load_dotenv()

# Import your existing handlers
from handlers import (
    start_command, receive_proof, cancel,
    admin_approve, admin_reject_menu, admin_reject_confirm, admin_restore_menu,
    WAITING_PROOF
)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("bifrost-bot")

# Global app instance
ptb_application = None

async def init_bot():
    """Initializes the PTB Application (Async)"""
    global ptb_application
    token = os.getenv("BIFROST_BOT_TOKEN")
    if not token:
        logger.critical("BIFROST_BOT_TOKEN missing!")
        return None

    # Build App
    app = Application.builder().token(token).build()

    # --- REGISTER HANDLERS ---
    payment_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={WAITING_PROOF: [MessageHandler(filters.PHOTO, receive_proof)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True
    )
    app.add_handler(payment_conv)
    app.add_handler(CallbackQueryHandler(admin_approve, pattern="^pay_approve_"))
    app.add_handler(CallbackQueryHandler(admin_reject_menu, pattern="^pay_reject_menu_"))
    app.add_handler(CallbackQueryHandler(admin_reject_confirm, pattern="^pay_reject_confirm_"))
    app.add_handler(CallbackQueryHandler(admin_restore_menu, pattern="^pay_restore_"))

    # Initialize bot logic
    await app.initialize()
    await app.start()

    logger.info("🤖 Bot initialized in Webhook Mode.")
    return app

async def process_webhook_update(update_json):
    """Process a single update from Flask"""
    global ptb_application
    if not ptb_application:
        await init_bot()

    # Decode update and feed to bot
    update = Update.de_json(update_json, ptb_application.bot)
    await ptb_application.process_update(update)