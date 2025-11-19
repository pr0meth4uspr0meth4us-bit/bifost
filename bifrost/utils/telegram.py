# bifrost/utils/telegram.py

import hashlib
import hmac
import time
import logging

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