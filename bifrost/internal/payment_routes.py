from flask import request, jsonify, current_app
import logging
from .. import mongo
from ..models import BifrostDB
from ..services.payway import PayWayService
from ..services.gumroad import GumroadService
from .utils import require_service_auth
from . import internal_bp

log = logging.getLogger(__name__)

# =========================================================
#  SECTION: PAYMENT ENDPOINTS (SECURE + HYBRID)
# =========================================================

@internal_bp.route('/payments/secure-intent', methods=['POST'])
@require_service_auth
def create_secure_payment_intent():
    """
    ENTERPRISE FLOW: Creates a transaction intent in the DB first.
    Returns a secure Transaction ID that the client uses in the Telegram link.
    """
    data = request.json

    # 1. Validate Inputs
    account_id = data.get('account_id')  # Optional (if known)
    amount = data.get('amount')
    currency = data.get('currency', 'USD')
    target_role = data.get('target_role', 'premium_user')
    duration = data.get('duration', '1m')
    description = data.get('description', 'Subscription Upgrade')
    ref_id = data.get('client_ref_id')

    if not amount or not ref_id:
        return jsonify({"error": "Missing amount or client_ref_id"}), 400

    # 2. Get Authenticated App Context
    client_id = request.authenticated_client_id
    db = BifrostDB(mongo.cx, current_app.config['DB_NAME'])
    app_doc = db.get_app_by_client_id(client_id)

    if not app_doc:
        return jsonify({"error": "App context lost"}), 500

    # 3. Create Transaction Record (Pending)
    tx_id = db.create_transaction(
        account_id=account_id,
        app_id=app_doc['_id'],
        app_name=app_doc.get('app_name', 'Unknown App'), # <--- Pass Name Here
        amount=amount,
        currency=currency,
        description=description,
        target_role=target_role,
        duration=duration,
        ref_id=ref_id
    )

    return jsonify({
        "success": True,
        "transaction_id": tx_id,
        "secure_link": f"https://t.me/bifrost_byhelm_bot?start={tx_id}",
        "manual_command": f"/pay {tx_id}"
    })


@internal_bp.route('/payments/create-intent', methods=['POST'])
@require_service_auth
def create_payment_intent():
    """LEGACY DIRECT GATEWAY (Payway/Gumroad)"""
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
        app_name=app_doc.get('app_name', 'Unknown App'),
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
    """Manually upgrades a user to premium via Telegram ID."""
    data = request.json
    telegram_id = data.get('telegram_id')
    target_client_id = data.get('target_client_id')

    # If no target provided, default to the caller's ID
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
    """Universal Endpoint to claim a payment."""
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