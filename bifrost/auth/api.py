# bifrost/auth/api.py

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from zoneinfo import ZoneInfo
import jwt

# Use Relative Imports
from .. import mongo
from ..utils.telegram import verify_telegram_data

auth_api_bp = Blueprint('auth_api', __name__, url_prefix='/auth/api')
UTC_TZ = ZoneInfo("UTC")

@auth_api_bp.route('/telegram-login', methods=['POST'])
def telegram_login():
    """
    Securely authenticates a Telegram user via the Headless API.
    Expects signed 'telegram_data' in the payload.
    """
    data = request.json
    client_id = data.get('client_id')
    tg_data = data.get('telegram_data')

    if not client_id or not tg_data:
        return jsonify({"error": "Missing client_id or telegram_data"}), 400

    # Fetch the Client Application Config
    app_config = mongo.db.applications.find_one({"client_id": client_id})

    if not app_config:
        return jsonify({"error": "Invalid client_id"}), 401

    if "telegram" not in app_config.get("allowed_auth_methods", []):
        return jsonify({"error": "Telegram auth not enabled for this application"}), 403

    # Retrieve the secret Bot Token stored in Bifrost for this App
    bot_token = app_config.get("telegram_bot_token")
    if not bot_token:
        return jsonify({"error": "Server misconfiguration: No Bot Token found for this App"}), 500

    # --- CRITICAL SECURITY CHECK ---
    if not verify_telegram_data(tg_data, bot_token):
        return jsonify({"error": "Authentication verification failed"}), 401
    # -------------------------------

    # Data is now Trusted
    telegram_id = str(tg_data['id'])

    # Find or Create Account
    user = mongo.db.accounts.find_one({"telegram_id": telegram_id})

    if not user:
        user = {
            "telegram_id": telegram_id,
            "display_name": tg_data.get('first_name', 'Unknown'),
            "created_at": datetime.now(UTC_TZ),
            "is_active": True,
            "auth_providers": ["telegram"]
        }
        result = mongo.db.accounts.insert_one(user)
        user['_id'] = result.inserted_id

    user_id = user['_id']

    # Link User to App (Bifrost <-> FinanceBot Link)
    link = mongo.db.app_links.find_one({
        "account_id": user_id,
        "app_id": app_config['_id']
    })

    if not link:
        mongo.db.app_links.insert_one({
            "account_id": user_id,
            "app_id": app_config['_id'],
            "role": "user",
            "linked_at": datetime.now(UTC_TZ)
        })

    # Issue JWT
    token_payload = {
        "sub": str(user_id),
        "iss": "bifrost",
        "aud": client_id,
        "iat": datetime.now(UTC_TZ),
        "exp": datetime.now(UTC_TZ).timestamp() + 3600
    }

    encoded_jwt = jwt.encode(
        token_payload,
        current_app.config['JWT_SECRET_KEY'],
        algorithm="HS256"
    )

    return jsonify({
        "jwt": encoded_jwt,
        "account_id": str(user_id),
        "display_name": user.get('display_name')
    })