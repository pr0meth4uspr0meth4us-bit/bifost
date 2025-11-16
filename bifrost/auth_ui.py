from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, g, abort, current_app, session
)
from bson import ObjectId

from bifrost import mongo
from bifrost.models import hash_password, check_password
from bifrost.jwt_utils import create_jwt

auth_ui_bp = Blueprint('auth_ui', __name__, template_folder='templates')


@auth_ui_bp.before_request
def load_application():
    """
    Runs before every request in this blueprint.
    Validates the ?client_id= query parameter and loads the
    corresponding application config into the Flask 'g' object.
    """
    client_id = request.args.get('client_id')
    if not client_id:
        current_app.logger.warning("Auth UI: Missing client_id in request")
        return abort(400, "Missing client_id parameter.")

    # Find the application configuration
    application = mongo.db.applications.find_one({"client_id": client_id})
    if not application:
        current_app.logger.warning(f"Auth UI: Invalid client_id: {client_id}")
        return abort(404, "Invalid client_id.")

    # Store the app config and client_id for use in the view
    g.app = application
    g.client_id = client_id

    # Store in session for post-login redirects
    session['client_id'] = client_id


@auth_ui_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handles the GET request for the login page and the POST for form submission.
    'g.app' is available from the 'before_request' loader.
    """

    # Check if 'email' auth method is allowed for this app
    if "email" not in g.app.get('allowed_auth_methods', []):
        flash(f"'Email' authentication is not enabled for {g.app['app_name']}.", 'error')
        return render_template('auth/error.html', app=g.app)

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # 1. Find the account
        account = mongo.db.accounts.find_one({"email": email})

        if not account or not check_password(account.get('password_hash'), password):
            flash('Invalid email or password.', 'error')
            return redirect(url_for('.login', client_id=g.client_id))

        if not account.get('is_active', True):
            flash('This account is disabled.', 'error')
            return redirect(url_for('.login', client_id=g.client_id))

        # 2. Check if account is linked to this application
        link = mongo.db.app_links.find_one({
            "account_id": account['_id'],
            "app_id": g.app['_id']
        })

        if not link:
            # This is a critical security check
            current_app.logger.warning(
                f"Login blocked: Account {account['_id']} is not linked to app {g.app['_id']}"
            )
            flash(f"Your account does not have access to {g.app['app_name']}.", 'error')
            return redirect(url_for('.login', client_id=g.client_id))

        # 3. All checks passed. Create JWT and redirect to callback.
        token = create_jwt(account['_id'])
        if not token:
            flash('An error occurred while generating your login token.', 'error')
            return redirect(url_for('.login', client_id=g.client_id))

        callback_url = f"{g.app['app_callback_url']}?token={token}"
        return redirect(callback_url)

    # GET request: Show the login page, branded with app info
    return render_template('auth/login.html', app=g.app)


@auth_ui_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    Handles new user registration.
    """

    # 'g.app' is available from the 'before_request' loader
    client_id = session.get('client_id')
    if not client_id:
        # This can happen if session is lost. Try to get from request.
        client_id = request.args.get('client_id')
        if not client_id:
            return abort(400, "Invalid session or missing client_id.")
        # Re-load g.app if session was lost
        load_application()

    if "email" not in g.app.get('allowed_auth_methods', []):
        flash(f"Registration is not enabled for {g.app['app_name']}.", 'error')
        return render_template('auth/error.html', app=g.app)

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        display_name = request.form.get('display_name')

        # Basic validation
        if not email or not password or not display_name:
            flash('All fields are required.', 'error')
            return redirect(url_for('.register', client_id=client_id))

        # Check if user already exists
        if mongo.db.accounts.find_one({"email": email}):
            flash('An account with this email already exists. Try logging in.', 'warning')
            return redirect(url_for('.login', client_id=client_id))

        # 1. Create the new account
        new_account_data = {
            "email": email,
            "password_hash": hash_password(password),
            "display_name": display_name,
            "is_active": True,
            "created_at": datetime.datetime.utcnow()
        }
        result = mongo.db.accounts.insert_one(new_account_data)
        account_id = result.inserted_id

        # 2. Automatically link the account to the current application
        mongo.db.app_links.insert_one({
            "account_id": account_id,
            "app_id": g.app['_id'],
            "app_specific_role": "user"  # Default role
        })

        # 3. Log the user in by creating a JWT and redirecting
        token = create_jwt(account_id)
        if not token:
            flash('Account created, but failed to log you in. Please try logging in manually.', 'error')
            return redirect(url_for('.login', client_id=client_id))

        callback_url = f"{g.app['app_callback_url']}?token={token}"
        return redirect(callback_url)

    # GET request
    return render_template('auth/register.html', app=g.app)


@auth_ui_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    # We will implement this in a future phase.
    client_id = session.get('client_id', request.args.get('client_id'))
    flash('Password reset is not yet implemented.', 'info')
    return redirect(url_for('.login', client_id=client_id))