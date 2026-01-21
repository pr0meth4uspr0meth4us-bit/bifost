import logging
import requests
import hmac
import hashlib
import json
from flask import current_app
from datetime import datetime

log = logging.getLogger(__name__)

class WebhookService:
    @staticmethod
    def send_event(app_doc, event_type, account_id, token=None, extra_data=None):
        """
        Sends an auth event webhook to a specific client application.
        Signs the payload using HMAC-SHA256 for security.
        """
        api_url = app_doc.get('app_api_url')
        client_id = app_doc.get('client_id')
        webhook_secret = app_doc.get('webhook_secret') # New field from DB

        # Safety Check: If we don't have a URL or Secret, we can't send a valid webhook
        if not api_url or not webhook_secret:
            log.warning(f"⚠️ Skipping webhook for {client_id}: Missing URL or Webhook Secret")
            return

        # URL Construction: Ensure no double slashes
        endpoint = f"{api_url.rstrip('/')}/internal/webhook/auth-event"

        payload = {
            "event": event_type,
            "account_id": str(account_id),
            "token": token,
            "timestamp": int(datetime.utcnow().timestamp())
        }

        # Merge extra data (e.g. transaction details) if provided
        if extra_data:
            payload.update(extra_data)

        # 1. Create HMAC Signature
        # Use separators to ensure compact JSON representation (matches most receiver logic)
        payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')

        signature = hmac.new(
            key=webhook_secret.encode('utf-8'),
            msg=payload_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()

        # 2. Prepare Headers
        headers = {
            "Content-Type": "application/json",
            "X-Bifrost-Signature": signature,
            "X-Bifrost-Client-Id": client_id,
            "User-Agent": "Bifrost-IdP/1.0"
        }

        try:
            log.info(f"🚀 Sending webhook to: {endpoint} | Event: {event_type}")
            # Note: No Basic Auth used. Security is handled by the Signature.
            response = requests.post(endpoint, data=payload_bytes, headers=headers, timeout=5)

            if response.status_code in [200, 201]:
                log.info(f"🪝 Webhook sent to {client_id}: {event_type}")
            else:
                log.warning(f"🪝 Webhook failed for {client_id}: {response.status_code} - {response.text}")
        except Exception as e:
            log.error(f"🪝 Webhook connection error for {client_id}: {e}")