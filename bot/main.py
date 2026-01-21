import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ConversationHandler
from dotenv import load_dotenv

# Absolute import
from bot.handlers import (
    start_command, receive_proof, cancel,
    admin_approve, admin_reject_menu, admin_reject_confirm, admin_restore_menu,
    WAITING_PROOF
)
# Import the new persistence class
from bot.persistence import MongoPersistence

load_dotenv()

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("bifrost-bot")

async def process_webhook_update(update_json):
    """
    Process a single update from Flask.
    Uses MongoPersistence for scalable, concurrent state management.
    """
    token = os.getenv("BIFROST_BOT_TOKEN")
    mongo_uri = os.getenv("MONGO_URI")

    if not token or not mongo_uri:
        logger.critical("Missing BIFROST_BOT_TOKEN or MONGO_URI!")
        return

    # 1. Setup Persistence (MongoDB)
    # This connects to your existing DB and stores states in 'bifrost_bot.conversations'
    persistence = MongoPersistence(mongo_uri=mongo_uri)

    # 2. Build App (Ephemeral)
    app = Application.builder().token(token).persistence(persistence).build()

    # 3. Register Handlers
    payment_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={WAITING_PROOF: [MessageHandler(filters.PHOTO, receive_proof)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        allow_reentry=True,
        name="payment_flow",  # This ID is used as the Mongo Document ID
        persistent=True
    )

    app.add_handler(payment_conv)
    app.add_handler(CallbackQueryHandler(admin_approve, pattern="^pay_approve_"))
    app.add_handler(CallbackQueryHandler(admin_reject_menu, pattern="^pay_reject_menu_"))
    app.add_handler(CallbackQueryHandler(admin_reject_confirm, pattern="^pay_reject_confirm_"))
    app.add_handler(CallbackQueryHandler(admin_restore_menu, pattern="^pay_restore_"))

    # 4. Lifecycle
    await app.initialize()

    try:
        update = Update.de_json(update_json, app.bot)
        await app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing update: {e}")
    finally:
        await app.shutdown()