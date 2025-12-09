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
        Generates the HMAC-SHA512 hash (Base64 of Binary).
        CRITICAL: Must use binary digest, NOT hex digest!
        """
        if not self.api_key:
            log.error("Missing PAYWAY_API_KEY")
            return None

        # Generate Raw Binary Digest
        signature = hmac.new(
            self.api_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha512
        ).digest()

        # Base64 Encode the binary
        return base64.b64encode(signature).decode('utf-8')

    def create_transaction(self, transaction_id, amount, items, firstname, lastname, email, phone):
        """
        Calls ABA API to generate a KHQR code.
        FIXED: Proper hash construction following ABA's exact specification.
        """
        # 1. Format and Encode Data
        formatted_amount = "{:.2f}".format(float(amount))

        # Items: Compact JSON -> Base64
        items_json = json.dumps(items, separators=(',', ':'))
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Request Time
        req_time = datetime.now().strftime('%Y%m%d%H%M%S')

        # Callback URL -> Base64
        callback_url = f"{self.public_url}/internal/payments/callback"
        callback_url_b64 = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Payment Configuration
        payment_option = "abapay_khqr"
        purchase_type = "purchase"
        currency = "USD"

        # 2. CRITICAL FIX: Hash String Construction
        # According to ABA PayWay API v1 documentation, the hash string must be:
        # req_time + merchant_id + tran_id + amount + items + firstname + lastname +
        # email + phone + purchase_type + payment_option + callback_url + currency

        hash_str = (
            f"{req_time}"
            f"{self.merchant_id}"
            f"{transaction_id}"
            f"{formatted_amount}"
            f"{items_base64}"
            f"{firstname}"
            f"{lastname}"
            f"{email}"
            f"{phone}"
            f"{purchase_type}"
            f"{payment_option}"
            f"{callback_url_b64}"
            f"{currency}"
        )

        signature = self._generate_hash(hash_str)

        if not signature:
            log.error("Failed to generate hash signature")
            return None

        # 3. Build JSON Payload
        payload = {
            "req_time": req_time,
            "merchant_id": self.merchant_id,
            "tran_id": transaction_id,
            "first_name": firstname,
            "last_name": lastname,
            "email": email,
            "phone": phone,
            "amount": float(formatted_amount),
            "purchase_type": purchase_type,
            "payment_option": payment_option,
            "items": items_base64,
            "currency": currency,
            "callback_url": callback_url_b64,
            "lifetime": 60,
            "qr_image_template": "template3_color",
            "hash": signature
        }

        # 4. Debug Logging (Remove in production)
        log.info(f"=== ABA PayWay Request Debug ===")
        log.info(f"Transaction ID: {transaction_id}")
        log.info(f"Amount: {formatted_amount}")
        log.info(f"Hash String Components:")
        log.info(f"  req_time: {req_time}")
        log.info(f"  merchant_id: {self.merchant_id}")
        log.info(f"  tran_id: {transaction_id}")
        log.info(f"  amount: {formatted_amount}")
        log.info(f"  items_base64: {items_base64[:50]}...")
        log.info(f"  firstname: {firstname}")
        log.info(f"  lastname: {lastname}")
        log.info(f"  email: {email}")
        log.info(f"  phone: {phone}")
        log.info(f"  purchase_type: {purchase_type}")
        log.info(f"  payment_option: {payment_option}")
        log.info(f"  callback_url_b64: {callback_url_b64[:50]}...")
        log.info(f"  currency: {currency}")
        log.info(f"Generated Hash: {signature[:50]}...")
        log.info(f"================================")

        # 5. Execute Request
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        try:
            log.info(f"Sending request to: {self.api_url}")
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=30
            )

            log.info(f"ABA Response Status: {response.status_code}")
            log.info(f"ABA Response Body: {response.text[:500]}")

            try:
                data = response.json()
            except json.JSONDecodeError:
                log.error(f"ABA returned non-JSON: {response.text[:200]}")
                return None

            status_code = str(data.get('status', {}).get('code'))

            if status_code == '0':
                return {
                    "qr_string": data.get('qrString'),
                    "deeplink": data.get('abapay_deeplink'),
                    "description": data.get('description', 'Success')
                }
            else:
                log.error(f"ABA API Error: {data.get('status', {}).get('message')} (Code: {status_code})")
                log.error(f"Full response: {json.dumps(data, indent=2)}")
                return None

        except Exception as e:
            log.error(f"ABA Request Failed: {e}", exc_info=True)
            return None

    def verify_webhook(self, request_data):
        """
        Verifies the hash received from ABA callback.
        Hash format: req_time + merchant_id + tran_id + status + apv
        """
        received_hash = request_data.get('hash')
        tran_id = request_data.get('tran_id')
        status = request_data.get('status')
        apv = request_data.get('apv', '')
        req_time = request_data.get('req_time') or request_data.get('request_time') or ""

        if not received_hash or not tran_id:
            log.warning("Webhook missing required fields")
            return False

        # Construct callback hash string
        local_hash_str = f"{req_time}{self.merchant_id}{tran_id}{status}{apv}"

        log.info(f"=== Webhook Hash Debug ===")
        log.info(f"Callback hash string: {local_hash_str}")
        log.info(f"Received hash: {received_hash}")

        expected_hash = self._generate_hash(local_hash_str)
        log.info(f"Expected hash: {expected_hash}")
        log.info(f"========================")

        if expected_hash and hmac.compare_digest(expected_hash, received_hash):
            return True

        log.warning(f"Hash mismatch! Expected: {expected_hash} | Got: {received_hash}")
        return False