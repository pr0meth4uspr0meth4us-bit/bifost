from flask import session, redirect, url_for, request, render_template, flash
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.pymongo import ModelView
from wtforms import Form, StringField, PasswordField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Optional, Email
from bson import ObjectId
import datetime

from bifrost import mongo
from bifrost.models import (
    hash_password, check_password,
    generate_client_id, generate_client_secret, hash_client_secret
)


# --- 1. Secure Base Views ---

class SecureAdminIndexView(AdminIndexView):
    """
    Custom Admin Index View that requires login.
    """

    @expose('/')
    def index(self):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return super(SecureAdminIndexView, self).index()


class AuthenticatedModelView(ModelView):
    """
    Custom ModelView that requires login for all CRUD operations.
    """

    def is_accessible(self):
        return session.get('admin_logged_in')

    def inaccessible_callback(self, name, **kwargs):
        flash("You must be logged in as a Super Admin to access this page.", "error")
        return redirect(url_for('admin_login'))


# --- 2. Custom Collection Views ---

class AdminsView(AuthenticatedModelView):
    """
    CRUD view for Super Admins.
    Handles password hashing.
    """
    column_list = ('email', 'role')
    column_searchable_list = ('email',)

    # Define the form for create/edit operations
    def scaffold_form(self):
        class AdminForm(Form):
            email = StringField('Email', validators=[DataRequired(), Email()])
            role = StringField('Role', default='super_admin')
            password = PasswordField('Password', validators=[Optional()])

        return AdminForm

    def on_model_change(self, form, model, is_created):
        # If a password was provided in the form, hash it
        if hasattr(form, 'password') and form.password.data:
            model['password_hash'] = hash_password(form.password.data)

        # Ensure role is always set
        if 'role' not in model or not model['role']:
            model['role'] = 'super_admin'

        # Add timestamp for new records
        if is_created:
            model['created_at'] = datetime.datetime.utcnow()


class AccountsView(AuthenticatedModelView):
    """
    CRUD view for user accounts.
    Handles password hashing for 'email' auth method.
    """
    column_list = ('email', 'phone_number', 'display_name', 'is_active', 'telegram_id', 'google_id')
    column_searchable_list = ('email', 'display_name', 'phone_number')

    def scaffold_form(self):
        class AccountForm(Form):
            email = StringField('Email', validators=[Optional(), Email()])
            phone_number = StringField('Phone Number', validators=[Optional()])
            display_name = StringField('Display Name', validators=[DataRequired()])
            is_active = BooleanField('Is Active', default=True)
            telegram_id = StringField('Telegram ID', validators=[Optional()])
            google_id = StringField('Google ID', validators=[Optional()])
            password = PasswordField('New/Reset Password', validators=[Optional()])

        return AccountForm

    def on_model_change(self, form, model, is_created):
        # If a password was provided, hash it
        if hasattr(form, 'password') and form.password.data:
            model['password_hash'] = hash_password(form.password.data)

        # Ensure 'is_active' has a default
        if 'is_active' not in model:
            model['is_active'] = True

        # Add timestamp for new records
        if is_created:
            model['created_at'] = datetime.datetime.utcnow()


class ApplicationsView(AuthenticatedModelView):
    """
    CRUD view for client applications (the "Link Gateway").
    Handles client_id and client_secret generation.
    """
    column_list = ('app_name', 'client_id', 'app_callback_url', 'allowed_auth_methods')
    column_searchable_list = ('app_name', 'client_id')

    # Don't show the secret hash in lists
    column_exclude_list = ('client_secret_hash',)

    def scaffold_form(self):
        class ApplicationForm(Form):
            app_name = StringField('App Name', validators=[DataRequired()])
            app_logo_url = StringField('App Logo URL', validators=[Optional()])
            app_callback_url = StringField('App Callback URL', validators=[DataRequired()])
            allowed_auth_methods = StringField(
                'Allowed Auth Methods',
                validators=[DataRequired()],
                description='Comma-separated list (e.g., email,google,telegram,phone)'
            )

        return ApplicationForm

    def on_model_change(self, form, model, is_created):
        if is_created:
            # Generate new credentials
            model['client_id'] = generate_client_id()
            raw_secret = generate_client_secret()

            # Hash the secret for database storage
            model['client_secret_hash'] = hash_client_secret(raw_secret)

            # Add timestamp
            model['created_at'] = datetime.datetime.utcnow()

            # Flash the raw secret and snippet to the admin
            flash(f"Application '{model['app_name']}' created successfully.", 'success')
            flash(f"Client ID: {model['client_id']}", 'info')
            flash(
                f"Client Secret: {raw_secret}\n"
                f"*** YOU MUST COPY THIS SECRET NOW. It will not be shown again. ***",
                'warning'
            )
            flash(
                f"Hosted Login URL (Snippet):\n"
                f"{request.host_url}auth/ui/login?client_id={model['client_id']}",
                'info'
            )

        # Convert comma-separated string from form into a list for the DB
        if 'allowed_auth_methods' in model and isinstance(model['allowed_auth_methods'], str):
            model['allowed_auth_methods'] = [
                method.strip() for method in model['allowed_auth_methods'].split(',') if method.strip()
            ]


class AppLinksView(AuthenticatedModelView):
    """
    CRUD view for linking accounts to applications.
    """
    column_list = ('account_id', 'app_id', 'app_specific_role')

    def scaffold_form(self):
        class AppLinkForm(Form):
            account_id = StringField('Account ID (ObjectId)', validators=[DataRequired()])
            app_id = StringField('App ID (ObjectId)', validators=[DataRequired()])
            app_specific_role = StringField('App Specific Role', default='user')

        return AppLinkForm

    def on_model_change(self, form, model, is_created):
        # Convert string IDs to ObjectId
        if 'account_id' in model and isinstance(model['account_id'], str):
            try:
                model['account_id'] = ObjectId(model['account_id'])
            except Exception as e:
                raise ValueError(f"Invalid account_id format: {e}")

        if 'app_id' in model and isinstance(model['app_id'], str):
            try:
                model['app_id'] = ObjectId(model['app_id'])
            except Exception as e:
                raise ValueError(f"Invalid app_id format: {e}")

        # Add timestamp for new records
        if is_created:
            model['created_at'] = datetime.datetime.utcnow()


# --- 3. Initialization and Login Routes ---

def init_admin(app):
    """
    Initializes the Flask-Admin interface and custom login routes.
    """
    admin = Admin(
        app,
        name='Bifrost IdP Admin',
        index_view=SecureAdminIndexView(url='/admin')
    )

    # Add all the views
    admin.add_view(AdminsView(mongo.db.admins, 'Admins'))
    admin.add_view(AccountsView(mongo.db.accounts, 'User Accounts'))
    admin.add_view(ApplicationsView(mongo.db.applications, 'Applications'))
    admin.add_view(AppLinksView(mongo.db.app_links, 'App Links'))

    # --- Custom Admin Login/Logout Routes ---

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')

            admin_user = mongo.db.admins.find_one({"email": email})

            if admin_user and check_password(admin_user.get('password_hash'), password):
                session['admin_logged_in'] = True
                flash("Login successful!", "success")
                return redirect(url_for('admin.index'))
            else:
                flash("Invalid email or password.", "error")

        return render_template('admin/login.html')

    @app.route('/admin/logout')
    def admin_logout():
        session.clear()
        flash("You have been logged out.", "success")
        return redirect(url_for('admin_login'))