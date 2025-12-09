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
        Uses multipart/form-data as per official PayWay documentation.
        """
        # 1. Strict Formatting (CRITICAL FOR HASHING)
        # Amount must be 2 decimal places (e.g., "5.00")
        formatted_amount = "{:.2f}".format(float(amount))

        # Items JSON must be compact (no spaces) and base64 encoded
        items_json = json.dumps(items, separators=(',', ':'))
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Request Time (YYYYmmddHHMMSS format - notice the lowercase 'm' for month)
        req_time = datetime.now().strftime('%Y%m%d%H%M%S')

        # Callback URL (Base64 encoded)
        callback_url = f"{self.public_url}/internal/payments/callback"
        return_url = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Static/Optional Fields - MUST be empty strings, not None
        shipping = ""
        ctid = ""  # Consumer Token ID (for saved accounts)
        pwt = ""  # PayWay Token (for saved accounts)
        type_ = "purchase"
        payment_option = "abapay"  # Changed from abapay_khqr to just abapay
        continue_success_url = ""
        return_deeplink = ""
        currency = "USD"  # or "KHR"
        custom_fields = ""
        return_params = ""

        # 2. Generate Hash
        # CRITICAL: The order MUST match the official documentation EXACTLY
        # Order from docs: req_time + merchant_id + tran_id + amount + items + shipping +
        # ctid + pwt + firstname + lastname + email + phone + type + payment_option +
        # return_url + cancel_url + continue_success_url + return_deeplink + currency +
        # custom_fields + return_params

        hash_str = (
            f"{req_time}"
            f"{self.merchant_id}"
            f"{transaction_id}"
            f"{formatted_amount}"
            f"{items_base64}"
            f"{shipping}"
            f"{ctid}"
            f"{pwt}"
            f"{firstname}"
            f"{lastname}"
            f"{email}"
            f"{phone}"
            f"{type_}"
            f"{payment_option}"
            f"{return_url}"
            f""  # cancel_url (empty)
            f"{continue_success_url}"
            f"{return_deeplink}"
            f"{currency}"
            f"{custom_fields}"
            f"{return_params}"
        )

        signature = self._generate_hash(hash_str)

        if not signature:
            log.error("Failed to generate hash signature")
            return None

        # 3. Build Form Data Payload
        # CRITICAL: Must use multipart/form-data, NOT JSON
        payload = {
            "req_time": req_time,
            "merchant_id": self.merchant_id,
            "tran_id": transaction_id,
            "amount": formatted_amount,
            "items": items_base64,
            "shipping": shipping,
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "phone": phone,
            "type": type_,
            "payment_option": payment_option,
            "return_url": return_url,
            "continue_success_url": continue_success_url,
            "currency": currency,
            "hash": signature
        }

        # 4. Execute Request
        # No Content-Type header - requests will set it automatically for form-data
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'Bifrost/1.0'
        }

        try:
            log.info(f"Sending Payment Request to ABA: {self.api_url}")
            log.info(f"Transaction ID: {transaction_id} | Amount: {formatted_amount} {currency}")
            log.debug(f"Hash String (for debugging): {hash_str[:100]}...")

            response = requests.post(
                self.api_url,
                data=payload,  # Changed from json= to data= for form-data
                headers=headers,
                timeout=30
            )

            # Log response for debugging
            log.info(f"ABA Response Status: {response.status_code}")
            log.debug(f"ABA Response Body: {response.text[:500]}")

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
                error_message = data.get('status', {}).get('message', 'Unknown error')
                log.error(f"ABA API Error: {error_message} (Code: {status_code})")
                log.error(f"Full error response: {json.dumps(data, indent=2)}")
                return None

        except requests.exceptions.RequestException as e:
            log.error(f"ABA Request Failed: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error in ABA transaction: {e}")
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