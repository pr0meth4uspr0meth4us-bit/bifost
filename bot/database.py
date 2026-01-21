from pymongo import MongoClient
from .config import Config

def get_db():
    """Returns a MongoDB Database instance."""
    client = MongoClient(Config.MONGO_URI)
    return client[Config.DB_NAME]