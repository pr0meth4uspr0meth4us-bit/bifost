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

        FIX: The Technical Report (Section 5.2) specifies that the output
        must be the Base64 encoding of the RAW BINARY digest, not a Hex string.
        """
        if not self.api_key:
            log.error("Missing PAYWAY_API_KEY")
            return None

        # 1. Generate Raw Binary Digest
        signature = hmac.new(
            self.api_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha512
        ).digest()

        # 2. Base64 Encode the binary data
        return base64.b64encode(signature).decode('utf-8')

    # In bifrost/services/payway.py
    # Replace the entire create_transaction method with this:

    # In bifrost/services/payway.py
    # Replace the entire create_transaction method with this:

    def create_transaction(self, transaction_id, amount, items, firstname, lastname, email, phone):
        """
        Calls ABA API to generate a KHQR code (Server-to-Server).
        Uses the /generate-qr endpoint which returns JSON with QR data.
        """
        # 1. Format data
        formatted_amount = "{:.2f}".format(float(amount))

        # Items: compact JSON, base64 encoded
        items_json = json.dumps(items, separators=(',', ':'))
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Timestamp: YYYYMMDDHHmmss
        req_time = datetime.now().strftime('%Y%m%d%H%M%S')

        # Callback URL: base64 encoded
        callback_url = f"{self.public_url}/internal/payments/callback"
        callback_url_b64 = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Required fields
        payment_option = "abapay_khqr"
        purchase_type = "purchase"
        currency = "USD"
        lifetime = 60
        qr_image_template = "template3_color"

        # 2. Generate hash (ONLY include NON-NULL fields)
        # According to official docs, null fields should NOT be in the hash
        hash_str = (
            f"{req_time}"
            f"{self.merchant_id}"
            f"{transaction_id}"
            f"{firstname}"
            f"{lastname}"
            f"{email}"
            f"{phone}"
            f"{formatted_amount}"
            f"{purchase_type}"
            f"{payment_option}"
            f"{items_base64}"
            f"{currency}"
            f"{callback_url_b64}"
            f"{lifetime}"
            f"{qr_image_template}"
        )

        signature = self._generate_hash(hash_str)

        if not signature:
            log.error("Failed to generate hash signature")
            return None

        # 3. Build payload
        # IMPORTANT: ABA expects null values to be actual null (None in Python),
        # NOT empty strings or omitted fields!
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
            "return_deeplink": None,  # Send as null, not omitted
            "custom_fields": None,  # Send as null, not omitted
            "return_params": None,  # Send as null, not omitted
            "payout": None,  # Send as null, not omitted
            "lifetime": lifetime,
            "qr_image_template": qr_image_template,
            "hash": signature
        }

        # 4. Execute request
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Bifrost/1.0'
        }

        try:
            log.info(f"Sending QR Request to ABA: {self.api_url}")
            log.info(f"Transaction ID: {transaction_id} | Amount: {formatted_amount} {currency}")

            # Debug: print payload to see what's being sent
            log.debug(f"Payload: {json.dumps(payload, indent=2)}")

            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=30
            )

            log.info(f"ABA Response Status: {response.status_code}")

            # 5. Handle response
            try:
                data = response.json()
            except json.JSONDecodeError:
                log.error(f"ABA returned non-JSON: {response.text[:200]}")
                return None

            status = data.get('status', {})
            status_code = str(status.get('code', ''))

            if status_code == '0':  # Success
                return {
                    "qr_string": data.get('qrString'),
                    "deeplink": data.get('abapay_deeplink'),
                    "description": status.get('message', 'Success')
                }
            else:
                error_msg = status.get('message', 'Unknown error')
                log.error(f"ABA API Error: {error_msg} (Code: {status_code})")
                log.error(f"Full response: {json.dumps(data, indent=2)}")
                return None

        except requests.exceptions.RequestException as e:
            log.error(f"ABA Request Failed: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            return None

    def verify_webhook(self, request_data):
        """
        Verifies the hash received from ABA callback.
        """
        received_hash = request_data.get('hash')
        tran_id = request_data.get('tran_id')
        status = request_data.get('status')
        apv = request_data.get('apv', '')  # Approval Code
        req_time = request_data.get('req_time') or request_data.get('request_time') or ""

        if not received_hash or not tran_id:
            return False

        # Hash Construction for Callback:
        # Standard PayWay callback hash order: req_time + merchant_id + tran_id + status + apv [cite: 139]
        local_hash_str = f"{req_time}{self.merchant_id}{tran_id}{status}{apv}"

        expected_hash = self._generate_hash(local_hash_str)

        # Use constant time comparison
        if hmac.compare_digest(expected_hash, received_hash):
            return True

        log.warning(f"Hash mismatch! Expected: {expected_hash} | Got: {received_hash}")
        return False