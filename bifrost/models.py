from pymongo import ASCENDING
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bson import ObjectId
import logging
import random
import secrets
import re
from .services.webhook_service import WebhookService

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
        """Creates unique indexes to enforce data integrity."""

        # Helper to ensure unique sparse index
        def ensure_unique_sparse(collection, field):
            idx_name = f"{field}_1"
            try:
                collection.create_index([(field, ASCENDING)], unique=True, sparse=True)
            except Exception:
                try:
                    log.info(f"Recreating index for {field} to ensure sparse constraint...")
                    collection.drop_index(idx_name)
                    collection.create_index([(field, ASCENDING)], unique=True, sparse=True)
                except Exception as e:
                    log.warning(f"Could not recreate sparse index for {field}: {e}")

        # Ensure sparse indexes for optional fields
        ensure_unique_sparse(self.db.accounts, "email")
        ensure_unique_sparse(self.db.accounts, "username")
        ensure_unique_sparse(self.db.accounts, "telegram_id")
        ensure_unique_sparse(self.db.accounts, "google_id")
        ensure_unique_sparse(self.db.accounts, "phone_number")

        # Standard non-sparse indexes
        self.db.applications.create_index([("client_id", ASCENDING)], unique=True)
        self.db.app_links.create_index([("account_id", ASCENDING), ("app_id", ASCENDING)], unique=True)
        self.db.admins.create_index([("email", ASCENDING)], unique=True)
        self.db.verification_codes.create_index("created_at", expireAfterSeconds=600)
        self.db.verification_codes.create_index([("identifier", ASCENDING)])

        # Transactions
        self.db.transactions.create_index([("transaction_id", ASCENDING)], unique=True)
        self.db.transactions.create_index([("account_id", ASCENDING)])
        self.db.transactions.create_index([("app_id", ASCENDING)])

        # Payment Logs
        self.db.payment_logs.create_index([("trx_id", ASCENDING)], unique=True)
        self.db.payment_logs.create_index([("status", ASCENDING)])

    # ---------------------------------------------------------
    # AUTH & OTP UTILITIES
    # ---------------------------------------------------------

    def create_otp(self, identifier, channel="email", account_id=None):
        code = str(random.randint(100000, 999999))
        doc = {
            "code": code,
            "identifier": str(identifier).lower(),
            "channel": channel,
            "created_at": datetime.now(UTC)
        }
        if account_id:
            doc["account_id"] = str(account_id)
        result = self.db.verification_codes.insert_one(doc)
        log.info(f"✅ OTP Created: Code={code}, Channel={channel}, ID={identifier}")
        return code, str(result.inserted_id)

    def create_login_code(self, telegram_id):
        code, _ = self.create_otp(telegram_id, channel="telegram")
        return code

    def create_deep_link_token(self, account_id):
        """Generates a secure, long-string token for Deep Linking."""
        token = secrets.token_urlsafe(16)
        doc = {
            "code": token,
            "identifier": "deep_link",
            "account_id": str(account_id),
            "channel": "deep_link",
            "created_at": datetime.now(UTC)
        }
        self.db.verification_codes.insert_one(doc)
        log.info(f"🔗 Deep Link Token Created for Account {account_id}")
        return token

    def verify_otp(self, identifier=None, code=None, verification_id=None):
        safe_code = str(code).replace(" ", "").strip() if code else None
        query = {"code": safe_code}

        if verification_id:
            try:
                query["_id"] = ObjectId(verification_id)
            except:
                return False
        elif identifier:
            query["identifier"] = str(identifier).lower()

        if not identifier and not verification_id and not safe_code:
            return False

        record = self.db.verification_codes.find_one_and_delete(query)
        return record if record else False

    def verify_and_consume_code(self, code):
        safe_code = str(code).replace(" ", "").strip() if code else None
        log.info(f"🔍 Attempting to verify Telegram code: '{safe_code}'")
        query = {"code": safe_code, "channel": "telegram"}
        record = self.db.verification_codes.find_one_and_delete(query)
        if record:
            return record['identifier']
        return None

    # ---------------------------------------------------------
    # HELPER: WEBHOOK TRIGGERS
    # ---------------------------------------------------------

    def _trigger_event_for_user(self, account_id, event_type, specific_app_id=None, token=None):
        """
        Finds linked apps for a user and triggers the webhook.
        """
        try:
            query = {"account_id": ObjectId(account_id)}
            if specific_app_id:
                query["app_id"] = ObjectId(specific_app_id)

            links = list(self.db.app_links.find(query))
            if not links:
                return

            app_ids = list(set([link['app_id'] for link in links]))
            apps = self.db.applications.find({"_id": {"$in": app_ids}})

            for app_doc in apps:
                # Trigger the webhook (WebhookService handles the signing)
                WebhookService.send_event(
                    app_doc=app_doc,
                    event_type=event_type,
                    account_id=account_id,
                    token=token
                )
        except Exception as e:
            log.error(f"Failed to trigger events for user {account_id}: {e}")

    # ---------------------------------------------------------
    # ACCOUNT MANAGEMENT
    # ---------------------------------------------------------

    def create_account(self, data):
        account = {
            "display_name": data.get("display_name", "Unknown User"),
            "is_active": True,
            "created_at": datetime.now(UTC),
            "auth_providers": data.get("auth_providers", [])
        }

        if data.get("email"):
            account["email"] = data.get("email").lower()
        if data.get("username"):
            account["username"] = data.get("username").lower()
        if data.get("password"):
            account["password_hash"] = generate_password_hash(data["password"])
        if data.get("telegram_id"):
            account["telegram_id"] = str(data.get("telegram_id"))
        if data.get("google_id"):
            account["google_id"] = data.get("google_id")
        if data.get("phone_number"):
            account["phone_number"] = data.get("phone_number")

        return self.db.accounts.insert_one(account).inserted_id

    def find_account_by_email(self, email):
        if not email: return None
        return self.db.accounts.find_one({"email": email.lower()})

    def find_account_by_username(self, username):
        if not username: return None
        return self.db.accounts.find_one({"username": username.lower()})

    def find_account_by_id(self, account_id):
        try:
            return self.db.accounts.find_one({"_id": ObjectId(account_id)})
        except:
            return None

    def find_account_by_telegram(self, telegram_id):
        return self.db.accounts.find_one({"telegram_id": str(telegram_id)})

    def update_password(self, email, new_password):
        user = self.find_account_by_email(email)
        if not user:
            return

        self.db.accounts.update_one(
            {"_id": user['_id']},
            {"$set": {"password_hash": generate_password_hash(new_password)}}
        )
        self._trigger_event_for_user(user['_id'], "security_password_change")

    def link_email_credentials(self, account_id, email, password):
        email = email.lower()
        existing = self.db.accounts.find_one({"email": email, "_id": {"$ne": ObjectId(account_id)}})
        if existing:
            return False, "Email is already associated with another account."

        result = self.db.accounts.update_one(
            {"_id": ObjectId(account_id)},
            {
                "$set": {"email": email, "password_hash": generate_password_hash(password)},
                "$addToSet": {"auth_providers": "email"}
            }
        )

        if result.modified_count > 0:
            self._trigger_event_for_user(account_id, "account_update")
            return True, "Account linked successfully."
        else:
            return False, "Account not found."

    def link_telegram(self, account_id, telegram_id, display_name):
        telegram_id = str(telegram_id)
        existing = self.db.accounts.find_one({"telegram_id": telegram_id, "_id": {"$ne": ObjectId(account_id)}})
        if existing:
            return False, "Telegram account already linked to another user."

        updates = {"telegram_id": telegram_id}
        result = self.db.accounts.update_one(
            {"_id": ObjectId(account_id)},
            {
                "$set": updates,
                "$addToSet": {"auth_providers": "telegram"}
            }
        )

        if result.modified_count > 0:
            self._trigger_event_for_user(account_id, "account_update")
            return True, "Telegram linked."
        else:
            return False, "Account not found."

    def update_account_profile(self, account_id, updates):
        if 'email' in updates:
            updates['email'] = updates['email'].lower()
            existing = self.db.accounts.find_one({"email": updates['email'], "_id": {"$ne": ObjectId(account_id)}})
            if existing:
                return False, "Email is already in use by another account."

        if 'username' in updates:
            updates['username'] = updates['username'].lower()
            existing = self.db.accounts.find_one({"username": updates['username'], "_id": {"$ne": ObjectId(account_id)}})
            if existing:
                return False, "Username is already taken."

        result = self.db.accounts.update_one({"_id": ObjectId(account_id)}, {"$set": updates})

        if result.matched_count > 0:
            self._trigger_event_for_user(account_id, "account_update")
            return True, "Profile updated."
        else:
            return False, "Account not found."

    # ---------------------------------------------------------
    # CLIENT APP MANAGEMENT
    # ---------------------------------------------------------

    def register_application(self, app_name, callback_url, web_url=None, logo_url=None, allowed_methods=None, api_url=None):
        client_id = f"{app_name.lower().replace(' ', '_')}_{secrets.token_hex(4)}"
        client_secret = secrets.token_urlsafe(32)

        # Generate a dedicated secret for Webhook Signing
        webhook_secret = secrets.token_hex(24)

        app_doc = {
            "app_name": app_name,
            "client_id": client_id,
            "client_secret_hash": generate_password_hash(client_secret),
            "webhook_secret": webhook_secret,
            "app_logo_url": logo_url or "/static/default_logo.png",
            "app_web_url": web_url,
            "app_callback_url": callback_url,
            "app_api_url": api_url,
            "allowed_auth_methods": allowed_methods or ["email"],
            "telegram_bot_token": None,
            "created_at": datetime.now(UTC)
        }
        self.db.applications.insert_one(app_doc)

        # Return all secrets to display to admin (one-time)
        return client_id, client_secret, webhook_secret

    def get_app_by_client_id(self, client_id):
        return self.db.applications.find_one({"client_id": client_id})

    def verify_client_secret(self, client_id, provided_secret):
        app = self.get_app_by_client_id(client_id)
        if not app:
            return False
        return check_password_hash(app["client_secret_hash"], provided_secret)

    def link_user_to_app(self, account_id, app_id, role="user", duration_str=None):
        """
        Links a user to an app, optionally calculating an expiration date.
        duration_str examples: '1m' (month), '1y' (year), 'lifetime'
        """
        current_link = self.db.app_links.find_one({"account_id": ObjectId(account_id), "app_id": ObjectId(app_id)})
        old_role = current_link.get('role') if current_link else None

        # Calculate Expiration
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

        # If 'lifetime', explicitly remove expiration
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

        # Trigger Webhook if role changed
        if old_role != role:
            self._trigger_event_for_user(account_id, "account_role_change", specific_app_id=app_id)

    def get_user_role_for_app(self, account_id, app_id):
        link = self.db.app_links.find_one({"account_id": ObjectId(account_id), "app_id": ObjectId(app_id)})
        if not link:
            return None

        # Check Expiration
        if link.get('expires_at') and link['expires_at'].replace(tzinfo=UTC) < datetime.now(UTC):
            return "expired"

        return link.get('role', 'user')

    # ---------------------------------------------------------
    # TENANT DASHBOARD / BACKOFFICE HELPERS
    # ---------------------------------------------------------

    def is_super_admin(self, email):
        """Checks if the email belongs to a Super Admin."""
        if not email: return False
        return self.db.admins.find_one({"email": email.lower()}) is not None

    def get_managed_apps(self, account_id):
        """Returns a list of apps where the user is an 'admin' or 'owner'."""
        links = self.db.app_links.find({
            "account_id": ObjectId(account_id),
            "role": {"$in": ["admin", "owner", "super_admin"]}
        })
        app_ids = [link['app_id'] for link in links]
        return list(self.db.applications.find({"_id": {"$in": app_ids}}))

    def get_all_apps(self):
        """For Super Admin Dashboard."""
        return list(self.db.applications.find({}))

    def get_app_users(self, app_id):
        """
        Returns all users linked to a specific app.
        Joins 'app_links' with 'accounts' to provide a complete view.
        """
        links = list(self.db.app_links.find({"app_id": ObjectId(app_id)}))
        if not links:
            return []

        user_ids = [link['account_id'] for link in links]
        users_cursor = self.db.accounts.find({"_id": {"$in": user_ids}})

        # Create a lookup dictionary
        users_map = {u['_id']: u for u in users_cursor}

        # Merge data
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

    # ---------------------------------------------------------
    # PAYMENT & TRANSACTIONS
    # ---------------------------------------------------------

    def create_transaction(self, account_id, app_id, amount, currency, description, target_role=None, duration=None, ref_id=None):
        """
        Creates a pending transaction with optional subscription details.
        """
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
            "duration": duration,   # '1m', '1y'
            "client_ref_id": ref_id, # External ID from client app
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "provider_ref": None
        }
        self.db.transactions.insert_one(doc)
        return transaction_id

    def complete_transaction(self, transaction_id, provider_ref=None):
        tx = self.db.transactions.find_one({"transaction_id": transaction_id})
        if not tx: return False, "Transaction not found"
        if tx['status'] == 'completed': return True, "Already completed"

        self.db.transactions.update_one(
            {"_id": tx['_id']},
            {"$set": {"status": "completed", "provider_ref": provider_ref, "updated_at": datetime.now(UTC)}}
        )

        # Grant the role and Apply Duration
        if tx.get('target_role'):
            self.link_user_to_app(
                account_id=tx['account_id'],
                app_id=tx['app_id'],
                role=tx['target_role'],
                duration_str=tx.get('duration')
            )

        return True, "Transaction completed and role updated"

    # --- NEW: Universal Payment Listener Logic ---

    def save_pending_payment(self, trx_id, amount, currency, raw_text, payer_name):
        try:
            if self.db.payment_logs.find_one({"trx_id": trx_id}):
                return False

            self.db.payment_logs.insert_one({
                "trx_id": trx_id,
                "amount": float(amount),
                "currency": currency,
                "payer_name": payer_name,
                "raw_text": raw_text,
                "status": "unclaimed",
                "claimed_by_account_id": None,
                "created_at": datetime.now(UTC)
            })
            return True
        except Exception as e:
            log.error(f"Error saving payment log: {e}")
            return False

    def claim_payment(self, trx_input, app_id, user_identity):
        # 1. Resolve User
        user = None
        if 'account_id' in user_identity:
            user = self.find_account_by_id(user_identity['account_id'])
        elif 'telegram_id' in user_identity:
            user = self.find_account_by_telegram(user_identity['telegram_id'])
        elif 'email' in user_identity:
            user = self.find_account_by_email(user_identity['email'])

        if not user:
            return False, "User account not found."

        # 2. Fuzzy Match Payment
        safe_input = str(trx_input).strip()
        regex_pattern = f"{safe_input}$"

        payment = self.db.payment_logs.find_one({
            "status": "unclaimed",
            "trx_id": {"$regex": regex_pattern}
        })

        if not payment:
            return False, "Transaction ID not found or already claimed."

        # 3. Atomic Claim
        result = self.db.payment_logs.update_one(
            {"_id": payment['_id'], "status": "unclaimed"},
            {
                "$set": {
                    "status": "claimed",
                    "claimed_by_account_id": user['_id'],
                    "claimed_for_app_id": ObjectId(app_id),
                    "claimed_method": list(user_identity.keys())[0],
                    "claimed_at": datetime.now(UTC)
                }
            }
        )

        if result.modified_count == 0:
            return False, "Error: Payment claimed by someone else."

        # 4. Grant Premium Role (Triggers Webhook)
        self.link_user_to_app(user['_id'], app_id, role="premium_user")

        return True, f"Success! ${payment['amount']} claimed."

    # ---------------------------------------------------------
    # ADMIN
    # ---------------------------------------------------------

    def create_super_admin(self, email, password):
        admin = {
            "email": email.lower(),
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