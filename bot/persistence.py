import os
import logging
from pymongo import MongoClient
from telegram.ext import BasePersistence, PersistenceInput
from telegram.ext._utils.types import UD, CD, BD, CDC

logger = logging.getLogger(__name__)

class MongoPersistence(BasePersistence):
    """
    Custom Persistence class to store Telegram Bot state in MongoDB.
    Atomic operations ensure User A and User B don't overwrite each other.
    """
    def __init__(self, mongo_uri, db_name="bifrost_bot"):
        # We only persist conversations (flow states) for now to keep it efficient
        super().__init__(store_data=PersistenceInput(
            user_data=False,
            chat_data=False,
            bot_data=False,
            callback_data=False,
            conversation_data=True
        ))

        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.conversations = self.db["conversations"]

    async def get_conversations(self, name: str) -> dict:
        """Load all conversations from Mongo for a specific handler (e.g., 'payment_flow')"""
        doc = self.conversations.find_one({"_id": name})
        if not doc:
            return {}

        # Convert stringified keys "chat_id|user_id" back to tuples (chat_id, user_id)
        data = {}
        for key_str, state in doc.get("data", {}).items():
            try:
                # Assuming key is "chat_id|user_id"
                key_parts = key_str.split("|")
                if len(key_parts) == 2:
                    key = (int(key_parts[0]), int(key_parts[1]))
                    data[key] = state
            except Exception as e:
                logger.error(f"Failed to deserialize key {key_str}: {e}")
        return data

    async def update_conversation(self, name: str, key: tuple, new_state: object) -> None:
        """
        Atomic update of a SINGLE user's state.
        Safe for concurrent User A and User B.
        """
        if isinstance(key, tuple):
            # Serialize (chat_id, user_id) tuple to string "chat_id|user_id"
            key_str = f"{key[0]}|{key[1]}"

            # Atomic update using $set
            self.conversations.update_one(
                {"_id": name},
                {"$set": {f"data.{key_str}": new_state}},
                upsert=True
            )

    async def flush(self) -> None:
        """Required by abstract class, but we save instantly in update_conversation"""
        pass

    # --- Stubs for unused features (required by abstract class) ---
    async def get_user_data(self) -> dict: return {}
    async def update_user_data(self, user_id, data) -> None: pass
    async def drop_user_data(self, user_id) -> None: pass
    async def get_chat_data(self) -> dict: return {}
    async def update_chat_data(self, chat_id, data) -> None: pass
    async def drop_chat_data(self, chat_id) -> None: pass
    async def get_bot_data(self) -> dict: return {}
    async def update_bot_data(self, data) -> None: pass
    async def drop_bot_data(self) -> None: pass
    async def get_callback_data(self) -> dict: return {}
    async def update_callback_data(self, data) -> None: pass
    async def drop_callback_data(self) -> None: pass