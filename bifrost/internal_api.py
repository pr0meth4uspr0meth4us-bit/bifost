from flask import Blueprint, request, jsonify, g, current_app, Response
from functools import wraps
from bson import ObjectId

from bifrost import mongo
from bifrost.models import check_client_secret
from bifrost.jwt_utils import decode_jwt

internal_api_bp = Blueprint('internal_api', __name__)


def _challenge():
    """Returns 401 Unauthorized response for Basic Auth."""
    return Response(
        'Could not verify your application credentials.\n'
        'Please login with your client_id and client_secret.', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})


def require_app_auth(f):
    """
    Decorator that implements HTTP Basic Auth for client applications.
    Expects client_id as username and client_secret as password.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return _challenge()

        client_id = auth.username
        client_secret = auth.password

        # Find the application
        application = mongo.db.applications.find_one({"client_id": client_id})

        if not application:
            current_app.logger.warning(f"Internal Auth: Invalid client_id: {client_id}")
            return _challenge()

        # Check the secret
        secret_hash = application.get('client_secret_hash')
        if not secret_hash or not check_client_secret(secret_hash, client_secret):
            current_app.logger.warning(f"Internal Auth: Invalid secret for client_id: {client_id}")
            return _challenge()

        # Store the authenticated application in 'g' for the view to use
        g.application = application
        return f(*args, **kwargs)

    return decorated


@internal_api_bp.route('/validate-token', methods=['POST'])
@require_app_auth
def validate_token():
    """
    Validates a JWT. This endpoint is protected and requires
    the calling service (e.g., FinanceBot) to authenticate itself
    using its client_id and client_secret (via Basic Auth).

    Payload: {"jwt": "..."}
    """
    data = request.get_json()
    if not data or 'jwt' not in data:
        return jsonify({"error": "Missing 'jwt' in payload"}), 400

    token = data.get('jwt')

    # 1. Decode the JWT
    payload = decode_jwt(token)
    if not payload:
        return jsonify({"error": "Invalid or expired token", "is_valid": False}), 401

    # 2. Extract account_id from 'sub' claim
    try:
        account_id = ObjectId(payload.get('sub'))
    except Exception:
        return jsonify({"error": "Invalid token subject (sub)", "is_valid": False}), 401

    # 3. Get the authenticated application (from the decorator)
    application = g.application
    app_id = application['_id']

    # 4. CRITICAL: Check if the account is linked to this app
    link = mongo.db.app_links.find_one({
        "account_id": account_id,
        "app_id": app_id
    })

    if not link:
        # Token is valid, but user is not authorized for *this* app
        msg = "Token is valid, but account is not linked to this application."
        return jsonify({"error": msg, "is_valid": False}), 403

    # 5. All checks passed. Return account details.
    return jsonify({
        "is_valid": True,
        "account_id": str(account_id),
        "app_specific_role": link.get('app_specific_role', 'user')
    })