from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
import datetime

from bifrost import mongo
from bifrost.models import check_password, hash_password
from bifrost.jwt_utils import create_jwt

auth_api_bp = Blueprint('auth_api', __name__)


def _get_app_and_account(client_id, auth_method):
    """
    Internal helper to validate client_id and auth method.
    Returns (application, error_response)
    """
    if not client_id:
        return None, (jsonify({"error": "client_id is required"}), 400)

    application = mongo.db.applications.find_one({"client_id": client_id})
    if not application:
        return None, (jsonify({"error": "Invalid client_id"}), 404)

    if auth_method not in application.get('allowed_auth_methods', []):
        msg = f"Authentication method '{auth_method}' is not allowed for this application."
        return None, (jsonify({"error": msg}), 403)

    return application, None


@auth_api_bp.route('/login', methods=['POST'])
def api_login():
    """
    Headless login for Email/Password.
    Payload: {"client_id": "...", "email": "...", "password": "..."}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    client_id = data.get('client_id')
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    application, error = _get_app_and_account(client_id, 'email')
    if error:
        return error

    # 1. Find the account
    account = mongo.db.accounts.find_one({"email": email})
    if not account or not check_password(account.get('password_hash'), password):
        return jsonify({"error": "Invalid email or password"}), 401

    if not account.get('is_active', True):
        return jsonify({"error": "Account is disabled"}), 403

    # 2. Check if account is linked to this application
    link = mongo.db.app_links.find_one({
        "account_id": account['_id'],
        "app_id": application['_id']
    })

    if not link:
        # This is a critical security check
        current_app.logger.warning(
            f"API Login blocked: Account {account['_id']} is not linked to app {application['_id']}"
        )
        return jsonify({"error": "Account not authorized for this application"}), 403

    # 3. All checks passed. Create and return JWT.
    token = create_jwt(account['_id'])
    if not token:
        return jsonify({"error": "Token generation failed"}), 500

    return jsonify({"jwt": token})


@auth_api_bp.route('/telegram-login', methods=['POST'])
def api_telegram_login():
    """
    Headless login for Telegram users.
    Finds or creates the user account and app link.
    Payload: {
        "client_id": "...",
        "telegram_id": "123456",
        "display_name": "Tele User" (optional),
        "username": "tele_user" (optional)
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON payload"}), 400

    client_id = data.get('client_id')
    telegram_id = data.get('telegram_id')

    if not telegram_id:
        return jsonify({"error": "telegram_id is required"}), 400

    application, error = _get_app_and_account(client_id, 'telegram')
    if error:
        return error

    # 1. Find or Create the Account
    account = mongo.db.accounts.find_one({"telegram_id": telegram_id})

    if not account:
        # Account doesn't exist, create it
        display_name = data.get('display_name') or data.get('username') or f"User {telegram_id}"

        new_account_data = {
            "telegram_id": telegram_id,
            "display_name": display_name,
            "is_active": True,
            "created_at": datetime.datetime.utcnow()
        }
        result = mongo.db.accounts.insert_one(new_account_data)
        account_id = result.inserted_id
        account = new_account_data
        account['_id'] = account_id

    if not account.get('is_active', True):
        return jsonify({"error": "Account is disabled"}), 403

    # 2. Find or Create the App Link
    account_id = account['_id']
    app_id = application['_id']

    link = mongo.db.app_links.find_one({
        "account_id": account_id,
        "app_id": app_id
    })

    if not link:
        # Automatically link the user to this bot
        mongo.db.app_links.insert_one({
            "account_id": account_id,
            "app_id": app_id,
            "app_specific_role": "user"  # Default role
        })

    # 3. Create and return JWT
    token = create_jwt(account_id)
    if not token:
        return jsonify({"error": "Token generation failed"}), 500

    return jsonify({"jwt": token})