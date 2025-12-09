import base64
import hashlib
import hmac
import json
import logging
import requests
from flask import current_app
from datetime import datetime

log = logging.getLogger(__name__)


class PayWayService:
    def __init__(self):
        self.api_url = current_app.config['PAYWAY_API_URL']
        self.merchant_id = current_app.config['PAYWAY_MERCHANT_ID']
        self.api_key = current_app.config['PAYWAY_API_KEY']
        self.public_url = current_app.config['BIFROST_PUBLIC_URL']

    def _generate_hash(self, data_string):
        """
        Generates the HMAC-SHA512 hash using the API Key.
        """
        if not self.api_key:
            log.error("Missing PAYWAY_API_KEY")
            return None

        return hmac.new(
            self.api_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()

    def create_transaction(self, transaction_id, amount, items, firstname, lastname, email, phone):
        """
        Calls ABA API directly to generate a KHQR code.
        """
        # 1. Prepare Data
        req_time = datetime.now().strftime('%Y%m%d%H%M%S')

        # Base64 Encode Items
        items_json = json.dumps(items)
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Base64 Encode Return URL
        callback_url = f"{self.public_url}/internal/payments/callback"
        return_url = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Optional fields
        shipping = ""
        type_ = "purchase"
        payment_option = "abapay_khqr"  # Forces QR generation
        continue_success_url = ""
        return_params = ""

        # 2. Generate Hash (Strict Order)
        hash_str = (
            f"{req_time}{self.merchant_id}{transaction_id}{amount}{items_base64}"
            f"{shipping}{firstname}{lastname}{email}{phone}"
            f"{type_}{payment_option}{return_url}{continue_success_url}{return_params}"
        )

        signature = self._generate_hash(hash_str)

        # 3. Build Payload
        # IMPORTANT: We use a standard dictionary here, NOT a tuple with None.
        # This allows requests to send it as 'application/x-www-form-urlencoded'
        payload = {
            'req_time': req_time,
            'merchant_id': self.merchant_id,
            'tran_id': transaction_id,
            'amount': amount,
            'items': items_base64,
            'hash': signature,
            'firstname': firstname,
            'lastname': lastname,
            'email': email,
            'phone': phone,
            'return_url': return_url,
            'shipping': shipping,
            'type': type_,
            'payment_option': payment_option,
            'continue_success_url': continue_success_url,
            'return_params': return_params
        }

        # 4. Execute Request
        try:
            log.info(f"Sending Payment Request to ABA: {self.api_url} | TranID: {transaction_id}")

            # FIX: Use 'data=' instead of 'files='.
            # This sends Content-Type: application/x-www-form-urlencoded
            response = requests.post(self.api_url, data=payload, timeout=20)

            # Check for HTTP errors first
            response.raise_for_status()

            # Parse JSON
            try:
                data = response.json()
            except ValueError:
                # If ABA returns HTML (maintenance/error page), log it
                log.error(f"ABA returned non-JSON response: {response.text[:200]}...")
                return None

            # Check Logic Status
            if data.get('status', {}).get('code') == '00':
                return {
                    "qr_string": data.get('qr_string'),
                    "deeplink": data.get('abapay_deeplink'),
                    "description": data.get('description')
                }
            else:
                log.error(f"ABA API Error: {data}")
                return None

        except Exception as e:
            log.error(f"ABA Request Failed: {e}")
            return None

    def verify_webhook(self, request_data):
        received_hash = request_data.get('hash')
        tran_id = request_data.get('tran_id')
        status = request_data.get('status')
        req_time = request_data.get('request_time') or request_data.get('req_time')

        if not received_hash or not tran_id or not status:
            return False

        local_hash_str = f"{req_time}{self.merchant_id}{tran_id}{status}"
        expected_hash = self._generate_hash(local_hash_str)

        if hmac.compare_digest(expected_hash, received_hash):
            return True

        log.warning(f"Hash Mismatch! Expected: {expected_hash} | Got: {received_hash}")
        return False