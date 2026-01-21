from flask import Blueprint, render_template, request, redirect, url_for, session, flash, current_app
from werkzeug.security import check_password_hash
from bson import ObjectId
from . import mongo
from .models import BifrostDB

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

@backoffice_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        db = get_db()

        # 1. Check Super Admin (God Mode)
        super_admin = db.db.admins.find_one({"email": email})
        if super_admin and check_password_hash(super_admin['password_hash'], password):
            session['backoffice_user'] = str(super_admin['_id'])
            session['is_super_admin'] = True
            session['role'] = 'Super Admin'
            return redirect(url_for('backoffice.dashboard'))

        # 2. Check App Admin (Tenant Mode)
        user = db.find_account_by_email(email)
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