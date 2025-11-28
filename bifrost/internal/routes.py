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
    Response: { "is_valid": true, "account_id": "...", "role": "user" }
    """
    data = request.json
    token = data.get('jwt')

    if not token:
        return jsonify({"is_valid": False, "error": "Missing token"}), 400

    try:
        # 1. Verify Signature using Bifrost's Secret
        payload = jwt.decode(
            token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=["HS256"],
            audience=request.authorization.username  # The token must be FOR this client
        )

        return jsonify({
            "is_valid": True,
            "account_id": payload['sub'],
            "role": "user"  # You could fetch app-specific role from DB here
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

    # Generate Code
    code = db.create_login_code(telegram_id)

    return jsonify({"code": code, "expires_in": "10 minutes"})