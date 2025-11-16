from flask import Flask, jsonify
from flask_pymongo import PyMongo
from config import Config
import datetime
from bson import ObjectId
import json  # <-- Import for the encoder
from flask.json.provider import JSONProvider  # <-- Import for modern Flask

# Globally accessible PyMongo instance
mongo = PyMongo()


# --- Custom JSON Encoder for Flask 2.3+ ---
# This is required to handle ObjectId and datetime objects
# from MongoDB when serializing to JSON, especially for Flask-Admin.

class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON Encoder to handle ObjectId and datetime."""

    def default(self, o):
        if isinstance(o, datetime.datetime):
            return o.isoformat()
        if isinstance(o, ObjectId):
            return str(o)
        # Let the base class default method raise the TypeError
        return super().default(o)


class CustomJSONProvider(JSONProvider):
    """Custom JSON Provider that uses our encoder."""

    def dumps(self, obj, **kwargs):
        # Pass our custom encoder to json.dumps
        return json.dumps(obj, **kwargs, cls=CustomJSONEncoder)

    def loads(self, s, **kwargs):
        return json.loads(s, **kwargs)


# --- End Custom JSON Encoder ---


def create_app(config_class=Config):
    """
    The application factory.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # --- Apply the Custom JSON Provider ---
    # This replaces the old, removed app.json_encoder
    app.json_provider_class = CustomJSONProvider
    app.json = app.json_provider_class(app)
    # ---------------------------------------

    # Initialize extensions
    mongo.init_app(app)

    # --- Create database indexes ---
    with app.app_context():
        from . import models
        models.create_indexes(mongo)

    # --- Register Blueprints ---
    from .auth_ui import auth_ui_bp
    app.register_blueprint(auth_ui_bp, url_prefix='/auth/ui')

    from .auth_api import auth_api_bp
    app.register_blueprint(auth_api_bp, url_prefix='/auth/api')

    from .internal_api import internal_api_bp
    app.register_blueprint(internal_api_bp, url_prefix='/internal')

    # --- Initialize Flask-Admin ---
    from .admin import init_admin
    init_admin(app)

    # --- Health Check Endpoint ---
    @app.route('/health')
    def health():
        """A simple health check endpoint."""
        try:
            mongo.db.command('ping')
            return jsonify(status="ok", message="Bifrost IdP is operational.")
        except Exception as e:
            return jsonify(status="error", message=f"Database connection failed: {e}"), 500

    return app