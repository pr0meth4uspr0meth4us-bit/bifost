# bifrost/models/apps.py
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
import logging

log = logging.getLogger(__name__)
UTC = ZoneInfo("UTC")


class AppMixin:
    # ---------------------------------------------------------
    # CLIENT APP MANAGEMENT
    # ---------------------------------------------------------
    def register_application(self, app_name, callback_url, web_url=None, logo_url=None, allowed_methods=None,
                             api_url=None):
        """Creates a new application document."""
        safe_name = app_name.lower().replace(' ', '_')
        client_id = f"{safe_name}_{secrets.token_hex(4)}"
        client_secret = secrets.token_urlsafe(32)
        webhook_secret = secrets.token_hex(24)

        app_doc = {
            "app_name": app_name,
            "client_id": client_id,
            "client_secret_hash": generate_password_hash(client_secret),
            "webhook_secret": webhook_secret,
            "app_logo_url": logo_url or "",
            "app_qr_url": "",
            "app_web_url": web_url,
            "app_callback_url": callback_url,
            "app_api_url": api_url,
            "allowed_auth_methods": allowed_methods or ["email"],
            "telegram_bot_token": None,
            "created_at": datetime.now(UTC)
        }
        self.db.applications.insert_one(app_doc)

        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "webhook_secret": webhook_secret
        }

    def update_app_details(self, app_id, data):
        """Updates non-sensitive app details."""
        allowed_fields = ['app_name', 'app_callback_url', 'app_web_url', 'app_api_url', 'app_logo_url', 'app_qr_url', 'telegram_bot_token']
        updates = {k: v for k, v in data.items() if k in allowed_fields}

        if updates:
            self.db.applications.update_one(
                {"_id": ObjectId(app_id)},
                {"$set": updates}
            )
            return True
        return False

    def rotate_app_secret(self, app_id):
        """Regenerates the Client Secret for an App."""
        new_secret = secrets.token_urlsafe(32)
        self.db.applications.update_one(
            {"_id": ObjectId(app_id)},
            {"$set": {"client_secret_hash": generate_password_hash(new_secret)}}
        )
        return new_secret

    def get_app_by_client_id(self, client_id):
        return self.db.applications.find_one({"client_id": client_id})

    def verify_client_secret(self, client_id, provided_secret):
        app = self.get_app_by_client_id(client_id)
        if not app:
            return False
        return check_password_hash(app["client_secret_hash"], provided_secret)

    def link_user_to_app(self, account_id, app_id, role="user", duration_str=None, suppress_webhook=False):
        """
        Links a user to an app.
        Enforces 'One Owner per App' rule if role is 'owner'.
        """
        # --- OWNER LOGIC: Enforce Single Owner ---
        if role == 'owner':
            existing_owners = self.db.app_links.find({
                "app_id": ObjectId(app_id),
                "role": "owner",
                "account_id": {"$ne": ObjectId(account_id)}
            })

            for owner_link in existing_owners:
                log.info(f"👑 Ownership Transfer: Demoting {owner_link['account_id']} to Admin.")
                self.link_user_to_app(
                    account_id=owner_link['account_id'],
                    app_id=app_id,
                    role="admin",
                    duration_str="lifetime",
                    suppress_webhook=False
                )
        # ------------------------------------------

        current_link = self.db.app_links.find_one({"account_id": ObjectId(account_id), "app_id": ObjectId(app_id)})
        old_role = current_link.get('role') if current_link else None

        update_doc = {
            "last_login": datetime.now(UTC),
            "role": role
        }

        if duration_str and duration_str != 'lifetime':
            now = datetime.now(UTC)
            expires_at = None
            if duration_str == '1m':
                expires_at = now + timedelta(days=30)
            elif duration_str == '3m':
                expires_at = now + timedelta(days=90)
            elif duration_str == '6m':
                expires_at = now + timedelta(days=180)
            elif duration_str == '1y':
                expires_at = now + timedelta(days=365)

            if expires_at:
                update_doc["expires_at"] = expires_at

        if duration_str == 'lifetime':
            update_doc["expires_at"] = None

        self.db.app_links.update_one(
            {"account_id": ObjectId(account_id), "app_id": ObjectId(app_id)},
            {
                "$set": update_doc,
                "$setOnInsert": {"linked_at": datetime.now(UTC)}
            },
            upsert=True
        )

        if old_role != role and not suppress_webhook:
            self._trigger_event_for_user(account_id, "account_role_change", specific_app_id=app_id)

    def remove_user_from_app(self, account_id, app_id, is_self_action=False):
        """
        Completely unlinks a user from an application.
        Verified users (user, premium_user, admin) cannot be removed by anyone except themselves.
        """
        query = {
            "account_id": ObjectId(account_id),
            "app_id": ObjectId(app_id)
        }

        link = self.db.app_links.find_one(query)
        if not link:
            return False, "Link not found."

        if not is_self_action:
            if link.get('role') not in ['guest', 'banned']:
                return False, "COMPLIANCE ERROR: Verified users cannot be removed by Admins. They must delete their own account."

        result = self.db.app_links.delete_one(query)

        if result.deleted_count > 0:
            self._trigger_event_for_user(
                account_id=account_id,
                event_type="account_role_change",
                specific_app_id=app_id,
                extra_data={"new_role": "removed", "reason": "admin_removed" if not is_self_action else "self_deleted"}
            )
            return True, "User removed successfully."

        return False, "Database error during removal."

    def get_user_role_for_app(self, account_id, app_id):
        link = self.db.app_links.find_one({"account_id": ObjectId(account_id), "app_id": ObjectId(app_id)})
        if not link:
            return None
        if link.get('expires_at') and link['expires_at'].replace(tzinfo=UTC) < datetime.now(UTC):
            return "expired"
        return link.get('role', 'user')

    # ---------------------------------------------------------
    # BACKOFFICE & HEIMDALL HELPERS
    # ---------------------------------------------------------
    def is_heimdall(self, email):
        """Checks if the email belongs to a Heimdall (God Admin)."""
        if not email: return False
        admin = self.db.admins.find_one({"email": email.lower()})
        return admin and admin.get('role') == 'heimdall'

    def get_managed_apps(self, account_id):
        """Returns a list of apps where the user is an 'admin' or 'owner'."""
        links = self.db.app_links.find({
            "account_id": ObjectId(account_id),
            "role": {"$in": ["admin", "owner", "heimdall"]}
        })
        app_ids = [link['app_id'] for link in links]
        return list(self.db.applications.find({"_id": {"$in": app_ids}}))

    def get_all_apps(self):
        """For Heimdall Dashboard."""
        return list(self.db.applications.find({}))

    def get_app_users(self, app_id):
        """Returns all users linked to a specific app."""
        links = list(self.db.app_links.find({"app_id": ObjectId(app_id)}))
        if not links:
            return []

        user_ids = [link['account_id'] for link in links]
        users_cursor = self.db.accounts.find({"_id": {"$in": user_ids}})
        users_map = {u['_id']: u for u in users_cursor}

        results = []
        for link in links:
            user = users_map.get(link['account_id'])
            if user:
                results.append({
                    "account_id": str(user['_id']),
                    "display_name": user.get('display_name'),
                    "email": user.get('email'),
                    "username": user.get('username'),
                    "telegram_id": user.get('telegram_id'),
                    "role": link.get('role'),
                    "expires_at": link.get('expires_at'),
                    "linked_at": link.get('linked_at')
                })
        return results

    def get_app_owner(self, app_id):
        """Returns the user object of the current app owner."""
        link = self.db.app_links.find_one({
            "app_id": ObjectId(app_id),
            "role": "owner"
        })
        if link:
            return self.db.accounts.find_one({"_id": link['account_id']})
        return None