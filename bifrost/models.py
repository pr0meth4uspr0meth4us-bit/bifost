from pymongo import ASCENDING, DESCENDING
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from zoneinfo import ZoneInfo
from bson import ObjectId
import logging
import random
import secrets

log = logging.getLogger(__name__)
UTC = ZoneInfo("UTC")


class BifrostDB:
    """
    Central Database Manager for Bifrost.
    Handles Schema enforcement via Indexes and Data Access Objects (DAOs).
    """

    def __init__(self, mongo_client, db_name):
        self.db = mongo_client[db_name]
        self.init_indexes()

    def init_indexes(self):
        """
        Creates unique indexes to enforce data integrity at the DB level.
        Run this on app startup.
        """
        log.info("Ensuring Database Indexes...")

        # 1. Accounts Collection
        self.db.accounts.create_index([("email", ASCENDING)], unique=True, sparse=True)
        self.db.accounts.create_index([("telegram_id", ASCENDING)], unique=True, sparse=True)
        self.db.accounts.create_index([("google_id", ASCENDING)], unique=True, sparse=True)

        # 2. Applications Collection
        self.db.applications.create_index([("client_id", ASCENDING)], unique=True)

        # 3. App Links Collection
        self.db.app_links.create_index(
            [("account_id", ASCENDING), ("app_id", ASCENDING)],
            unique=True
        )

        # 4. Admins Collection
        self.db.admins.create_index([("email", ASCENDING)], unique=True)

        # 5. OTP Codes (Time To Live Index - auto delete after 10 mins)
        self.db.verification_codes.create_index("created_at", expireAfterSeconds=600)
        # We index 'verification_id' for fast lookups if provided
        self.db.verification_codes.create_index([("identifier", ASCENDING)])

        log.info("Indexes verified.")

    # --- OTP Management (Generic) ---

    def create_otp(self, identifier, channel="email"):
        """
        Generates a 6-digit code for a generic identifier (email or telegram_id).
        Returns the code and the internal verification_id (ObjectId).
        """
        code = str(random.randint(100000, 999999))

        result = self.db.verification_codes.insert_one({
            "code": code,
            "identifier": str(identifier), # email or telegram_id
            "channel": channel,
            "created_at": datetime.now(UTC)
        })

        return code, str(result.inserted_id)

    # Legacy wrapper for Telegram Bot compatibility
    def create_login_code(self, telegram_id):
        code, _ = self.create_otp(telegram_id, channel="telegram")
        return code

    def verify_otp(self, identifier=None, code=None, verification_id=None):
        """
        Checks if code exists.
        Can verify by (identifier + code) OR (verification_id + code).
        If valid, deletes the code and returns True.
        """
        query = {"code": code}

        if verification_id:
            try:
                query["_id"] = ObjectId(verification_id)
            except:
                return False
        elif identifier:
            query["identifier"] = str(identifier)
        else:
            return False

        record = self.db.verification_codes.find_one_and_delete(query)

        if record:
            return record['identifier'] if not identifier else True
        return False

    # Legacy wrapper for Telegram Bot compatibility
    def verify_and_consume_code(self, code):
        # We find purely by code for the legacy generic bot flow
        record = self.db.verification_codes.find_one_and_delete({"code": code, "channel": "telegram"})
        if record:
            return record['identifier']
        return None

    # --- User Account Management ---

    def create_account(self, data):
        """
        Creates a new user account.
        """
        account = {
            "email": data.get("email"),
            "password_hash": generate_password_hash(data["password"]) if data.get("password") else None,
            "telegram_id": data.get("telegram_id"),
            "google_id": data.get("google_id"),
            "display_name": data.get("display_name", "Unknown User"),
            "phone_number": data.get("phone_number"),
            "is_active": True,
            "created_at": datetime.now(UTC),
            "auth_providers": data.get("auth_providers", [])
        }
        return self.db.accounts.insert_one(account).inserted_id

    def update_password(self, email, new_password):
        """
        Updates the password for a user.
        """
        self.db.accounts.update_one(
            {"email": email},
            {"$set": {"password_hash": generate_password_hash(new_password)}}
        )

    def find_account_by_email(self, email):
        return self.db.accounts.find_one({"email": email})

    def find_account_by_telegram(self, telegram_id):
        return self.db.accounts.find_one({"telegram_id": str(telegram_id)})

    # --- Application (Client) Management ---

    def register_application(self, app_name, callback_url, allowed_methods=None):
        """
        Registers a new Client Application (like FinanceBot).
        """
        client_id = f"{app_name.lower().replace(' ', '_')}_{secrets.token_hex(4)}"
        client_secret = secrets.token_urlsafe(32)

        app_doc = {
            "app_name": app_name,
            "client_id": client_id,
            "client_secret_hash": generate_password_hash(client_secret),
            "app_logo_url": "/static/default_logo.png",
            "app_callback_url": callback_url,
            "allowed_auth_methods": allowed_methods or ["email"],
            "telegram_bot_token": None,
            "created_at": datetime.now(UTC)
        }

        self.db.applications.insert_one(app_doc)
        return client_id, client_secret

    def get_app_by_client_id(self, client_id):
        return self.db.applications.find_one({"client_id": client_id})

    def verify_client_secret(self, client_id, provided_secret):
        app = self.get_app_by_client_id(client_id)
        if not app:
            return False
        return check_password_hash(app["client_secret_hash"], provided_secret)

    # --- App Linking (Authorization) ---

    def link_user_to_app(self, account_id, app_id, role="user"):
        """
        Links a user to an application. Safe to call multiple times (upsert).
        """
        self.db.app_links.update_one(
            {"account_id": ObjectId(account_id), "app_id": ObjectId(app_id)},
            {
                "$set": {
                    "role": role,
                    "last_login": datetime.now(UTC)
                },
                "$setOnInsert": {
                    "linked_at": datetime.now(UTC)
                }
            },
            upsert=True
        )

    def get_user_role_for_app(self, account_id, app_id):
        link = self.db.app_links.find_one(
            {"account_id": ObjectId(account_id), "app_id": ObjectId(app_id)}
        )
        return link['role'] if link else None

    # --- Admin Management ---

    def create_super_admin(self, email, password):
        admin = {
            "email": email,
            "password_hash": generate_password_hash(password),
            "role": "super_admin",
            "created_at": datetime.now(UTC)
        }
        try:
            self.db.admins.insert_one(admin)
            return True
        except Exception as e:
            log.error(f"Could not create admin: {e}")
            return False