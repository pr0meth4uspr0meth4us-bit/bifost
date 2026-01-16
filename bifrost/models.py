from pymongo import ASCENDING, DESCENDING
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from zoneinfo import ZoneInfo
from bson import ObjectId
import logging
import random
import secrets

# Configure logging to print to stdout
logging.basicConfig(level=logging.INFO)
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

        # 6. Transactions (Payments)
        self.db.transactions.create_index([("transaction_id", ASCENDING)], unique=True)
        self.db.transactions.create_index([("account_id", ASCENDING)])
        self.db.transactions.create_index([("app_id", ASCENDING)])

    # --- OTP Management (Generic) ---

    def create_otp(self, identifier, channel="email", account_id=None):
        """
        Generates a 6-digit code for a generic identifier (email or telegram_id).
        Returns the code and the internal verification_id (ObjectId).
        """
        code = str(random.randint(100000, 999999))

        doc = {
            "code": code,
            "identifier": str(identifier),  # email or telegram_id
            "channel": channel,
            "created_at": datetime.now(UTC)
        }

        # Context preservation for Account Linking
        if account_id:
            doc["account_id"] = str(account_id)

        result = self.db.verification_codes.insert_one(doc)

        log.info(f"✅ OTP Created: Code={code}, Channel={channel}, ID={identifier}")
        return code, str(result.inserted_id)

    # Legacy wrapper for Telegram Bot compatibility
    def create_login_code(self, telegram_id):
        # Force channel='telegram'
        code, _ = self.create_otp(telegram_id, channel="telegram")
        return code

    def verify_otp(self, identifier=None, code=None, verification_id=None):
        """
        Checks if code exists.
        Can verify by (identifier + code) OR (verification_id + code).
        If valid, deletes the code and returns the OTP record (dict) or False.
        """
        # Ensure code is string and remove ALL spaces (internal & external)
        safe_code = str(code).replace(" ", "").strip() if code else None
        query = {"code": safe_code}

        if verification_id:
            try:
                query["_id"] = ObjectId(verification_id)
            except:
                return False
        elif identifier:
            query["identifier"] = str(identifier)
        else:
            return False

        # Return the whole record so the API can check for 'account_id' context
        record = self.db.verification_codes.find_one_and_delete(query)

        if record:
            return record
        return False

    # Legacy wrapper for Telegram Bot compatibility
    def verify_and_consume_code(self, code):
        # Ensure code is string and remove ALL spaces (internal & external)
        safe_code = str(code).replace(" ", "").strip() if code else None

        log.info(f"🔍 Attempting to verify Telegram code: '{safe_code}'")

        # 1. Try to find strict match
        query = {"code": safe_code, "channel": "telegram"}
        record = self.db.verification_codes.find_one_and_delete(query)

        if record:
            log.info(f"✅ Code verified for Telegram ID: {record.get('identifier')}")
            return record['identifier']

        # 2. Debugging: If not found, check if it exists but matches incorrectly
        check = self.db.verification_codes.find_one({"code": safe_code})
        if check:
            log.warning(
                f"⚠️ Code '{safe_code}' FOUND but failed verification. Expected channel='telegram', Got='{check.get('channel')}'")
        else:
            log.warning(f"❌ Code '{safe_code}' NOT FOUND in DB.")

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

    def link_email_credentials(self, account_id, email, password):
        """
        Links an email and password to an EXISTING account (e.g., Telegram user).
        Fails if the email is already used by a DIFFERENT account.
        """
        # 1. Security Check: Is this email already taken by someone else?
        existing = self.db.accounts.find_one({"email": email, "_id": {"$ne": ObjectId(account_id)}})
        if existing:
            return False, "Email is already associated with another account."

        # 2. Update the specific account
        result = self.db.accounts.update_one(
            {"_id": ObjectId(account_id)},
            {
                "$set": {
                    "email": email,
                    "password_hash": generate_password_hash(password)
                },
                "$addToSet": {
                    "auth_providers": "email"
                }
            }
        )

        if result.modified_count > 0:
            return True, "Account linked successfully."
        return False, "Account not found."

    def update_account_profile(self, account_id, updates):
        """
        Updates profile fields (display_name, email).
        Handles email uniqueness check.
        """
        # If email is being updated, check for uniqueness
        if 'email' in updates:
            new_email = updates['email']
            existing = self.db.accounts.find_one({"email": new_email, "_id": {"$ne": ObjectId(account_id)}})
            if existing:
                return False, "Email is already in use by another account."

        # Perform update
        result = self.db.accounts.update_one(
            {"_id": ObjectId(account_id)},
            {"$set": updates}
        )

        if result.matched_count > 0:
            return True, "Profile updated."
        return False, "Account not found."

    def find_account_by_email(self, email):
        return self.db.accounts.find_one({"email": email})

    def find_account_by_id(self, account_id):
        try:
            return self.db.accounts.find_one({"_id": ObjectId(account_id)})
        except:
            return None

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
        Links a user to an application.
        Logic updated to PREVENT overwriting existing roles.
        """
        self.db.app_links.update_one(
            {"account_id": ObjectId(account_id), "app_id": ObjectId(app_id)},
            {
                # Update last_login every time
                "$set": {
                    "last_login": datetime.now(UTC)
                },
                # Only set role and linked_at if this is a NEW insertion
                "$setOnInsert": {
                    "role": role,
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

    # --- Payment / Transaction Management ---

    def create_transaction(self, account_id, app_id, amount, currency, description, target_role=None):
        """
        Creates a 'pending' transaction record.
        IMPORTANT: ABA PayWay requires transaction IDs to only contain:
        - Letters (a-z, A-Z)
        - Numbers (0-9)
        - Hyphens (-)
        MUST BE MAX 20 CHARACTERS
        """
        # "tx-" (3) + 16 hex chars = 19 chars total.
        transaction_id = f"tx-{secrets.token_hex(8)}"

        doc = {
            "transaction_id": transaction_id,
            "account_id": ObjectId(account_id),
            "app_id": ObjectId(app_id),
            "amount": amount,
            "currency": currency,
            "description": description,
            "status": "pending",
            "target_role": target_role,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "provider_ref": None
        }

        self.db.transactions.insert_one(doc)
        return transaction_id

    def complete_transaction(self, transaction_id, provider_ref=None):
        """
        Marks a transaction as successful and EXECUTES the role upgrade.
        Returns: (success, message)
        """
        tx = self.db.transactions.find_one({"transaction_id": transaction_id})
        if not tx:
            return False, "Transaction not found"

        if tx['status'] == 'completed':
            return True, "Already completed"

        # 1. Update Transaction Status
        self.db.transactions.update_one(
            {"_id": tx['_id']},
            {
                "$set": {
                    "status": "completed",
                    "provider_ref": provider_ref,
                    "updated_at": datetime.now(UTC)
                }
            }
        )

        # 2. Upgrade User Role (if applicable)
        if tx.get('target_role'):
            self.db.app_links.update_one(
                {"account_id": tx['account_id'], "app_id": tx['app_id']},
                {
                    "$set": {
                        "role": tx['target_role'],
                        "updated_at": datetime.now(UTC)
                    }
                },
                upsert=True
            )
            log.info(f"💰 Transaction {transaction_id} successful. Role upgraded to {tx['target_role']}")

        return True, "Transaction completed and role updated"

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