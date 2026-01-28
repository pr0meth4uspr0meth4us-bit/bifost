from flask import Flask, jsonify, render_template, current_app
from flask_pymongo import PyMongo
from flask.json.provider import JSONProvider
from flask_cors import CORS
import json
import datetime
import os
import logging
from bson import ObjectId
import markdown  # Added for Changelog parsing

# Globally accessible PyMongo instance
mongo = PyMongo()


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
    app = Flask(__name__)
    app.config.from_object(config_class)

    # --- LOGGING CONFIGURATION ---
    # Enforce the timestamped format requested
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        force=True
    )

    CORS(app, resources={r"/*": {"origins": "*"}})

    app.json_provider_class = CustomJSONProvider
    app.json = app.json_provider_class(app)

    mongo.init_app(app)

    # Initialize Blueprints
    from .auth.ui import auth_ui_bp
    from .auth.api import auth_api_bp
    from .internal.routes import internal_bp
    from .backoffice import backoffice_bp

    app.register_blueprint(auth_ui_bp)
    app.register_blueprint(auth_api_bp)
    app.register_blueprint(internal_bp)
    app.register_blueprint(backoffice_bp)

    from .scheduler import start_scheduler
    if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        start_scheduler(app)

    @app.route('/')
    def index():
        try:
            db_name = current_app.config.get('DB_NAME', 'bifrost_db')
            db = mongo.cx[db_name]
            apps = list(db.applications.find({}))
            return render_template('index.html', apps=apps, app=None)
        except Exception as e:
            return jsonify(status="error", message=f"Portal error: {e}"), 500

    @app.route('/docs')
    def documentation():
        """Serves the Developer Documentation Portal."""
        # No longer loading changelog here
        return render_template('docs.html')

    @app.route('/docs/changelog')
    def changelog_page():
        """Serves the standalone Changelog page."""
        changelog_html = ""
        try:
            # Path to CHANGELOG.md (assuming it's in the project root, one level up from bifrost package)
            changelog_path = os.path.join(app.root_path, '..', 'CHANGELOG.md')
            with open(changelog_path, 'r', encoding='utf-8') as f:
                text = f.read()
                # Parse Markdown to HTML with extensions for cleaner rendering
                changelog_html = markdown.markdown(text, extensions=['fenced_code', 'tables', 'nl2br'])
        except Exception as e:
            logging.error(f"Error reading changelog: {e}")
            changelog_html = "<div class='alert alert-error'><span>Could not load changelog file.</span></div>"

        return render_template('changelog.html', changelog=changelog_html)

    @app.route('/health')
    def health():
        try:
            mongo.cx.admin.command('ping')
            return jsonify(status="ok", message="Bifrost IdP operational.")
        except Exception as e:
            return jsonify(status="error", message=f"Database error: {e}"), 500

    return app