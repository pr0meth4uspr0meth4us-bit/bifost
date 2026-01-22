import secrets
import logging
from datetime import datetime
from bson import ObjectId
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
log = logging.getLogger(__name__)

class PaymentsMixin:
    """Handles Transactions, Payment Logs, and Claims."""

    def create_transaction(self, account_id, app_id, amount, currency, description, target_role=None, duration=None, ref_id=None):
        transaction_id = f"tx-{secrets.token_hex(8)}"
        doc = {
            "transaction_id": transaction_id,
            "account_id": ObjectId(account_id) if account_id else None,
            "app_id": ObjectId(app_id),
            "amount": amount,
            "currency": currency,
            "description": description,
            "status": "pending",
            "target_role": target_role,
            "duration": duration,
            "client_ref_id": ref_id,
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

        # 1. Mark as Completed
        self.db.transactions.update_one(
            {"_id": tx['_id']},
            {"$set": {"status": "completed", "provider_ref": provider_ref, "updated_at": datetime.now(UTC)}}
        )

        # 2. Grant Role & Trigger Events
        if tx.get('target_role') and tx.get('account_id'):
            # This triggers 'account_role_change' automatically if the role changes
            self.link_user_to_app(
                account_id=tx['account_id'],
                app_id=tx['app_id'],
                role=tx['target_role'],
                duration_str=tx.get('duration')
            )

            # --- NEW: Explicitly trigger 'subscription_success' ---
            # This ensures your bot gets the specific payment event it is waiting for
            log.info(f"🚀 Triggering subscription_success for TX {transaction_id}")
            self._trigger_event_for_user(
                account_id=tx['account_id'],
                event_type="subscription_success",
                specific_app_id=tx['app_id']
            )

        return True, "Transaction completed and role updated"

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
        user = None
        if 'account_id' in user_identity:
            user = self.find_account_by_id(user_identity['account_id'])
        elif 'telegram_id' in user_identity:
            user = self.find_account_by_telegram(user_identity['telegram_id'])
        elif 'email' in user_identity:
            user = self.find_account_by_email(user_identity['email'])

        if not user:
            return False, "User account not found."

        safe_input = str(trx_input).strip()
        regex_pattern = f"{safe_input}$"

        payment = self.db.payment_logs.find_one({
            "status": "unclaimed",
            "trx_id": {"$regex": regex_pattern}
        })

        if not payment:
            return False, "Transaction ID not found or already claimed."

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

        # Grant Role & Trigger Event
        self.link_user_to_app(user['_id'], app_id, role="premium_user")

        # Also trigger explicit success here for claimed payments
        self._trigger_event_for_user(
            account_id=user['_id'],
            event_type="subscription_success",
            specific_app_id=app_id
        )

        return True, f"Success! ${payment['amount']} claimed."