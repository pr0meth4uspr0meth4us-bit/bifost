# bifrost/utils/telegram.py

import hashlib
import hmac
import time
import logging
import requests
import json

log = logging.getLogger(__name__)

def verify_telegram_data(telegram_data: dict, bot_token: str) -> bool:
    """
    Verifies the authenticity of data received from Telegram.

    Args:
        telegram_data: The dictionary of data received from the Bot/Widget.
                       Must contain 'id', 'auth_date', and 'hash'.
        bot_token: The API token of the bot that authenticated the user.

    Returns:
        bool: True if signature is valid and data is fresh (within 24h).
    """
    if not bot_token:
        log.error("Verification failed: Missing bot_token.")
        return False

    received_hash = telegram_data.get('hash')
    auth_date = telegram_data.get('auth_date')

    if not received_hash or not auth_date:
        log.warning("Verification failed: Missing hash or auth_date.")
        return False

    # 1. Check for replay attacks (Data older than 24 hours)
    if time.time() - int(auth_date) > 86400:
        log.warning("Verification failed: Data is outdated (possible replay attack).")
        return False

    # 2. Construct the data check string
    # Sort keys alphabetically, exclude 'hash', join as key=value separated by \n
    data_check_arr = []
    for key, value in sorted(telegram_data.items()):
        if key != 'hash':
            data_check_arr.append(f"{key}={value}")
    data_check_string = '\n'.join(data_check_arr)

    # 3. Calculate HMAC-SHA256 signature
    # The secret key is the SHA256 hash of the bot token
    secret_key = hashlib.sha256(bot_token.encode('utf-8')).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    # 4. Compare (use secure compare to prevent timing attacks)
    if hmac.compare_digest(calculated_hash, received_hash):
        return True

    log.warning("Verification failed: Hash mismatch.")
    return False

def send_payment_proof_to_admin(file_stream, file_name, user_display_name, user_identifier, app_name, client_id, amount, config):
    """
    Uploads a photo to the Telegram Admin Group with Approval Buttons.

    Args:
        user_identifier: Can be Telegram ID OR Bifrost Account ID.
    """
    bot_token = config.get('BIFROST_BOT_TOKEN')
    chat_id = config.get('PAYMENT_GROUP_ID')

    if not bot_token or not chat_id:
        log.error("Missing BIFROST_BOT_TOKEN or PAYMENT_GROUP_ID")
        return False

    # 1. Construct Caption
    caption = (
        f"📸 <b>Web Upload Proof</b>\n"
        f"User: {user_display_name}\n"
        f"ID: <code>{user_identifier}</code>\n"
        f"App: <b>{app_name}</b>\n"
        f"Amount: {amount}\n"
        f"Action: Verify Screenshot below."
    )

    # 2. Construct Inline Keyboard (JSON)
    # Callback data format: "pay_approve_<USER_ID>|<CLIENT_ID>"
    # Here <USER_ID> will be the Bifrost Account ID (ObjectId)
    callback_data = f"{user_identifier}|{client_id}"

    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"pay_approve_{callback_data}"},
            {"text": "❌ Reject", "callback_data": f"pay_reject_menu_{callback_data}"}
        ]]
    }

    # 3. Send Request via Telegram HTTP API
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    try:
        file_stream.seek(0)

        files = {
            'photo': (file_name, file_stream)
        }
        data = {
            'chat_id': chat_id,
            'caption': caption,
            'parse_mode': 'HTML',
            'reply_markup': json.dumps(reply_markup)
        }

        response = requests.post(url, data=data, files=files, timeout=10)

        if response.status_code == 200:
            return True
        else:
            log.error(f"Telegram API Error: {response.text}")
            return False

    except Exception as e:
        log.error(f"Failed to send photo to Telegram: {e}")
        return False