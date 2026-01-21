import logging
import requests
from requests.auth import HTTPBasicAuth
from bson import ObjectId
from .config import Config
from .database import get_db

# Import the logic directly from the Backend
# We use a try/except import to allow this file to run in standalone contexts if needed
try:
    from bifrost.models import BifrostDB
except ImportError:
    BifrostDB = None

log = logging.getLogger(__name__)

def call_grant_premium(user_telegram_id, target_client_id):
    """
    Directly accesses the database to grant premium.
    Replaces the HTTP call to avoid Gunicorn Deadlocks.
    """
    try:
        if BifrostDB is None:
            log.error("CRITICAL: BifrostDB model not found. Cannot grant premium.")
            return False

        # 1. Get a DB connection
        db_instance = get_db()
        # Create the logic handler (passing the client and db_name)
        logic = BifrostDB(db_instance.client, Config.DB_NAME)

        # 2. Find User
        user = logic.find_account_by_telegram(user_telegram_id)
        if not user:
            log.error(f"User {user_telegram_id} not found.")
            return False

        # 3. Find App
        app_doc = logic.get_app_by_client_id(target_client_id)
        if not app_doc:
            log.error(f"App {target_client_id} not found.")
            return False

        # 4. Perform the Link (Grant Role)
        logic.link_user_to_app(user['_id'], app_doc['_id'], role="premium_user")
        log.info(f"✅ Directly granted premium to {user_telegram_id} for {target_client_id}")
        return True

    except Exception as e:
        log.error(f"Direct DB Grant failed: {e}")
        return False

def get_app_details(client_id):
    """Fetches App Name to display nicely in the Bot."""
    try:
        db = get_db()
        app = db.applications.find_one({"client_id": client_id})
        return app
    except Exception as e:
        log.error(f"DB Error fetching app details: {e}")
        return None

def get_transaction(transaction_id):
    """Fetches a transaction by ID."""
    db = get_db()
    return db.transactions.find_one({"transaction_id": transaction_id})

def get_app_by_id(app_id):
    """Fetches App by ObjectId, safely handling strings."""
    db = get_db()
    try:
        oid = ObjectId(app_id) if isinstance(app_id, str) else app_id
        return db.applications.find_one({"_id": oid})
    except Exception as e:
        log.error(f"Invalid App ID format: {e}")
        return None