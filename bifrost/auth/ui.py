from flask import Blueprint, render_template, request, redirect, flash, current_app, url_for
from werkzeug.security import check_password_hash
import jwt
import datetime
from zoneinfo import ZoneInfo
from .. import mongo
from ..models import BifrostDB
from ..services.email_service import send_otp_email

auth_ui_bp = Blueprint('auth_ui', __name__, url_prefix='/auth/ui')
UTC = ZoneInfo("UTC")

def get_app_config(client_id):
    """Helper to fetch App configuration and DB instance."""
    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    return db, db.get_app_by_client_id(client_id)

def create_session_token(user, client_id):
    """Helper to generate the JWT for the client app."""
    token_payload = {
        "sub": str(user['_id']),
        "iss": "bifrost",
        "aud": client_id,
        "iat": datetime.datetime.now(UTC),
        "exp": datetime.datetime.now(UTC) + datetime.timedelta(days=7),
        "email": user.get('email'),
        "name": user.get('display_name'),
        "role": "user"  # Default role context (refreshed by API validation later)
    }
    return jwt.encode(
        token_payload,
        current_app.config['JWT_SECRET_KEY'],
        algorithm="HS256"
    )

@auth_ui_bp.route('/login', methods=['GET', 'POST'])
def login():
    client_id = request.args.get('client_id')
    if not client_id:
        return render_template('auth/error.html', error="Missing client_id")

    db, app_config = get_app_config(client_id)
    if not app_config:
        return render_template('auth/error.html', error="Invalid client_id")

    if request.method == 'POST':
        identifier = request.form.get('email') # Can be email or username
        password = request.form.get('password')

        # 1. Try Email
        user = db.find_account_by_email(identifier)
        # 2. Try Username
        if not user:
            user = db.find_account_by_username(identifier)

        if user and user.get('password_hash') and check_password_hash(user['password_hash'], password):
            # Link User to App if not already linked
            db.link_user_to_app(user['_id'], app_config['_id'])

            # Generate Token & Redirect
            token = create_session_token(user, client_id)
            callback_url = app_config.get('app_callback_url')

            separator = '&' if '?' in callback_url else '?'
            return redirect(f"{callback_url}{separator}token={token}")
        else:
            flash("Invalid email or password", "danger")

    return render_template('auth/login.html', app=app_config, api_base=request.url_root.rstrip('/'))

@auth_ui_bp.route('/register', methods=['GET', 'POST'])
def register():
    client_id = request.args.get('client_id')
    if not client_id:
        return render_template('auth/error.html', error="Missing client_id")

    db, app_config = get_app_config(client_id)
    if not app_config:
        return render_template('auth/error.html', error="Invalid client_id")

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        display_name = request.form.get('display_name')

        # 1. Check if user exists
        existing_user = db.find_account_by_email(email)
        if existing_user:
            flash("Email already registered. Please login.", "warning")
            return redirect(url_for('auth_ui.login', client_id=client_id))

        # 2. Create Account
        new_account = {
            "email": email,
            "password": password, # db.create_account handles hashing
            "display_name": display_name,
            "auth_providers": ["email"]
        }
        user_id = db.create_account(new_account)

        # 3. Link & Redirect
        db.link_user_to_app(user_id, app_config['_id'])

        # Refetch user to get full object for token
        user = db.find_account_by_id(user_id)
        token = create_session_token(user, client_id)

        callback_url = app_config.get('app_callback_url')
        separator = '&' if '?' in callback_url else '?'
        return redirect(f"{callback_url}{separator}token={token}")

    return render_template('auth/register.html', app=app_config)

@auth_ui_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    client_id = request.args.get('client_id')
    if not client_id:
        return render_template('auth/error.html', error="Missing client_id")

    db, app_config = get_app_config(client_id)
    if not app_config:
        return render_template('auth/error.html', error="Invalid client_id")

    if request.method == 'POST':
        email = request.form.get('email')
        user = db.find_account_by_email(email)

        if user:
            # Generate OTP
            otp, ver_id = db.create_otp(email, channel='email', account_id=user['_id'])

            # Send Email with App Branding (Logo + Name)
            send_otp_email(
                to_email=email,
                otp=otp,
                app_name=app_config.get('app_name', 'Bifrost'),
                logo_url=app_config.get('app_logo_url')  # <--- NEW: Inject App Logo
            )
            flash("If an account exists, a reset code has been sent.", "info")

            # In a real flow, you'd redirect to a verify-otp page here
            # For now, we stay on page or redirect to login
        else:
            # Fake success to prevent enumeration
            flash("If an account exists, a reset code has been sent.", "info")

    return render_template('auth/forgot_password.html', app=app_config)