from flask import Flask, jsonify
from flask_pymongo import PyMongo
from .models import BifrostDB
from flask.json.provider import JSONProvider
import json
import datetime
from bson import ObjectId

# Globally accessible PyMongo instance
mongo = PyMongo()

# --- Custom JSON Encoder ---
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        if isinstance(o, ObjectId):
            return str(o)
        return super().default(o)

class CustomJSONProvider(JSONProvider):
    def dumps(self, obj, **kwargs):
        return json.dumps(obj, **kwargs, cls=CustomJSONEncoder)
    def loads(self, s, **kwargs):
        return json.loads(s, **kwargs)

def create_app(config_class):
    """The application factory."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Apply Custom JSON Provider
    app.json_provider_class = CustomJSONProvider
    app.json = app.json_provider_class(app)

    # Initialize Mongo
    mongo.init_app(app)

    # --- Fix: Initialize Database Indexes Correctly ---
    # We instantiate the BifrostDB class to trigger index creation
    with app.app_context():
        # Ensure we pass the client and db_name correctly
        db_name = app.config.get('DB_NAME', 'bifrost_db')
        BifrostDB(mongo.cx, db_name)

    # --- Fix: Register Blueprints Correctly ---
    from .auth.ui import auth_ui_bp
    app.register_blueprint(auth_ui_bp) # URL prefix is defined in the blueprint

    from .auth.api import auth_api_bp
    app.register_blueprint(auth_api_bp)

    from .internal.routes import internal_bp
    app.register_blueprint(internal_bp)

    # --- Fix: Initialize Admin Correctly ---
    # Ensure you have created bifrost/admin_panel.py (Code provided in Fix 3 below)
    from .admin_panel import init_admin
    init_admin(app, mongo)

    @app.route('/health')
    def health():
        try:
            mongo.cx.admin.command('ping')
            return jsonify(status="ok", message="Bifrost IdP is operational.")
        except Exception as e:
            return jsonify(status="error", message=f"Database error: {e}"), 500

    return app