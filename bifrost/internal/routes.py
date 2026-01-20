from flask import Blueprint, request, jsonify, current_app
from functools import wraps
import jwt
import logging

# Import the DB helper and Services
from .. import mongo
from ..models import BifrostDB
from ..services.payway import PayWayService
from ..services.gumroad import GumroadService
from ..utils.telegram import verify_telegram_data

internal_bp = Blueprint('internal', __name__, url_prefix='/internal')
log = logging.getLogger(__name__)


def require_service_auth(f):
    """
    Middleware: Ensures the request comes from a valid internal
    service (like FinanceBot) using Client Credentials (Basic Auth).
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not auth.username or not auth.password:
            return jsonify({"error": "Missing Basic Auth credentials"}), 401

        client_id = auth.username
        client_secret = auth.password

        # Verify the service credentials against the DB
        db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
        if not db.verify_client_secret(client_id, client_secret):
            return jsonify({"error": "Invalid client_id or secret"}), 401

        # Store the authenticated client_id in the request context for use in routes
        request.authenticated_client_id = client_id

        return f(*args, **kwargs)

    return decorated


@internal_bp.route('/generate-link-token', methods=['POST'])
@require_service_auth
def generate_link_token():
    """
    Generates a token for the user to click (Web -> Tele flow).
    """
    data = request.json
    account_id = data.get('account_id')

    if not account_id:
        return jsonify({"error": "Missing account_id"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    token = db.create_deep_link_token(account_id)

    return jsonify({"token": token, "expires_in": "10 minutes"})


@internal_bp.route('/link-account', methods=['POST'])
@require_service_auth
def link_account_internal():
    """
    Connects a credential (Email/Pass or Telegram) to an existing account.
    """
    data = request.json
    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    client_id = request.authenticated_client_id
    app_config = db.get_app_by_client_id(client_id)

    # --- MODE 1: Link Email & Password ---
    if data.get('email') and data.get('password') and data.get('account_id'):
        account_id = data['account_id']
        email = data['email']
        password = data['password']

        success, msg = db.link_email_credentials(account_id, email, password)
        if success:
            return jsonify({"success": True, "message": "Email linked successfully", "email": email}), 200
        else:
            return jsonify({"error": msg}), 409

    # --- MODE 2: Link Telegram via Widget Data (Legacy/Widget Flow) ---
    elif data.get('telegram_data') and data.get('account_id'):
        account_id = data['account_id']
        tg_data = data['telegram_data']
        bot_token = app_config.get("telegram_bot_token")

        if not bot_token:
            return jsonify({"error": "Server misconfiguration: No Bot Token found for this app"}), 500

        if not verify_telegram_data(tg_data, bot_token):
            return jsonify({"error": "Invalid Telegram signature"}), 401

        telegram_id = str(tg_data['id'])
        display_name = tg_data.get('first_name', 'Unknown')

        success, msg = db.link_telegram(account_id, telegram_id, display_name)
        if success:
            return jsonify({"success": True, "message": "Telegram linked successfully", "telegram_id": telegram_id}), 200
        else:
            return jsonify({"error": msg}), 409

    # --- MODE 3: Link via Deep Link Token (Bot -> Web User) ---
    elif data.get('link_token') and data.get('telegram_id'):
        token = data['link_token']
        telegram_id = str(data['telegram_id'])

        # 1. Verify Token
        record = db.verify_otp(code=token)
        if not record or record.get('channel') != 'deep_link':
            return jsonify({"error": "Invalid or expired link token"}), 400

        target_account_id = record.get('account_id')

        # 2. Perform Link
        success, msg = db.link_telegram(target_account_id, telegram_id, "Linked via Bot")

        if success:
            return jsonify({
                "success": True,
                "message": "Telegram linked successfully",
                "account_id": target_account_id
            }), 200
        else:
            return jsonify({"error": msg}), 409

    return jsonify({"error": "Invalid payload. Provide email/pass, telegram_data, or link_token"}), 400


@internal_bp.route('/validate-token', methods=['POST'])
@require_service_auth
def validate_token():
    """
    Validates a User JWT provided by a Client App.
    """
    data = request.json
    token = data.get('jwt') or data.get('token')
    client_id = request.authorization.username

    if not token:
        return jsonify({"is_valid": False, "error": "Missing token"}), 400

    try:
        # 1. Verify Signature using Bifrost's Secret
        payload = jwt.decode(
            token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=["HS256"],
            audience=client_id
        )

        account_id = payload['sub']

        # 2. Fetch Actual Role from Database
        db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
        app_doc = db.get_app_by_client_id(client_id)

        if not app_doc:
            return jsonify({"is_valid": False, "error": "App not found"}), 500

        user = db.find_account_by_id(account_id)
        if not user or not user.get('is_active', True):
            return jsonify({"is_valid": False, "error": "User inactive or not found"}), 403

        # Get Role from App Link
        role = db.get_user_role_for_app(account_id, app_doc['_id'])
        final_role = role if role else "user"

        return jsonify({
            "is_valid": True,
            "account_id": account_id,
            "app_specific_role": final_role,
            "email": user.get('email'),
            "username": user.get('username'),
            "display_name": user.get('display_name')
        })

    except Exception as e:
        log.error(f"Token validation failed: {e}")
        return jsonify({"is_valid": False, "error": "Invalid Token"}), 401


@internal_bp.route('/generate-otp', methods=['POST'])
@require_service_auth
def generate_otp():
    """Generates a login code for a specific Telegram ID."""
    data = request.json
    telegram_id = data.get('telegram_id')

    if not telegram_id:
        return jsonify({"error": "Missing telegram_id"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    code = db.create_login_code(telegram_id)

    return jsonify({"code": code, "expires_in": "10 minutes"})


@internal_bp.route('/set-credentials', methods=['POST'])
@require_service_auth
def set_credentials():
    """Sets the password for an email account using a proof token."""
    data = request.json
    email = data.get('email')
    password = data.get('password')
    proof_token = data.get('proof_token')

    if not email or not password or not proof_token:
        return jsonify({"error": "Missing email, password, or proof_token"}), 400

    try:
        payload = jwt.decode(
            proof_token,
            current_app.config['JWT_SECRET_KEY'],
            algorithms=["HS256"]
        )
    except jwt.InvalidTokenError:
        return jsonify({"error": "Invalid proof_token"}), 403

    if payload.get('scope') != 'credential_reset':
        return jsonify({"error": "Invalid token scope"}), 403

    if payload.get('email') != email:
        return jsonify({"error": "Token does not match provided email"}), 403

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    context_account_id = payload.get('account_id')

    if context_account_id:
        success, message = db.link_email_credentials(context_account_id, email, password)
        if success:
            return jsonify({"success": True, "message": "Account linked successfully", "mode": "linked"})
        else:
            return jsonify({"error": message}), 409
    else:
        user = db.find_account_by_email(email)
        if not user:
            db.create_account({
                "email": email,
                "password": password,
                "display_name": "New User",
                "auth_providers": ["email"]
            })
            return jsonify({"success": True, "message": "Account created", "mode": "created"})
        else:
            db.update_password(email, password)
            return jsonify({"success": True, "message": "Credentials updated", "mode": "updated"})


@internal_bp.route('/users/<account_id>/update', methods=['POST'])
@require_service_auth
def update_user_profile(account_id):
    """
    Updates basic user profile information (display_name, email, username).
    Does NOT require a password reset token, but relies on Service Auth.
    """
    data = request.json
    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])

    updates = {}
    if 'display_name' in data:
        updates['display_name'] = data['display_name']
    if 'email' in data:
        updates['email'] = data['email']
    if 'username' in data:
        updates['username'] = data['username']

    if not updates:
        return jsonify({"error": "No fields to update"}), 400

    success, msg = db.update_account_profile(account_id, updates)
    if success:
        return jsonify({"success": True, "message": msg})
    else:
        return jsonify({"error": msg}), 409


@internal_bp.route('/users/<user_id>', methods=['GET'])
@require_service_auth
def get_user_info(user_id):
    """Retrieve public user info for a client service"""
    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    user = db.find_account_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": str(user['_id']),
        "email": user.get('email'),
        "username": user.get('username'),
        "display_name": user.get('display_name')
    }), 200


# =========================================================
#  SECTION: PAYMENT ENDPOINTS (HYBRID: PAYWAY + GUMROAD + MANUAL)
# =========================================================

@internal_bp.route('/payments/create-intent', methods=['POST'])
@require_service_auth
def create_payment_intent():
    data = request.json
    account_id = data.get('account_id')
    amount = data.get('amount')
    region = data.get('region', 'local')
    target_role = data.get('target_role', 'premium_user')
    product_id = data.get('product_id')

    firstname = data.get('firstname', 'Bifrost')
    lastname = data.get('lastname', 'User')
    email = data.get('email', 'user@example.com')
    phone = data.get('phone', '099999999')

    client_id = request.authenticated_client_id

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_doc = db.get_app_by_client_id(client_id)

    if not app_doc:
        return jsonify({"error": "App context lost"}), 500

    # 1. Create Pending Transaction in Bifrost
    tx_id = db.create_transaction(
        account_id=account_id,
        app_id=app_doc['_id'],
        amount=amount,
        currency="USD",
        description=f"Upgrade to {target_role}",
        target_role=target_role
    )

    # 2. ROUTER LOGIC
    if region == 'local':
        payway = PayWayService()
        items = [{"name": target_role, "quantity": "1", "price": amount}]

        result = payway.create_transaction(
            transaction_id=tx_id,
            amount=amount,
            items=items,
            firstname=firstname,
            lastname=lastname,
            email=email,
            phone=phone
        )

        if result:
            return jsonify({
                "success": True,
                "transaction_id": tx_id,
                "provider": "payway",
                "qr_string": result['qr_string'],
                "deeplink": result['deeplink']
            })
        else:
            return jsonify({"error": "Failed to communicate with ABA"}), 502

    else:
        gumroad = GumroadService()
        checkout_url = gumroad.generate_checkout_url(
            transaction_id=tx_id,
            email=email,
            product_permalink=product_id
        )

        if not checkout_url:
            return jsonify({"error": "Missing product configuration"}), 400

        return jsonify({
            "success": True,
            "transaction_id": tx_id,
            "provider": "gumroad",
            "payment_url": checkout_url
        })


@internal_bp.route('/grant-premium', methods=['POST'])
@require_service_auth
def grant_premium_by_admin():
    """
    Manually upgrades a user to premium via Telegram ID.
    Used by the Central Bifrost Bot to approve transfers for specific apps.
    """
    data = request.json
    telegram_id = data.get('telegram_id')
    target_client_id = data.get('target_client_id')

    # If no target provided, default to the caller's ID (legacy support/direct app call)
    caller_client_id = request.authenticated_client_id
    app_client_id = target_client_id if target_client_id else caller_client_id

    if not telegram_id:
        return jsonify({"error": "Missing telegram_id"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_doc = db.get_app_by_client_id(app_client_id)

    if not app_doc:
        return jsonify({"error": f"Target App ({app_client_id}) not found"}), 404

    # Find User
    user = db.find_account_by_telegram(telegram_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Update Role
    db.link_user_to_app(user['_id'], app_doc['_id'], role="premium_user")

    log.info(f"Admin manually granted premium for App '{app_doc.get('app_name')}' to User {telegram_id}")
    return jsonify({"success": True, "message": f"User upgraded to Premium for {app_doc.get('app_name')}"}), 200


@internal_bp.route('/payments/callback', methods=['POST'])
def payway_callback():
    data = request.form.to_dict()
    log.info(f"PayWay Webhook: {data}")

    status = data.get('status')
    tran_id = data.get('tran_id')
    apv = data.get('apv')

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])

    if status == '00':
        success, msg = db.complete_transaction(transaction_id=tran_id, provider_ref=apv)
        log.info(f"PayWay TX {tran_id}: {msg}")

    return "OK", 200


@internal_bp.route('/payments/webhook/gumroad', methods=['POST'])
def gumroad_webhook():
    raw_data = request.form.to_dict()
    print(f"🔔 HIT! Webhook received. Raw Data: {raw_data}", flush=True)

    if raw_data.get('sale_id') == '1234' or raw_data.get('test'):
        print("✅ Gumroad Test Ping confirmed successful.", flush=True)
        return "OK", 200

    tx_id = raw_data.get('url_params[transaction_id]')
    if not tx_id:
        tx_id = raw_data.get('transaction_id')

    if not tx_id:
        print("⚠️ Warning: No transaction_id found in webhook. Ignoring.", flush=True)
        return "OK", 200

    sale_id = raw_data.get('sale_id')
    resource = raw_data.get('resource_name')

    if resource == 'sale' or resource == 'subscription':
        from ..models import BifrostDB
        from .. import mongo
        db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
        success, msg = db.complete_transaction(tx_id, provider_ref=sale_id)
        print(f"💰 Processed Sale {sale_id} for TX {tx_id}: {msg}", flush=True)

    return "OK", 200

@internal_bp.route('/payments/claim', methods=['POST'])
@require_service_auth
def api_claim_payment():
    """
    Universal Endpoint to claim a payment.
    Can be called by Bifrost Bot (Telegram) OR Finance Web (Email).
    Payload:
      - trx_input: "123456"
      - target_app_id: "finance_bot"
      - identity_type: "telegram_id" OR "email"
      - identity_value: "12345" OR "user@example.com"
    """
    data = request.json
    trx_input = data.get('trx_input')
    target_app_id = data.get('target_app_id')
    identity_type = data.get('identity_type')
    identity_value = data.get('identity_value')

    if not trx_input or not target_app_id or not identity_type:
        return jsonify({"error": "Missing parameters"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])

    # Verify the App exists first
    app_doc = db.get_app_by_client_id(target_app_id)
    if not app_doc:
        return jsonify({"error": "Invalid App ID"}), 404

    # Construct Identity Dict
    user_identity = {identity_type: identity_value}

    # Perform Claim
    success, msg = db.claim_payment(trx_input, app_doc['_id'], user_identity)

    if success:
        return jsonify({"success": True, "message": msg}), 200
    else:
        return jsonify({"success": False, "error": msg}), 400

# ... existing imports ...

@internal_bp.route('/get-role', methods=['POST'])
@require_service_auth
def get_user_role_internal():
    """
    Allows a Service (like Finance Bot) to check the role of a Telegram User.
    Input: { "telegram_id": "123456" }
    Output: { "role": "premium_user" }
    """
    data = request.json
    telegram_id = data.get('telegram_id')

    # The app asking (Finance Bot) is identified by Basic Auth
    client_id = request.authenticated_client_id

    if not telegram_id:
        return jsonify({"error": "Missing telegram_id"}), 400

    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])

    # 1. Find the User Account
    user = db.find_account_by_telegram(telegram_id)
    if not user:
        return jsonify({"role": "guest"}), 200 # User not known to Bifrost

    # 2. Find the App ID for the calling service
    app_doc = db.get_app_by_client_id(client_id)
    if not app_doc:
        return jsonify({"error": "Calling App not found"}), 404

    # 3. Get the Role
    role = db.get_user_role_for_app(user['_id'], app_doc['_id'])

    return jsonify({"role": role or "user"}), 200

@internal_bp.route('/me', methods=['GET'])
@require_service_auth
def get_current_user():
    """
    Introspection Endpoint.
    Services can call this with a Bearer token to validate it
    and retrieve user identity without knowing the Secret Key.
    """
    from flask import g
    user = User.find_by_id(g.user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "id": str(user['_id']),
        "email": user.get('email'),
        "telegram_id": user.get('telegram_id'),
        "roles": user.get('roles', []),
        "is_active": True
    }), 200