from flask import Flask, jsonify, render_template, current_app, request, make_response
from flask_pymongo import PyMongo
from flask.json.provider import JSONProvider
# Note: flask_cors is removed in favor of the custom DynamicCorsMiddleware
import json
import datetime
import time
import os
import logging
from bson import ObjectId
import markdown
from urllib.parse import urlparse

# Preserve your custom utility import
try:
    from bifrost.utils.changelog import get_latest_version_info
except ImportError:
    # Fallback if file is missing during dev
    def get_latest_version_info():
        return "v0.0.0", datetime.datetime.now().strftime("%Y-%m-%d")

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


# --- DYNAMIC CORS MIDDLEWARE ---
class DynamicCorsMiddleware:
    def __init__(self, app):
        self.app = app
        self.cache = set()
        self.last_update = 0
        self.cache_ttl = 60  # Cache duration in seconds

    def get_allowed_origins(self):
        """Fetches allowed origins from DB with caching."""
        now = time.time()

        # 1. Return Cache if valid
        if self.cache and (now - self.last_update < self.cache_ttl):
            return self.cache

        # 2. Refresh from DB
        try:
            with self.app.app_context():
                db_name = self.app.config.get('DB_NAME', 'bifrost_db')
                db = mongo.cx[db_name]

                new_origins = set()

                # A. Default Origins (Localhost + Public URL)
                new_origins.add("http://localhost:8000")
                new_origins.add("http://localhost:5000")
                if self.app.config.get('BIFROST_PUBLIC_URL'):
                    new_origins.add(self.app.config['BIFROST_PUBLIC_URL'])

                # B. Fetch Registered Apps
                apps = list(db.applications.find({}, {"app_web_url": 1, "app_callback_url": 1}))

                for application in apps:
                    for field in ['app_web_url', 'app_callback_url']:
                        url = application.get(field)
                        if url:
                            try:
                                parsed = urlparse(url)
                                if parsed.scheme and parsed.netloc:
                                    origin = f"{parsed.scheme}://{parsed.netloc}"
                                    new_origins.add(origin)
                            except:
                                pass

                self.cache = new_origins
                self.last_update = now
                # logging.info(f"🔄 CORS Cache Refreshed: {len(self.cache)} origins")
                return self.cache
        except Exception as e:
            logging.error(f"CORS DB Error: {e}")
            return self.cache  # Return old cache on error

    def attach(self):
        """Attaches request hooks to the Flask app."""

        @self.app.before_request
        def handle_preflight():
            """Handle OPTIONS requests for Preflight checks."""
            if request.method == "OPTIONS":
                origin = request.headers.get('Origin')
                allowed = self.get_allowed_origins()

                if origin in allowed or self.app.debug:
                    response = make_response()
                    response.headers.add("Access-Control-Allow-Origin", origin)
                    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization,X-Requested-With")
                    response.headers.add("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
                    response.headers.add("Access-Control-Allow-Credentials", "true")
                    return response

        @self.app.after_request
        def add_cors_headers(response):
            """Add headers to normal responses."""
            origin = request.headers.get('Origin')
            if not origin:
                return response

            allowed = self.get_allowed_origins()

            if origin in allowed or self.app.debug:
                response.headers.add("Access-Control-Allow-Origin", origin)
                response.headers.add("Access-Control-Allow-Credentials", "true")

            return response


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

    # --- ACTIVATE DYNAMIC CORS ---
    # Replaces static Flask-CORS configuration
    cors = DynamicCorsMiddleware(app)
    cors.attach()

    # --- BLUEPRINTS ---
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
        # Using your custom version info
        version, date = get_latest_version_info()
        return render_template('docs.html', version=version, date=date)

    @app.route('/docs/changelog')
    def changelog_page():
        """Serves the standalone Changelog page."""
        changelog_html = ""
        try:
            # Path to CHANGELOG.md
            changelog_path = os.path.join(app.root_path, '..', 'CHANGELOG.md')
            with open(changelog_path, 'r', encoding='utf-8') as f:
                text = f.read()
                # Parse Markdown to HTML
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