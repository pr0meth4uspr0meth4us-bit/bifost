from flask import Blueprint, request, jsonify, current_app
from functools import wraps
from datetime import datetime
import jwt
from zoneinfo import ZoneInfo

# Import the DB helper from the main app package
from .. import mongo
from ..models import BifrostDB

internal_bp = Blueprint('internal', __name__, url_prefix='/internal')


def require_service_auth(f):
    """
    Middleware: Ensures the request comes from a valid internal service
    (like FinanceBot) using Client Credentials (Basic Auth).
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return jsonify({"error": "Missing Basic Auth credentials"}), 401

        client_id = auth.username
        client_secret = auth.password

        # Verify the service credentials against the DB
        db = BifrostDB(mongo, current_app.config['DB_NAME'])
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

        # 2. Check Database (Optional but recommended for banning users)
        # You might check if user['is_active'] is True here.

        return jsonify({
            "is_valid": True,
            "account_id": payload['sub'],
            "role": "user"  # You could fetch app-specific role from DB here
        })

    except jwt.ExpiredSignatureError:
        return jsonify({"is_valid": False, "error": "Token expired"}), 401
    except jwt.InvalidTokenError as e:
        return jsonify({"is_valid": False, "error": str(e)}), 401