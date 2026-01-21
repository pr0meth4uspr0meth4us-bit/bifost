import random
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo
from bson import ObjectId
from werkzeug.security import generate_password_hash
import logging

log = logging.getLogger(__name__)
UTC = ZoneInfo("UTC")

class AuthMixin:
    # ---------------------------------------------------------
    # OTP UTILITIES
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
            existing = self.db.accounts.find_one(
                {"username": updates['username'], "_id": {"$ne": ObjectId(account_id)}})
            if existing:
                return False, "Username is already taken."

        result = self.db.accounts.update_one({"_id": ObjectId(account_id)}, {"$set": updates})

        if result.matched_count > 0:
            self._trigger_event_for_user(account_id, "account_update")
            return True, "Profile updated."
        else:
            return False, "Account not found."