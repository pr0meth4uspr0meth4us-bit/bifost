from flask import Blueprint, render_template, request, redirect, url_for, current_app
from .. import mongo

auth_ui_bp = Blueprint('auth_ui', __name__, url_prefix='/auth/ui')


@auth_ui_bp.route('/login', methods=['GET'])
def login_page():
    """
    Renders the hosted login page.
    """
    client_id = request.args.get('client_id')
    if not client_id:
        return render_template('auth/error.html', error="Missing client_id")

    # Fetch App Config to show Logo/Name
    app_config = mongo.db.applications.find_one({"client_id": client_id})
    if not app_config:
        return render_template('auth/error.html', error="Invalid client_id")

    return render_template(
        'auth/login.html',
        app=app_config,
        # Pass the verify endpoint for the frontend JS to use
        api_base=request.url_root.rstrip('/')
    )

# NOTE: The actual POST /login action is often handled by
# standard API endpoints or a specific UI-handler.
# For Telegram, the Widget on the frontend will POST directly
# to our /auth/api/telegram-login endpoint via fetch().