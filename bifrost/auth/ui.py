from flask import Blueprint, render_template, request, redirect, flash, current_app, url_for
from werkzeug.security import check_password_hash
import jwt
import datetime
from zoneinfo import ZoneInfo
from .. import mongo
from ..models import BifrostDB

auth_ui_bp = Blueprint('auth_ui', __name__, url_prefix='/auth/ui')
UTC = ZoneInfo("UTC")


@auth_ui_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles both rendering the login page (GET) and processing the login (POST).
    """
    client_id = request.args.get('client_id')

    # 1. Validate Client ID
    if not client_id:
        return render_template('auth/error.html', error="Missing client_id")

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_config = db.get_app_by_client_id(client_id)

    if not app_config:
        return render_template('auth/error.html', error="Invalid client_id")

    # 2. Handle Login Submission (POST)
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = db.find_account_by_email(email)

        if user and user.get('password_hash') and check_password_hash(user['password_hash'], password):
            # A. Credentials Valid - Link User to App
            db.link_user_to_app(user['_id'], app_config['_id'])

            # B. Generate Token
            token_payload = {
                "sub": str(user['_id']),
                "iss": "bifrost",
                "aud": client_id,
                "iat": datetime.datetime.now(UTC),
                "exp": datetime.datetime.now(UTC) + datetime.timedelta(days=7),
                "email": user.get('email'),
                "name": user.get('display_name')
            }

            encoded_jwt = jwt.encode(
                token_payload,
                current_app.config['JWT_SECRET_KEY'],
                algorithm="HS256"
            )

            # C. Redirect to Client Callback
            callback_url = app_config.get('app_callback_url')
            if not callback_url:
                flash("Misconfiguration: No callback URL set for this app.", "danger")
            else:
                # Append token to callback URL
                separator = '&' if '?' in callback_url else '?'
                return redirect(f"{callback_url}{separator}token={encoded_jwt}")

        else:
            flash("Invalid email or password", "danger")

    # 3. Render Login Page (GET or failed POST)
    return render_template(
        'auth/login.html',
        app=app_config,
        api_base=request.url_root.rstrip('/')
    )