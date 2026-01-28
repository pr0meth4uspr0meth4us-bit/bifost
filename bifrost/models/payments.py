# bifrost/models/payments.py
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bson import ObjectId
import logging

log = logging.getLogger(__name__)
UTC = ZoneInfo("UTC")


class PaymentMixin:
    # ---------------------------------------------------------
    # PAYMENT & TRANSACTIONS
    # ---------------------------------------------------------
    def create_transaction(self, account_id, app_id, app_name, amount, currency, description, target_role=None,
                           duration=None,
                           ref_id=None):
        """
        Creates a pending transaction.
        Stores app_name directly to prevent lookup failures later.
        """
        # SECURITY: Double check at model level
        forbidden = ['admin', 'super_admin', 'owner', 'god_admin']
        if target_role and (target_role.lower() in forbidden or 'admin' in target_role.lower()):
            raise ValueError(f"Role '{target_role}' is restricted and cannot be purchased.")

        transaction_id = f"tx-{secrets.token_hex(8)}"
        doc = {
            "transaction_id": transaction_id,
            "account_id": ObjectId(account_id) if account_id else None,
            "app_id": ObjectId(app_id),
            "app_name": app_name,
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

        now = datetime.now(UTC)

        self.db.transactions.update_one(
            {"_id": tx['_id']},
            {"$set": {"status": "completed", "provider_ref": provider_ref, "updated_at": now}}
        )

        # Grant the role and Apply Duration
        if tx.get('target_role') and tx.get('account_id'):
            # 1. Update DB Link (SUPPRESS generic event)
            self.link_user_to_app(
                account_id=tx['account_id'],
                app_id=tx['app_id'],
                role=tx['target_role'],
                duration_str=tx.get('duration'),
                suppress_webhook=True  # <--- SILENCE GENERIC
            )

            # 2. Calculate Expiration for Webhook Payload
            # We mirror the logic from link_user_to_app to ensure the client gets the correct date
            duration_str = tx.get('duration')
            expires_at = None
            if duration_str == '1m':
                expires_at = now + timedelta(days=30)
            elif duration_str == '3m':
                expires_at = now + timedelta(days=90)
            elif duration_str == '6m':
                expires_at = now + timedelta(days=180)
            elif duration_str == '1y':
                expires_at = now + timedelta(days=365)

            # Format as ISO string for JSON payload, or None if lifetime
            expires_at_iso = expires_at.isoformat() if expires_at else None

            # 3. Trigger Specific Payment Success Webhook
            log.info(f"🚀 Triggering subscription_success for TX {transaction_id}")
            self._trigger_event_for_user(
                account_id=tx['account_id'],
                event_type="subscription_success",
                specific_app_id=tx['app_id'],
                extra_data={
                    "transaction_id": transaction_id,
                    "amount": tx['amount'],
                    "currency": tx['currency'],
                    "role": tx['target_role'],
                    "client_ref_id": tx.get('client_ref_id'),
                    "duration": duration_str,  # <--- Added
                    "expires_at": expires_at_iso  # <--- Added
                }
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

        # 4. Grant Premium Role (Claims currently default to 1 Month if not specified)
        self.link_user_to_app(user['_id'], app_id, role="premium_user", suppress_webhook=True)

        # 5. Send Success Webhook for Claims
        self._trigger_event_for_user(
            account_id=user['_id'],
            event_type="subscription_success",
            specific_app_id=app_id,
            extra_data={
                "transaction_id": payment['trx_id'],
                "amount": payment['amount'],
                "currency": payment['currency'],
                "role": "premium_user",
                "method": "claim"
            }
        )

        return True, f"Success! ${payment['amount']} claimed."