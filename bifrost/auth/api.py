from flask import Blueprint, request, jsonify, current_app
from datetime import datetime
from zoneinfo import ZoneInfo
import jwt
from werkzeug.security import check_password_hash
import logging
from bson import ObjectId

# Use Relative Imports
from .. import mongo
from ..models import BifrostDB
from ..services.email_service import send_otp_email
from ..utils.telegram import verify_telegram_data

auth_api_bp = Blueprint('auth_api', __name__, url_prefix='/auth/api')
UTC_TZ = ZoneInfo("UTC")
log = logging.getLogger(__name__)


# =========================================================
#  SECTION 1: PUBLIC OTP & ACCOUNT MANAGEMENT (HEADLESS)
# =========================================================

@auth_api_bp.route('/check-email', methods=['POST'])
def check_email():
    """Checks if an email or username is already registered."""
    data = request.json
    identifier = data.get('email') or data.get('username')

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    user = db.find_account_by_email(identifier) or db.find_account_by_username(identifier)

    return jsonify({"exists": bool(user)})


@auth_api_bp.route('/request-email-otp', methods=['POST'])
def request_email_otp():
    """Generates an OTP for an email address."""
    data = request.json
    email = data.get('email')
    client_id = data.get('client_id')

    if not email or not client_id:
        return jsonify({"error": "Missing email or client_id"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_config = db.get_app_by_client_id(client_id)
    if not app_config:
        return jsonify({"error": "Invalid client_id"}), 401

    app_name = app_config.get('app_name', 'Bifrost Identity')
    code, verification_id = db.create_otp(email, channel="email")

    if send_otp_email(to_email=email, otp=code, app_name=app_name):
        return jsonify({"message": "OTP sent successfully", "verification_id": verification_id})
    return jsonify({"error": "Failed to send email"}), 500


@auth_api_bp.route('/verify-email-otp', methods=['POST'])
def verify_email_otp():
    """Verifies OTP and returns a Proof Token for registration/reset."""
    data = request.json
    verification_id = data.get('verification_id')
    code = data.get('code')

    if not verification_id or not code:
        return jsonify({"error": "Missing verification_id or code"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    oid_record = db.db.verification_codes.find_one({"_id": ObjectId(verification_id)})

    if not oid_record:
        return jsonify({"error": "Invalid or expired verification session"}), 400

    if not db.verify_otp(verification_id=verification_id, code=code):
        return jsonify({"error": "Invalid code"}), 401

    proof_payload = {
        "email": oid_record['identifier'],
        "scope": "credential_change",
        "verified": True,
        "iss": "bifrost",
        "exp": datetime.now(UTC_TZ).timestamp() + 300
    }
    proof_token = jwt.encode(proof_payload, current_app.config['JWT_SECRET_KEY'], algorithm="HS256")

    return jsonify({"success": True, "proof_token": proof_token, "email": oid_record['identifier']})


@auth_api_bp.route('/complete-registration', methods=['POST'])
def complete_registration():
    """Finalizes account creation with password and optional username."""
    data = request.json
    proof_token = data.get('proof_token')
    password = data.get('password')
    username = data.get('username')
    display_name = data.get('display_name')
    client_id = data.get('client_id')

    if not proof_token or not password or not client_id:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        payload = jwt.decode(proof_token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
        if payload.get('scope') != 'credential_change': raise jwt.InvalidTokenError()
        email = payload.get('email')
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid or expired proof token"}), 403

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_config = db.get_app_by_client_id(client_id)
    if not app_config: return jsonify({"error": "Invalid client_id"}), 401

    if username and db.find_account_by_username(username):
        return jsonify({"error": "Username is already taken"}), 409

    existing_user = db.find_account_by_email(email)
    if existing_user:
        db.update_password(email, password)
        if username: db.db.accounts.update_one({"_id": existing_user['_id']}, {"$set": {"username": username.lower()}})
        user_id = existing_user['_id']
    else:
        user_id = db.create_account({
            "email": email,
            "username": username,
            "password": password,
            "display_name": display_name or username or email.split('@')[0],
            "auth_providers": ["email"]
        })

    db.link_user_to_app(user_id, app_config['_id'])

    token_payload = {
        "sub": str(user_id),
        "iss": "bifrost",
        "aud": client_id,
        "iat": datetime.now(UTC_TZ),
        "exp": datetime.now(UTC_TZ).timestamp() + 3600 * 24 * 7
    }
    encoded_jwt = jwt.encode(token_payload, current_app.config['JWT_SECRET_KEY'], algorithm="HS256")

    return jsonify({"success": True, "jwt": encoded_jwt, "account_id": str(user_id)})


@auth_api_bp.route('/reset-password', methods=['POST'])
def reset_password():
    """Resets password using a Proof Token."""
    data = request.json
    proof_token = data.get('proof_token')
    password = data.get('password')

    try:
        payload = jwt.decode(proof_token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
        email = payload.get('email')
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid proof token"}), 403

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    db.update_password(email, password)
    return jsonify({"success": True})


# =========================================================
#  SECTION 2: LOGIN ENDPOINTS
# =========================================================

@auth_api_bp.route('/login', methods=['POST'])
def login():
    """Login supporting Email or Username."""
    data = request.json
    client_id = data.get('client_id')
    identifier = data.get('identifier') or data.get('email') or data.get('username')
    password = data.get('password')

    if not client_id or not identifier or not password:
        return jsonify({"error": "Missing credentials"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_config = db.get_app_by_client_id(client_id)
    if not app_config: return jsonify({"error": "Invalid client_id"}), 401

    # Search both email and username
    user = db.find_account_by_email(identifier) or db.find_account_by_username(identifier)

    if not user or not user.get('password_hash') or not check_password_hash(user['password_hash'], password):
        return jsonify({"error": "Invalid credentials"}), 401

    db.link_user_to_app(user['_id'], app_config['_id'])

    token_payload = {
        "sub": str(user['_id']),
        "iss": "bifrost",
        "aud": client_id,
        "iat": datetime.now(UTC_TZ),
        "exp": datetime.now(UTC_TZ).timestamp() + 3600 * 24 * 7
    }
    encoded_jwt = jwt.encode(token_payload, current_app.config['JWT_SECRET_KEY'], algorithm="HS256")

    return jsonify({"jwt": encoded_jwt, "account_id": str(user['_id']), "display_name": user.get('display_name')})


@auth_api_bp.route('/verify-otp-login', methods=['POST'])
def verify_otp_login():
    """Verifies a code for Login (Telegram mainly)."""
    data = request.json
    client_id = data.get('client_id')
    code = data.get('code')

    if not client_id or not code:
        return jsonify({"error": "Missing client_id or code"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_config = db.get_app_by_client_id(client_id)
    if not app_config: return jsonify({"error": "Invalid client_id"}), 401

    telegram_id = db.verify_and_consume_code(code)
    if not telegram_id: return jsonify({"error": "Invalid or expired code"}), 401

    user = db.find_account_by_telegram(telegram_id)
    if not user:
        user_id = db.create_account({"telegram_id": telegram_id, "display_name": "Telegram User", "auth_providers": ["telegram"]})
    else:
        user_id = user['_id']

    db.link_user_to_app(user_id, app_config['_id'])

    token_payload = {"sub": str(user_id), "iss": "bifrost", "aud": client_id, "iat": datetime.now(UTC_TZ), "exp": datetime.now(UTC_TZ).timestamp() + 3600 * 24 * 7}
    encoded_jwt = jwt.encode(token_payload, current_app.config['JWT_SECRET_KEY'], algorithm="HS256")

    return jsonify({"jwt": encoded_jwt, "account_id": str(user_id), "display_name": "Telegram User" if not user else user.get('display_name')})


@auth_api_bp.route('/telegram-login', methods=['POST'])
def telegram_login():
    """Headless/Widget Telegram Login."""
    data = request.json
    client_id = data.get('client_id')
    tg_data = data.get('telegram_data')

    if not client_id or not tg_data: return jsonify({"error": "Missing data"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_config = db.get_app_by_client_id(client_id)
    if not app_config: return jsonify({"error": "Invalid client_id"}), 401

    if not verify_telegram_data(tg_data, app_config.get("telegram_bot_token")):
        return jsonify({"error": "Verification failed"}), 401

    telegram_id = str(tg_data['id'])
    user = db.find_account_by_telegram(telegram_id)

    if not user:
        user_id = db.create_account({"telegram_id": telegram_id, "display_name": tg_data.get('first_name', 'Unknown'), "auth_providers": ["telegram"]})
    else:
        user_id = user['_id']

    db.link_user_to_app(user_id, app_config['_id'])

    token_payload = {"sub": str(user_id), "iss": "bifrost", "aud": client_id, "iat": datetime.now(UTC_TZ), "exp": datetime.now(UTC_TZ).timestamp() + 3600 * 24 * 7}
    encoded_jwt = jwt.encode(token_payload, current_app.config['JWT_SECRET_KEY'], algorithm="HS256")

    return jsonify({"jwt": encoded_jwt, "account_id": str(user_id), "display_name": user.get('display_name') if user else "Telegram User"})