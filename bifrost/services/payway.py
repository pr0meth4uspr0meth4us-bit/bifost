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
        """
        if not self.api_key:
            log.error("Missing PAYWAY_API_KEY")
            return None

        # 1. Generate Raw Binary Digest (Not Hex!)
        signature = hmac.new(
            self.api_key.encode('utf-8'),
            data_string.encode('utf-8'),
            hashlib.sha512
        ).digest()

        # 2. Base64 Encode
        return base64.b64encode(signature).decode('utf-8')

    def create_transaction(self, transaction_id, amount, items, firstname, lastname, email, phone):
        """
        Calls ABA API to generate a KHQR code.
        STRICT HASH ORDER IMPLEMENTATION.
        """
        # 1. Formatting Data
        formatted_amount = "{:.2f}".format(float(amount))

        # Items: Compact JSON -> Base64
        items_json = json.dumps(items, separators=(',', ':'))
        items_base64 = base64.b64encode(items_json.encode('utf-8')).decode('utf-8')

        # Request Time
        req_time = datetime.now().strftime('%Y%m%d%H%M%S')

        # Callback URL -> Base64
        callback_url = f"{self.public_url}/internal/payments/callback"
        callback_url_b64 = base64.b64encode(callback_url.encode('utf-8')).decode('utf-8')

        # Standard Fields
        payment_option = "abapay_khqr"
        purchase_type = "purchase"
        currency = "USD"

        # Optional/Empty Fields (REQUIRED for Hash Position)
        gdt = ""
        shipping = ""
        ctid = ""
        pwt = ""
        cancel_url = ""
        continue_success_url = ""
        return_deeplink = ""
        topup_channel = ""
        custom_fields = ""
        return_params = ""

        # Extra Params for Body (Not typically hashed in V1, but sent in body)
        lifetime = 60
        qr_image_template = "template3_color"

        # 2. GENERATE HASH - STRICT ORDER (Report Sec 5.1)
        # The API expects values in this EXACT sequence.
        # DO NOT CHANGE THE ORDER.
        hash_str = (
            f"{req_time}"
            f"{self.merchant_id}"
            f"{transaction_id}"
            f"{formatted_amount}"
            f"{items_base64}"
            f"{gdt}"  # Placeholder for Global Discount
            f"{shipping}"  # Placeholder for Shipping
            f"{ctid}"  # Placeholder for Custom Tx ID
            f"{pwt}"  # Placeholder for PayWay Tx
            f"{firstname}"
            f"{lastname}"
            f"{email}"
            f"{phone}"
            f"{purchase_type}"
            f"{payment_option}"
            f"{callback_url_b64}"
            f"{cancel_url}"  # Placeholder for Cancel URL
            f"{continue_success_url}"  # Placeholder for Continue URL
            f"{return_deeplink}"  # Placeholder (Base64)
            f"{topup_channel}"  # Placeholder
            f"{currency}"
            f"{custom_fields}"  # Placeholder (Base64)
            f"{return_params}"  # Placeholder
        )

        signature = self._generate_hash(hash_str)

        if not signature:
            log.error("Failed to generate hash signature")
            return None

        # 3. Build JSON Payload
        # Note: We only send the fields we have data for, but the hash
        # must include the empty strings above to be valid.
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
            "lifetime": lifetime,
            "qr_image_template": qr_image_template,
            "hash": signature
        }

        # 4. Execute Request
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        try:
            log.info(f"Sending QR Request to ABA: {self.api_url}")
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=30
            )

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
                log.debug(f"Full response: {json.dumps(data, indent=2)}")
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
        apv = request_data.get('apv', '')
        req_time = request_data.get('req_time') or request_data.get('request_time') or ""

        if not received_hash or not tran_id:
            return False

        # Hash Construction for Callback:
        # req_time + merchant_id + tran_id + status + apv
        local_hash_str = f"{req_time}{self.merchant_id}{tran_id}{status}{apv}"

        expected_hash = self._generate_hash(local_hash_str)

        if hmac.compare_digest(expected_hash, received_hash):
            return True

        log.warning(f"Hash mismatch! Expected: {expected_hash} | Got: {received_hash}")
        return False