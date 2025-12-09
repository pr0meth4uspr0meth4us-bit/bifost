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

    def create_transaction(self, transaction_id, amount, items, firstname, lastname, email, phone):
        """
        Calls ABA API to generate a KHQR code (Server-to-Server).
        """
        # 1. Formatting Data
        # Amount must be 2 decimal places (e.g., "5.00") [cite: 120]
        formatted_amount = "{:.2f}".format(float(amount))

        # Items JSON must be compact (no spaces) and base64 encoded [cite: 120]
        items_json = json.dumps(items, separators=(',', ':'))
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Request Time (YYYYmmddHHMMSS format) [cite: 121]
        req_time = datetime.now().strftime('%Y%m%d%H%M%S')

        # Callback URL (Base64 encoded)
        callback_url = f"{self.public_url}/internal/payments/callback"
        callback_url_b64 = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Fixed Constants for this flow
        payment_option = "abapay_khqr"
        purchase_type = "purchase"
        currency = "USD"
        lifetime = 60
        qr_image_template = "template3_color"

        # Optional Params (Empty strings required for Hash Concatenation)
        return_deeplink = ""  # Can be populated if you have a deeplink scheme
        custom_fields = ""  # Can be Base64 JSON if needed
        return_params = ""
        shipping = ""
        gdt = ""  # Global Discount Total
        ctid = ""  # Custom Transaction ID
        pwt = ""  # PayWay Transaction ID
        cancel_url = ""
        continue_success_url = ""
        topup_channel = ""

        # 2. Generate Hash
        # FIX: Strict concatenation order based on Technical Report Section 5.1.
        # Order: req_time + merchant_id + tran_id + amount + items + gdt + shipping + ctid + pwt +
        #        firstname + lastname + email + phone + type + payment_option + return_url + ...

        hash_str = (
            f"{req_time}"
            f"{self.merchant_id}"
            f"{transaction_id}"
            f"{formatted_amount}"
            f"{items_base64}"  # Critical: Items must be the Base64 version in the hash 
            f"{gdt}"
            f"{shipping}"
            f"{ctid}"
            f"{pwt}"
            f"{firstname}"
            f"{lastname}"
            f"{email}"
            f"{phone}"
            f"{purchase_type}"  # Maps to 'type' in hash string sequence
            f"{payment_option}"
            f"{callback_url_b64}"  # Maps to 'return_url' in hash string sequence
            f"{cancel_url}"
            f"{continue_success_url}"
            f"{return_deeplink}"  # Must be Base64 encoded if present (currently empty)
            f"{topup_channel}"
            f"{currency}"
            f"{custom_fields}"
            f"{return_params}"
        )

        signature = self._generate_hash(hash_str)

        if not signature:
            log.error("Failed to generate hash signature")
            return None

        # 3. Build JSON Payload
        # Note: In the JSON payload, keys use specific names (e.g. 'items' is the base64 string)
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
            "return_deeplink": return_deeplink if return_deeplink else None,
            "custom_fields": custom_fields if custom_fields else None,
            "return_params": return_params if return_params else None,
            "lifetime": lifetime,
            "qr_image_template": qr_image_template,
            "hash": signature
        }

        # 4. Execute Request
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Bifrost/1.0'
        }

        try:
            log.info(f"Sending QR Generation Request to ABA: {self.api_url}")
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=30
            )

            # Log response for debugging
            try:
                data = response.json()
            except json.JSONDecodeError:
                log.error(f"ABA returned non-JSON response: {response.text[:200]}")
                return None

            status = data.get('status', {})
            status_code = status.get('code')

            if status_code == '0' or status_code == 0:  # Success [cite: 134]
                return {
                    "qr_string": data.get('qrString'),
                    "deeplink": data.get('abapay_deeplink'),
                    "description": status.get('message', 'Success')
                }
            else:
                error_message = status.get('message', 'Unknown error')
                log.error(f"ABA API Error: {error_message} (Code: {status_code})")
                log.debug(f"Hash String Sent: {hash_str}")
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