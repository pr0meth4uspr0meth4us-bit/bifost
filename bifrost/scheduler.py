import time
import schedule
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from bson import ObjectId
from .models import BifrostDB
from . import mongo # Assuming you can import the mongo instance or pass it in

log = logging.getLogger("bifrost_reaper")
UTC = ZoneInfo("UTC")

def run_expiration_check(app):
    """
    Checks for expired subscriptions and downgrades them.
    Triggers webhooks so client apps know immediately.
    """
    with app.app_context():
        db = BifrostDB(mongo.cx, app.config['DB_NAME'])
        now = datetime.now(UTC)

        # Find all links that are NOT 'user' (premium/admin) AND have expired
        query = {
            "role": {"$ne": "user"},
            "expires_at": {"$lt": now}
        }

        expired_links = list(db.db.app_links.find(query))

        if not expired_links:
            log.info("🌾 Reaper: No expired subscriptions found.")
            return

        log.info(f"🌾 Reaper: Found {len(expired_links)} expired subscriptions. Processing...")

        for link in expired_links:
            user_id = link['account_id']
            app_id = link['app_id']

            # 1. Downgrade in DB
            db.db.app_links.update_one(
                {"_id": link['_id']},
                {
                    "$set": {"role": "user"},
                    "$unset": {"expires_at": ""} # Clear expiration since they are now free
                }
            )

            # 2. Trigger Webhook (Crucial!)
            # This tells Finance Bot to clear its cache immediately
            log.info(f"⬇️ Downgrading User {user_id} for App {app_id}")
            db._trigger_event_for_user(user_id, "account_role_change", specific_app_id=app_id)

def start_scheduler(app):
    """Starts the scheduler in a background thread."""
    import threading

    def job():
        while True:
            schedule.run_pending()
            time.sleep(60)

    # Run every 60 minutes
    schedule.every(60).minutes.do(run_expiration_check, app)

    # Also run immediately on startup
    run_expiration_check(app)

    t = threading.Thread(target=job, daemon=True)
    t.start()