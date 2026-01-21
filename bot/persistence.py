import logging
from pymongo import MongoClient
from telegram.ext import BasePersistence, PersistenceInput

logger = logging.getLogger(__name__)


class MongoPersistence(BasePersistence):
    """
    Custom Persistence class to store Telegram Bot state AND User Data in MongoDB.
    """

    def __init__(self, mongo_uri, db_name="bifrost_bot"):
        super().__init__(store_data=PersistenceInput(
            user_data=True,  # <--- CHANGED: Enable User Data
            chat_data=False,
            bot_data=False,
            callback_data=False
        ))

        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.conversations = self.db["conversations"]
        self.user_data_col = self.db["user_data"]  # <--- NEW: Collection for User Data

    # --- CONVERSATION STATE ---
    async def get_conversations(self, name: str) -> dict:
        doc = self.conversations.find_one({"_id": name})
        if not doc:
            return {}
        data = {}
        for key_str, state in doc.get("data", {}).items():
            try:
                key_parts = key_str.split("|")
                if len(key_parts) == 2:
                    key = (int(key_parts[0]), int(key_parts[1]))
                    data[key] = state
            except Exception as e:
                logger.error(f"Failed to deserialize key {key_str}: {e}")
        return data

    async def update_conversation(self, name: str, key: tuple, new_state: object) -> None:
        if isinstance(key, tuple):
            key_str = f"{key[0]}|{key[1]}"
            self.conversations.update_one(
                {"_id": name},
                {"$set": {f"data.{key_str}": new_state}},
                upsert=True
            )

    # --- USER DATA (THE FIX) ---
    async def get_user_data(self) -> dict:
        """Loads ALL user_data from MongoDB on startup."""
        data = {}
        # Caution: For massive bots (100k+ users), this needs a lazy-load approach.
        # For this scale, loading into memory is fine and standard for PTB.
        cursor = self.user_data_col.find({})
        for doc in cursor:
            user_id = int(doc["_id"])
            data[user_id] = doc["data"]
        return data

    async def update_user_data(self, user_id: int, data: dict) -> None:
        """Save a single user's data to MongoDB."""
        if data:
            self.user_data_col.update_one(
                {"_id": user_id},
                {"$set": {"data": data}},
                upsert=True
            )
        else:
            self.user_data_col.delete_one({"_id": user_id})

    async def refresh_user_data(self, user_id: int, user_data: dict) -> None:
        """Reload user_data from DB (rarely used by default but good practice)."""
        doc = self.user_data_col.find_one({"_id": user_id})
        if doc:
            user_data.update(doc["data"])

    # --- REQUIRED STUBS ---
    async def flush(self) -> None:
        pass

    async def refresh_bot_data(self, bot_data) -> None:
        pass

    async def refresh_chat_data(self, chat_id, chat_data) -> None:
        pass

    async def get_chat_data(self) -> dict:
        return {}

    async def update_chat_data(self, chat_id, data) -> None:
        pass

    async def drop_chat_data(self, chat_id) -> None:
        pass

    async def get_bot_data(self) -> dict:
        return {}

    async def update_bot_data(self, data) -> None:
        pass

    async def drop_bot_data(self) -> None:
        pass

    async def get_callback_data(self) -> dict:
        return {}

    async def update_callback_data(self, data) -> None:
        pass

    async def drop_callback_data(self) -> None:
        pass

    async def drop_user_data(self, user_id: int) -> None:
        self.user_data_col.delete_one({"_id": user_id})