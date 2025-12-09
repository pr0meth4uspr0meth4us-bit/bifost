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
        """Generates the HMAC-SHA512 hash using the API Key."""
        if not self.api_key:
            log.error("Missing PAYWAY_API_KEY")
            return None

        # ABA PayWay requires the key and message to be bytes
        return hmac.new(
            self.api_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()

    def create_transaction(self, transaction_id, amount, items, firstname, lastname, email, phone):
        """
        Calls ABA API to generate a KHQR code (Server-to-Server).
        """
        # 1. Strict Formatting (CRITICAL FOR HASHING)
        # Amount must be 2 decimal places (e.g., "5.00")
        formatted_amount = "{:.2f}".format(float(amount))

        # Items JSON must be compact (no spaces)
        items_json = json.dumps(items, separators=(',', ':'))
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Request Time (YYYYMMDDHHmmSS)
        req_time = datetime.now().strftime('%Y%m%d%H%M%S')

        # Callback URL (Base64 encoded)
        callback_url = f"{self.public_url}/internal/payments/callback"
        return_url = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Static/Optional Fields
        shipping = ""
        type_ = "purchase"
        payment_option = "abapay_khqr"  # Forces QR generation
        continue_success_url = ""  # Optional redirect after success
        return_params = ""  # Optional passthrough params

        # 2. Generate Hash
        # The order is STRICT. Do not change.
        hash_str = (
            f"{req_time}"
            f"{self.merchant_id}"
            f"{transaction_id}"
            f"{formatted_amount}"
            f"{items_base64}"
            f"{shipping}"
            f"{firstname}"
            f"{lastname}"
            f"{email}"
            f"{phone}"
            f"{type_}"
            f"{payment_option}"
            f"{return_url}"
            f"{continue_success_url}"
            f"{return_params}"
        )

        signature = self._generate_hash(hash_str)

        # 3. Build JSON Payload
        # We use JSON instead of Multipart for better reliability
        payload = {
            "req_time": req_time,
            "merchant_id": self.merchant_id,
            "tran_id": transaction_id,
            "amount": formatted_amount,
            "items": items_base64,
            "hash": signature,
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "phone": phone,
            "return_url": return_url,
            "shipping": shipping,
            "type": type_,
            "payment_option": payment_option,
            "continue_success_url": continue_success_url,
            "return_params": return_params
        }

        # 4. Execute Request
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Bifrost/1.0'
        }

        try:
            log.info(f"Sending Payment Request to ABA: {self.api_url} | TranID: {transaction_id}")

            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=30
            )

            # 5. Handle Response
            try:
                data = response.json()
            except json.JSONDecodeError:
                log.error(f"ABA returned non-JSON response: {response.text[:200]}")
                return None

            status_code = data.get('status', {}).get('code')

            if status_code == '00':
                return {
                    "qr_string": data.get('qr_string'),
                    "deeplink": data.get('abapay_deeplink'),
                    "description": data.get('description')
                }
            else:
                log.error(f"ABA API Error: {data.get('status', {}).get('message')} (Code: {status_code})")
                return None

        except Exception as e:
            log.error(f"ABA Request Failed: {e}")
            return None

    def verify_webhook(self, request_data):
        """
        Verifies the hash received from ABA callback.
        """
        received_hash = request_data.get('hash')
        tran_id = request_data.get('tran_id')
        status = request_data.get('status')
        apv = request_data.get('apv', '')  # Approval Code

        # ABA callbacks sometimes use 'req_time', sometimes 'request_time' depending on version
        # We check both.
        req_time = request_data.get('req_time') or request_data.get('request_time') or ""

        if not received_hash or not tran_id:
            return False

        # Hash Construction for Callback:
        # req_time + merchant_id + tran_id + status + apv
        # Note: 'apv' might be empty for failed transactions, but must be in hash string if present
        local_hash_str = f"{req_time}{self.merchant_id}{tran_id}{status}{apv}"

        expected_hash = self._generate_hash(local_hash_str)

        if hmac.compare_digest(expected_hash, received_hash):
            return True

        log.warning(f"Hash mismatch! Expected: {expected_hash} | Got: {received_hash}")
        return False