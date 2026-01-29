from flask import Flask, jsonify, render_template, current_app
from flask_pymongo import PyMongo
from flask.json.provider import JSONProvider
from flask_cors import CORS
import json
import datetime
import os
import logging
from bson import ObjectId
import markdown
from bifrost.utils.changelog import get_latest_version_info
from urllib.parse import urlparse


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
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
        force=True
    )

    app.json_provider_class = CustomJSONProvider
    app.json = app.json_provider_class(app)

    mongo.init_app(app)

    # --- DYNAMIC CORS CONFIGURATION ---
    # Fetch all registered App URLs to build the whitelist
    with app.app_context():
        try:
            db_name = app.config.get('DB_NAME', 'bifrost_db')
            # Use the raw pymongo client to fetch during startup
            # Note: We use app.config['MONGO_URI'] if accessible or rely on mongo.cx if connected
            db = mongo.cx[db_name]

            allowed_origins = []

            # Fetch all applications
            apps = list(db.applications.find({}, {"app_web_url": 1, "app_callback_url": 1}))

            for application in apps:
                def get_origin(url):
                    if not url: return None
                    parsed = urlparse(url)
                    return f"{parsed.scheme}://{parsed.netloc}"

                web_origin = get_origin(application.get('app_web_url'))
                cb_origin = get_origin(application.get('app_callback_url'))

                if web_origin: allowed_origins.append(web_origin)
                if cb_origin: allowed_origins.append(cb_origin)

            # Deduplicate list
            allowed_origins = list(set(allowed_origins))

            # Fallback for local development if list is empty or strictly dev mode
            if app.debug or not allowed_origins:
                allowed_origins.append("http://localhost:8000")  # Client App port
                allowed_origins.append("http://localhost:5000")  # Bifrost port

            logging.info(f"🛡️ CORS Whitelist initialized with {len(allowed_origins)} origins: {allowed_origins}")

            # Apply CORS with the specific list
            CORS(app, resources={r"/*": {"origins": allowed_origins}}, supports_credentials=True)

        except Exception as e:
            logging.error(f"⚠️ Failed to load CORS whitelist from DB: {e}. Defaulting to safe local fallback.")
            CORS(app, resources={r"/*": {"origins": ["http://localhost:8000"]}})

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
        version, date = get_latest_version_info()
        return render_template('docs.html', version=version, date=date)

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