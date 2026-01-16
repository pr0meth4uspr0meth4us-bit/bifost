from flask import Flask, jsonify
from flask_pymongo import PyMongo
from .models import BifrostDB
from flask.json.provider import JSONProvider
import json
import datetime
from bson import ObjectId
from flask_cors import CORS

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

    # --- Enable CORS ---
    # This allows your Next.js frontend to communicate with this Flask backend
    CORS(app, resources={r"/*": {"origins": "*"}})

    # Apply Custom JSON Provider
    app.json_provider_class = CustomJSONProvider
    app.json = app.json_provider_class(app)

    # Initialize Mongo
    mongo.init_app(app)

    # --- Initialize Database Indexes ---
    # We instantiate the BifrostDB class to trigger index creation
    with app.app_context():
        # Ensure we pass the client and db_name correctly
        db_name = app.config.get('DB_NAME', 'bifrost_db')
        # Only initialize if connection is successful to avoid build crashes
        try:
            BifrostDB(mongo.cx, db_name)
        except Exception as e:
            print(f"Warning: Could not connect to DB during init: {e}")

    # --- Register Blueprints ---
    from .auth.ui import auth_ui_bp
    app.register_blueprint(auth_ui_bp)

    from .auth.api import auth_api_bp
    app.register_blueprint(auth_api_bp)

    from .internal.routes import internal_bp
    app.register_blueprint(internal_bp)

    # --- Initialize Admin ---
    from .admin_panel import init_admin
    # Wrap in try/except in case mongo isn't ready
    try:
        init_admin(app, mongo)
    except Exception as e:
        print(f"Warning: Admin panel init skipped: {e}")

    @app.route('/health')
    def health():
        try:
            mongo.cx.admin.command('ping')
            return jsonify(status="ok", message="Bifrost IdP is operational.")
        except Exception as e:
            return jsonify(status="error", message=f"Database error: {e}"), 500

    return app