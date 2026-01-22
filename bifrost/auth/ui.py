from flask import Blueprint, render_template, request, redirect, flash, current_app, url_for, session
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
        "role": "user"
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
        identifier = request.form.get('email')
        password = request.form.get('password')

        user = db.find_account_by_email(identifier)
        if not user:
            user = db.find_account_by_username(identifier)

        if user and user.get('password_hash') and check_password_hash(user['password_hash'], password):
            db.link_user_to_app(user['_id'], app_config['_id'])
            token = create_session_token(user, client_id)
            callback_url = app_config.get('app_callback_url')
            separator = '&' if '?' in callback_url else '?'
            return redirect(f"{callback_url}{separator}token={token}")
        else:
            flash("Invalid email or password", "danger")

    return render_template('auth/login.html', app=app_config)

# bifrost/auth/ui.py

@auth_ui_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    client_id = request.args.get('client_id')
    db, app_config = get_app_config(client_id)

    if request.method == 'POST':
        email = request.form.get('email').strip().lower()
        user = db.find_account_by_email(email)
        if user:
            # Create OTP and get a verification session ID [cite: 133, 170]
            otp, ver_id = db.create_otp(email, channel='email', account_id=user['_id'])

            # Construct the link specifically to the OTP verification page
            verify_url = url_for('auth_ui.verify_otp',
                                 verification_id=ver_id,
                                 client_id=client_id,
                                 _external=True)

            send_otp_email(
                to_email=email,
                otp=otp,
                app_name=app_config.get('app_name', 'Bifrost'),
                logo_url=app_config.get('app_logo_url'),
                app_url=verify_url
            )
            # Redirect browser to the verification page immediately
            return redirect(verify_url)

        flash("If an account exists, a reset code has been sent.", "info")
    return render_template('auth/forgot_password.html', app=app_config)

@auth_ui_bp.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    ver_id = request.args.get('verification_id')
    client_id = request.args.get('client_id')
    db, app_config = get_app_config(client_id)

    if request.method == 'POST':
        code = request.form.get('otp')
        record = db.verify_otp(verification_id=ver_id, code=code)
        if record:
            # Generate a temporary proof token for the password reset page
            proof_payload = {
                "email": record['identifier'],
                "scope": "credential_change",
                "exp": datetime.datetime.now(UTC) + datetime.timedelta(minutes=10)
            }
            proof_token = jwt.encode(proof_payload, current_app.config['JWT_SECRET_KEY'], algorithm="HS256")
            return redirect(url_for('auth_ui.reset_password', proof_token=proof_token, client_id=client_id))
        else:
            flash("Invalid or expired code.", "danger")

    return render_template('auth/verify_otp.html', app=app_config, verification_id=ver_id)

@auth_ui_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    proof_token = request.args.get('proof_token')
    client_id = request.args.get('client_id')
    db, app_config = get_app_config(client_id)

    try:
        payload = jwt.decode(proof_token, current_app.config['JWT_SECRET_KEY'], algorithms=["HS256"])
        email = payload['email']
    except:
        flash("Session expired. Please start over.", "danger")
        return redirect(url_for('auth_ui.forgot_password', client_id=client_id))

    if request.method == 'POST':
        new_password = request.form.get('password')
        db.update_password(email, new_password)
        flash("Password updated successfully. Please login.", "success")
        return redirect(url_for('auth_ui.login', client_id=client_id))

    return render_template('auth/reset_password.html', app=app_config, proof_token=proof_token)