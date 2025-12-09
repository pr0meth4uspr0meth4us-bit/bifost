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
        Generates the HMAC-SHA512 hash using the API Key (Public Key).
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

        Args:
            transaction_id (str): Unique ID from Bifrost DB.
            amount (str): formatted as "10.00"
            items (list): List of dicts [{"name":.., "price":..}]

        Returns:
            dict: { "qr_string": "...", "deeplink": "..." } or None
        """
        # 1. Prepare Data
        # For Sandbox, fixed time is often safer to prevent drift errors,
        # but in Prod use: datetime.now().strftime('%Y%m%d%H%M%S')
        req_time = datetime.now().strftime('%Y%m%d%H%M%S')

        # Base64 Encode Items
        items_json = json.dumps(items)
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Base64 Encode Return URL (The Callback)
        # We point this to our generic callback endpoint
        callback_url = f"{self.public_url}/internal/payments/callback"
        return_url = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Optional fields must be empty strings for the hash, but MUST be present in the string
        shipping = ""
        type_ = "purchase"  # Sometimes required to be 'purchase' or empty
        payment_option = "abapay_khqr"  # Force KHQR
        continue_success_url = ""
        return_params = ""

        # 2. Generate Hash (Strict Order: 15 params)
        # Consult ABA documentation for exact order. Standard V1 is:
        # req_time + merchant_id + tran_id + amount + items + shipping + firstname + lastname + email + phone + type + payment_option + return_url + continue_success_url + return_params
        hash_str = (
            f"{req_time}{self.merchant_id}{transaction_id}{amount}{items_base64}"
            f"{shipping}{firstname}{lastname}{email}{phone}"
            f"{type_}{payment_option}{return_url}{continue_success_url}{return_params}"
        )

        signature = self._generate_hash(hash_str)

        # 3. Build Multipart Payload
        # We use a tuple (None, value) to force 'multipart/form-data' without uploading actual files
        files = {
            'req_time': (None, req_time),
            'merchant_id': (None, self.merchant_id),
            'tran_id': (None, transaction_id),
            'amount': (None, amount),
            'items': (None, items_base64),
            'hash': (None, signature),
            'firstname': (None, firstname),
            'lastname': (None, lastname),
            'email': (None, email),
            'phone': (None, phone),
            'return_url': (None, return_url),
            'shipping': (None, shipping),
            'type': (None, type_),
            'payment_option': (None, payment_option),
            'continue_success_url': (None, continue_success_url),
            'return_params': (None, return_params)
        }

        # 4. Execute Request
        try:
            log.info(f"Sending Payment Request to ABA: {self.api_url} | TranID: {transaction_id}")
            response = requests.post(self.api_url, files=files, timeout=15)

            # Check for non-200 HTTP codes
            response.raise_for_status()

            # Parse JSON
            # ABA sometimes returns text/html on error, so be careful
            try:
                data = response.json()
            except ValueError:
                log.error(f"ABA returned non-JSON response: {response.text}")
                return None

            # Check logic status code
            if data.get('status', {}).get('code') == '00':
                return {
                    "qr_string": data.get('qr_string'),  # Raw string to generate QR Image
                    "deeplink": data.get('abapay_deeplink'),  # Link for Mobile App
                    "description": data.get('description')
                }
            else:
                log.error(f"ABA API Error: {data}")
                return None

        except Exception as e:
            log.error(f"ABA Request Failed: {e}")
            return None

    def verify_webhook(self, request_data):
        """
        Verifies the 'pushback' (webhook) from PayWay.
        """
        received_hash = request_data.get('hash')
        tran_id = request_data.get('tran_id')
        status = request_data.get('status')
        # In pushback, they typically send 'request_time' OR 'req_time', check both
        req_time = request_data.get('request_time') or request_data.get('req_time')

        if not received_hash or not tran_id or not status:
            return False

        # Pushback Hash Order: req_time + merchant_id + tran_id + status
        local_hash_str = f"{req_time}{self.merchant_id}{tran_id}{status}"
        expected_hash = self._generate_hash(local_hash_str)

        if hmac.compare_digest(expected_hash, received_hash):
            return True

        log.warning(f"Hash Mismatch! Expected: {expected_hash} | Got: {received_hash}")
        return False