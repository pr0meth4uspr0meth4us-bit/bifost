from flask import Blueprint, request, jsonify, current_app
from functools import wraps
import jwt

# Import the DB helper from the main app package
from .. import mongo
from ..models import BifrostDB

internal_bp = Blueprint('internal', __name__, url_prefix='/internal')


def require_service_auth(f):
    """
    Middleware: Ensures the request comes from a valid internal
    service (like FinanceBot) using Client Credentials (Basic Auth).
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return jsonify({"error": "Missing Basic Auth credentials"}), 401

        client_id = auth.username
        client_secret = auth.password

        # Verify the service credentials against the DB
        # FIX: Use mongo.cx to get the raw MongoClient, not the PyMongo wrapper
        db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
        if not db.verify_client_secret(client_id, client_secret):
            return jsonify({"error": "Invalid client_id or secret"}), 401

        return f(*args, **kwargs)

    return decorated


@internal_bp.route('/validate-token', methods=['POST'])
@require_service_auth
def validate_token():
    """
    Validates a User JWT provided by a Client App.
    Payload: { "jwt": "..." }
    Response: { "is_valid": true, "account_id": "...", "app_specific_role": "premium_user" }
    """
    data = request.json
    token = data.get('jwt')
    client_id = request.authorization.username  # Authenticated Client ID

    if not token:
        return jsonify({"is_valid": False, "error": "Missing token"}), 400

    try:
        # 1. Verify Signature using Bifrost's Secret
        payload = jwt.decode(
            token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=["HS256"],
            audience=client_id  # The token must be FOR this client
        )

        account_id = payload['sub']

        # 2. Fetch Actual Role from Database
        db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])

        # Get App ID from Client ID
        app_doc = db.get_app_by_client_id(client_id)
        if not app_doc:
            # Should not happen if require_service_auth passed, but safety check
            return jsonify({"is_valid": False, "error": "App not found"}), 500

        # Get Role from App Link
        role = db.get_user_role_for_app(account_id, app_doc['_id'])

        # Default to 'user' if link is missing (e.g. orphan token)
        final_role = role if role else "user"

        return jsonify({
            "is_valid": True,
            "account_id": account_id,
            "app_specific_role": final_role,
            # We can also pass the email if needed by the client app
            "email": db.find_account_by_id(account_id).get('email') if hasattr(db, 'find_account_by_id') else None
        })

    except jwt.ExpiredSignatureError:
        return jsonify({"is_valid": False, "error": "Token expired"}), 401
    except jwt.InvalidTokenError as e:
        return jsonify({"is_valid": False, "error": str(e)}), 401


@internal_bp.route('/generate-otp', methods=['POST'])
@require_service_auth
def generate_otp():
    """
    Generates a login code for a specific Telegram ID.
    Called by the Telegram Bot.
    Payload: { "telegram_id": "12345" }
    """
    data = request.json
    telegram_id = data.get('telegram_id')

    if not telegram_id:
        return jsonify({"error": "Missing telegram_id"}), 400

    # Ensure DB connection
    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])

    # Generate Code (Using legacy wrapper for now)
    code = db.create_login_code(telegram_id)

    return jsonify({"code": code, "expires_in": "10 minutes"})


@internal_bp.route('/set-credentials', methods=['POST'])
@require_service_auth
def set_credentials():
    """
    Sets the password for an email account.
    Requires a valid 'Proof Token' obtained via verify-email-otp.
    Payload: { 
        "email": "...", 
        "password": "...", 
        "proof_token": "..." 
    }
    """
    data = request.json
    email = data.get('email')
    password = data.get('password')
    proof_token = data.get('proof_token')

    if not email or not password or not proof_token:
        return jsonify({"error": "Missing email, password, or proof_token"}), 400

    # 1. Verify Proof Token
    try:
        payload = jwt.decode(
            proof_token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=["HS256"]
        )
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid proof_token"}), 403

    # 2. Validate Token Claims
    if payload.get('scope') != 'credential_reset':
        return jsonify({"error": "Invalid token scope"}), 403

    if payload.get('email') != email:
        return jsonify({"error": "Token does not match provided email"}), 403

    if not payload.get('verified'):
        return jsonify({"error": "Token not verified"}), 403

    # 3. Update Database
    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])

    # Check if user exists, if not, create placeholder
    user = db.find_account_by_email(email)
    if not user:
        db.create_account({
            "email": email,
            "password": password,
            "display_name": "New User",
            "auth_providers": ["email"]
        })
    else:
        db.update_password(email, password)

    return jsonify({"success": True, "message": "Credentials updated"})