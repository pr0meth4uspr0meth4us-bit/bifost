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

        items_json = json.dumps(items)
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Base64 Encode Return URL
        callback_url = f"{self.public_url}/internal/payments/callback"
        return_url = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Optional fields (Must be empty strings if unused)
        shipping = ""
        type_ = "purchase"
        payment_option = "abapay_khqr"
        continue_success_url = ""
        return_params = ""

        # 2. Generate Hash (Strict Order: 15 params)
        hash_str = (
            f"{req_time}{self.merchant_id}{transaction_id}{amount}{items_base64}"
            f"{shipping}{firstname}{lastname}{email}{phone}"
            f"{type_}{payment_option}{return_url}{continue_success_url}{return_params}"
        )

        signature = self._generate_hash(hash_str)

        # 3. Build Multipart Payload (The Critical Fix)
        # We assume 'files' usage to force multipart/form-data,
        # but we pass (None, value) so it treats them as text fields, not file uploads.
        raw_payload = {
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

        # Convert dictionary to the format requests expects for multipart text fields
        multipart_payload = {k: (None, str(v)) for k, v in raw_payload.items()}

        # 4. Execute Request
        try:
            log.info(f"Sending Payment Request to ABA: {self.api_url} | TranID: {transaction_id}")

            # Use 'files' to force multipart/form-data
            response = requests.post(self.api_url, files=multipart_payload, timeout=25)

            # 5. Handle Response
            try:
                data = response.json()
            except ValueError:
                # If HTML, try to extract the error message title for cleaner logs
                error_msg = "Unknown ABA Error"
                if "<title>" in response.text:
                    start = response.text.find("<title>") + 7
                    end = response.text.find("</title>")
                    error_msg = response.text[start:end]

                log.error(f"ABA HTML Response: {error_msg} | Full Body: {response.text[:200]}...")
                return None

            if data.get('status', {}).get('code') == '00':
                return {
                    "qr_string": data.get('qr_string'),
                    "deeplink": data.get('abapay_deeplink'),
                    "description": data.get('description')
                }
            else:
                log.error(f"ABA API Error Code: {data.get('status', {}).get('message')}")
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
        return False