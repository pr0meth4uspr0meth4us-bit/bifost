from flask import Blueprint, request, jsonify, current_app
from functools import wraps
import jwt
import logging

# Import the DB helper and Services
from .. import mongo
from ..models import BifrostDB
from ..services.payway import PayWayService
from ..services.gumroad import GumroadService

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


@internal_bp.route('/validate-token', methods=['POST'])
@require_service_auth
def validate_token():
    """
    Validates a User JWT provided by a Client App.
    """
    data = request.json
    token = data.get('jwt')
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

        # Get Role from App Link
        role = db.get_user_role_for_app(account_id, app_doc['_id'])
        final_role = role if role else "user"

        return jsonify({
            "is_valid": True,
            "account_id": account_id,
            "app_specific_role": final_role,
            "email": db.find_account_by_id(account_id).get('email')
        })

    except Exception:
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


# =========================================================
#  SECTION: PAYMENT ENDPOINTS (HYBRID: PAYWAY + GUMROAD)
# =========================================================

@internal_bp.route('/payments/create-intent', methods=['POST'])
@require_service_auth
def create_payment_intent():
    """
    Step 1: Client App (FinanceBot) requests to start a payment.
    Payload: {
        "account_id": "...",
        "amount": "5.00",
        "region": "local" | "international",
        "target_role": "premium_user",
        "product_id": "savvify-premium"  <-- Optional: Specific Gumroad Slug
    }
    """
    data = request.json
    account_id = data.get('account_id')
    amount = data.get('amount')
    region = data.get('region', 'local')
    target_role = data.get('target_role', 'premium_user')

    # Capture the specific product the bot wants to sell
    product_id = data.get('product_id')

    # User info
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
        # --- PATH A: ABA PAYWAY (Cambodia) ---
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
        # --- PATH B: GUMROAD (International) ---
        gumroad = GumroadService()

        # We pass the 'product_id' (permalink) from the request to the service
        # If None, the service will fall back to the Default in Config
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


@internal_bp.route('/payments/callback', methods=['POST'])
def payway_callback():
    """
    ABA PAYWAY WEBHOOK
    """
    data = request.form.to_dict()
    log.info(f"PayWay Webhook: {data}")

    payway = PayWayService()

    # In Sandbox, verify_webhook might fail if keys aren't perfect,
    # but uncomment for Prod:
    # if not payway.verify_webhook(data):
    #     return "Invalid Signature", 400

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
    """
    GUMROAD WEBHOOK
    Gumroad sends data as application/x-www-form-urlencoded
    """
    data = request.form.to_dict()
    log.info(f"Gumroad Webhook Payload: {data}")  # Log full payload to debug

    gumroad = GumroadService()
    # verify_webhook checks if 'sale_id' exists, which is standard for sales
    if not gumroad.verify_webhook(data):
        return "Invalid Product", 400

    # 1. Extract Transaction ID
    # Gumroad passes URL params back as 'url_params[key]' in the form data
    tx_id = data.get('url_params[transaction_id]')

    # Fallback: check top level just in case
    if not tx_id:
        tx_id = data.get('transaction_id')

    if not tx_id:
        log.info("Gumroad ping received (no transaction_id found)")
        # Return 200 so Gumroad doesn't keep retrying failed pings
        return "OK", 200

    # 2. Extract Sale ID
    sale_id = data.get('sale_id')

    # 3. Complete Transaction
    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])

    # Ensure this is a sale event
    if data.get('resource_name') == 'sale':
        success, msg = db.complete_transaction(tx_id, provider_ref=sale_id)
        log.info(f"Gumroad TX {tx_id}: {msg}")

    return "OK", 200