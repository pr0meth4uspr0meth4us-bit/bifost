import logging
import requests
from requests.auth import HTTPBasicAuth
from .config import Config
from .database import get_db

log = logging.getLogger(__name__)

def call_grant_premium(user_telegram_id, target_client_id):
    """Calls Bifrost Internal API to upgrade user role."""
    url = f"{Config.BIFROST_API_URL}/internal/grant-premium"
    payload = {
        "telegram_id": str(user_telegram_id),
        "target_client_id": target_client_id
    }

    # Authenticate as the Bifrost Service itself
    auth = HTTPBasicAuth(Config.BIFROST_ROOT_CLIENT_ID, Config.BIFROST_ROOT_CLIENT_SECRET)

    try:
        res = requests.post(url, json=payload, auth=auth, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Failed to call Bifrost API: {e}")
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
    """Fetches App by ObjectId."""
    db = get_db()
    return db.applications.find_one({"_id": app_id})