from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from werkzeug.security import check_password_hash
from bson import ObjectId
from . import mongo
from .models import BifrostDB
from .services.email_service import send_invite_email

backoffice_bp = Blueprint('backoffice', __name__, url_prefix='/backoffice')

def get_db():
    return BifrostDB(mongo.cx, current_app.config['DB_NAME'])

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('backoffice_user'):
            return redirect(url_for('backoffice.login'))
        return f(*args, **kwargs)
    return decorated_function

def super_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_super_admin'):
            flash("Super Admin privileges required.", "danger")
            return redirect(url_for('backoffice.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@backoffice_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('email').strip()
        password = request.form.get('password')
        db = get_db()

        # 1. Check Super Admin (God Mode) - Email Only
        super_admin = db.db.admins.find_one({"email": identifier.lower()})
        if super_admin and check_password_hash(super_admin['password_hash'], password):
            session['backoffice_user'] = str(super_admin['_id'])
            session['is_super_admin'] = True
            session['role'] = 'Super Admin'
            return redirect(url_for('backoffice.dashboard'))

        # 2. Check App Admin (Tenant Mode) - Email or Username
        user = db.find_account_by_email(identifier)
        if not user:
            user = db.find_account_by_username(identifier)

        if user and user.get('password_hash') and check_password_hash(user['password_hash'], password):
            # Verify they manage at least one app
            managed_apps = db.get_managed_apps(user['_id'])
            if managed_apps:
                session['backoffice_user'] = str(user['_id'])
                session['is_super_admin'] = False
                session['role'] = 'App Admin'
                return redirect(url_for('backoffice.dashboard'))
            else:
                flash("Access Denied: You are not an administrator for any app.", "danger")
        else:
            flash("Invalid credentials.", "danger")

    return render_template('backoffice/login.html')

@backoffice_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('backoffice.login'))

@backoffice_bp.route('/')
@login_required
def dashboard():
    db = get_db()

    if session.get('is_super_admin'):
        apps = db.get_all_apps()
        title = "Super Admin Dashboard"
    else:
        apps = db.get_managed_apps(session['backoffice_user'])
        title = "Tenant Dashboard"

    return render_template('backoffice/dashboard.html', apps=apps, title=title)

# --- SUPER ADMIN FUNCTIONS ---

@backoffice_bp.route('/apps/create', methods=['GET', 'POST'])
@login_required
@super_admin_required
def create_app():
    if request.method == 'POST':
        db = get_db()
        app_name = request.form.get('app_name')
        callback_url = request.form.get('callback_url')
        api_url = request.form.get('api_url')
        web_url = request.form.get('web_url')
        logo_url = request.form.get('logo_url')
        admin_email = request.form.get('admin_email').strip().lower()

        # 1. Register App
        creds = db.register_application(
            app_name=app_name,
            callback_url=callback_url,
            web_url=web_url,
            api_url=api_url,
            logo_url=logo_url
        )

        # 2. Handle Initial Admin (Invite Flow)
        if admin_email:
            # Need App Object ID (creds only returns secrets strings)
            app_doc = db.get_app_by_client_id(creds['client_id'])
            user = db.find_account_by_email(admin_email)

            if not user:
                # -- INVITE FLOW --
                new_id = db.create_account({
                    "email": admin_email,
                    "display_name": admin_email.split('@')[0],
                    "auth_providers": ["email"]
                })

                # Generate OTP & Send Email
                otp, _ = db.create_otp(admin_email, channel="email")
                login_url = f"{current_app.config['BIFROST_PUBLIC_URL']}/auth/ui/login?client_id={creds['client_id']}"

                send_invite_email(
                    to_email=admin_email,
                    otp=otp,
                    app_name=app_name,
                    login_url=login_url,
                    logo_url=logo_url # Pass the specific app logo
                )

                user_id = new_id
                flash(f"App created & Invite sent to {admin_email}", "success")
            else:
                user_id = user['_id']
                flash(f"App created & {admin_email} linked as Admin", "success")

            # Link User as Admin
            db.link_user_to_app(user_id, app_doc['_id'], role="admin", duration_str="lifetime")
        else:
            flash(f"App created without an admin.", "warning")

        return redirect(url_for('backoffice.dashboard'))

    return render_template('backoffice/create_app.html')

@backoffice_bp.route('/app/<app_id>/rotate-secret', methods=['POST'])
@login_required
@super_admin_required
def rotate_secret(app_id):
    db = get_db()
    new_secret = db.rotate_app_secret(app_id)
    flash(f"SECRET ROTATED! Copy immediately: {new_secret}", "warning")
    return redirect(url_for('backoffice.view_app', app_id=app_id))

# --- APP MANAGEMENT ---

@backoffice_bp.route('/app/<app_id>')
@login_required
def view_app(app_id):
    db = get_db()

    # Security: Ensure Tenant owns this app
    if not session.get('is_super_admin'):
        owned_apps = [str(app['_id']) for app in db.get_managed_apps(session['backoffice_user'])]
        if app_id not in owned_apps:
            flash("Unauthorized access to this app.", "danger")
            return redirect(url_for('backoffice.dashboard'))

    app = db.db.applications.find_one({"_id": ObjectId(app_id)})
    users = db.get_app_users(app_id)

    return render_template('backoffice/app_users.html', app=app, users=users)

@backoffice_bp.route('/app/<app_id>/user/<user_id>/update', methods=['POST'])
@login_required
def update_user_role(app_id, user_id):
    db = get_db()

    # Security Check
    if not session.get('is_super_admin'):
        owned_apps = [str(app['_id']) for app in db.get_managed_apps(session['backoffice_user'])]
        if app_id not in owned_apps:
            return "Unauthorized", 403

    new_role = request.form.get('role')
    duration = request.form.get('duration') # Optional: '1m', '1y' or manual date

    if new_role:
        db.link_user_to_app(user_id, app_id, role=new_role, duration_str=duration)
        flash(f"User updated to {new_role}", "success")

    return redirect(url_for('backoffice.view_app', app_id=app_id))

@backoffice_bp.route('/app/<app_id>/add', methods=['POST'])
@login_required
def add_user_to_app(app_id):
    db = get_db()

    # Security Check
    if not session.get('is_super_admin'):
        owned_apps = [str(app['_id']) for app in db.get_managed_apps(session['backoffice_user'])]
        if app_id not in owned_apps:
            flash("Unauthorized.", "danger")
            return redirect(url_for('backoffice.dashboard'))

    email = request.form.get('email').strip().lower()
    role = request.form.get('role')

    # 1. Find App Details (for email branding)
    app = db.db.applications.find_one({"_id": ObjectId(app_id)})

    # 2. Find or Create User
    user = db.find_account_by_email(email)

    if not user:
        # -- INVITE FLOW --
        new_id = db.create_account({
            "email": email,
            "display_name": email.split('@')[0],
            "auth_providers": ["email"]
        })

        # Generate Code & Send Email
        otp, _ = db.create_otp(email, channel="email")
        login_url = f"{current_app.config['BIFROST_PUBLIC_URL']}/auth/ui/login?client_id={app['client_id']}"

        send_invite_email(
            to_email=email,
            otp=otp,
            app_name=app['app_name'],
            login_url=login_url,
            logo_url=app.get('app_logo_url') # Pass specific app logo
        )

        user_id = new_id
        flash(f"User invited! An email has been sent to {email}.", "success")
    else:
        user_id = user['_id']
        flash(f"Existing user {email} added.", "success")

    # 3. Link them
    db.link_user_to_app(user_id, app_id, role=role, duration_str="lifetime")

    return redirect(url_for('backoffice.view_app', app_id=app_id))