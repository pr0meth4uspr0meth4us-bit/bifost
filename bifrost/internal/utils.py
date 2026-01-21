from functools import wraps
from flask import request, jsonify, current_app
from .. import mongo
from ..models import BifrostDB

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
        db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
        if not db.verify_client_secret(client_id, client_secret):
            return jsonify({"error": "Invalid client_id or secret"}), 401

        # Store the authenticated client_id in the request context for use in routes
        request.authenticated_client_id = client_id

        return f(*args, **kwargs)

    return decorated