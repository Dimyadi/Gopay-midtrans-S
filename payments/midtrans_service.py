import hashlib
import time
from datetime import datetime, timedelta
import logging
import midtransclient
from django.conf import settings

logger = logging.getLogger(__name__)

def is_placeholder_key(key: str) -> bool:
    return not key or 'test-key-demo' in key or 'xxxx' in key or len(key) < 15

def get_snap_client():
    return midtransclient.Snap(
        is_production=settings.MIDTRANS_IS_PRODUCTION,
        server_key=settings.MIDTRANS_SERVER_KEY,
        client_key=settings.MIDTRANS_CLIENT_KEY
    )

def get_core_api_client():
    return midtransclient.CoreApi(
        is_production=settings.MIDTRANS_IS_PRODUCTION,
        server_key=settings.MIDTRANS_SERVER_KEY,
        client_key=settings.MIDTRANS_CLIENT_KEY
    )

def verify_signature(order_id, status_code, gross_amount, signature_key, server_key=None):
    """
    Validasi signature_key Midtrans:
    sha512(order_id + status_code + gross_amount + server_key)
    """
    if not server_key:
        server_key = settings.MIDTRANS_SERVER_KEY
    
    # Gross amount standard format (e.g. 10000.00 or 10000)
    raw_str = f"{order_id}{status_code}{gross_amount}{server_key}"
    calculated_hash = hashlib.sha512(raw_str.encode('utf-8')).hexdigest()
    
    is_valid = calculated_hash.lower() == str(signature_key).lower()
    if not is_valid:
        logger.warning(
            f"Signature mismatch! Calculated: {calculated_hash}, Received: {signature_key}, Input: {raw_str}"
        )
    return is_valid

def generate_signature(order_id, status_code, gross_amount, server_key=None):
    """Helper generator for test payloads and webhook simulator"""
    if not server_key:
        server_key = settings.MIDTRANS_SERVER_KEY
    raw_str = f"{order_id}{status_code}{gross_amount}{server_key}"
    return hashlib.sha512(raw_str.encode('utf-8')).hexdigest()

def create_card_snap_token(subscriber, plan, finish_url):
    """
    Generate Snap Token dengan credit_card.save_card: true
    untuk pembayaran pertama & menyimpan card token.
    """
    order_id = f"CARD-INIT-{subscriber.id.hex[:8]}-{int(time.time())}"
    
    if is_placeholder_key(settings.MIDTRANS_SERVER_KEY):
        # Demo / Sandbox simulation mode when real keys not entered
        simulated_token = f"SNAP-SIMULATED-{order_id}"
        simulated_redirect = f"https://app.sandbox.midtrans.com/snap/v2/vtweb/{simulated_token}"
        return {
            "token": simulated_token,
            "redirect_url": simulated_redirect,
            "order_id": order_id,
            "is_simulated": True
        }

    snap = get_snap_client()
    param = {
        "transaction_details": {
            "order_id": order_id,
            "gross_amount": int(plan.amount),
        },
        "credit_card": {
            "secure": True,
            "save_card": True,
        },
        "customer_details": {
            "first_name": subscriber.name,
            "email": subscriber.email,
            "phone": subscriber.phone,
        },
        "callbacks": {
            "finish": finish_url
        }
    }
    
    try:
        response = snap.create_transaction(param)
        return {
            "token": response.get("token"),
            "redirect_url": response.get("redirect_url"),
            "order_id": order_id,
            "is_simulated": False
        }
    except Exception as e:
        logger.error(f"Failed to create Snap token: {e}")
        raise e

def create_subscription(subscriber, plan, token_id, payment_type="credit_card"):
    """
    Membuat recurring subscription di Midtrans Core API
    """
    now = datetime.now()
    if plan.interval_unit == 'day':
        start_time = now + timedelta(days=plan.interval)
    elif plan.interval_unit == 'week':
        start_time = now + timedelta(weeks=plan.interval)
    else:
        start_time = now + timedelta(days=30 * plan.interval)
    
    start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S +0700")
    
    if is_placeholder_key(settings.MIDTRANS_SERVER_KEY):
        simulated_sub_id = f"SUB-{payment_type.upper()}-{subscriber.id.hex[:6]}-{int(time.time())}"
        return {
            "id": simulated_sub_id,
            "status": "active",
            "payment_type": payment_type,
            "amount": str(plan.amount),
            "is_simulated": True
        }

    core = get_core_api_client()
    params = {
        "name": f"Sub {plan.name} - {subscriber.name}",
        "amount": str(plan.amount),
        "currency": "IDR",
        "payment_type": payment_type,
        "token": token_id,
        "schedule": {
            "interval": plan.interval,
            "interval_unit": plan.interval_unit,
            "max_interval": 12,
            "start_time": start_time_str
        },
        "metadata": {
            "subscriber_id": str(subscriber.id),
            "subscriber_email": subscriber.email
        },
        "customer_details": {
            "first_name": subscriber.name,
            "email": subscriber.email,
            "phone": subscriber.phone
        }
    }

    if payment_type == "gopay" and subscriber.gopay_account_id:
        params["gopay"] = {
            "account_id": subscriber.gopay_account_id
        }

    try:
        response = core.create_subscription(params)
        return response
    except Exception as e:
        logger.error(f"Midtrans create_subscription error: {e}")
        raise e

def link_gopay_account(subscriber, callback_url):
    """
    Panggil core_api.link_payment_account() untuk GoPay linking
    """
    phone_clean = subscriber.phone.strip().replace(" ", "").replace("-", "")
    if phone_clean.startswith("+62"):
        phone_number = phone_clean[3:]
    elif phone_clean.startswith("62"):
        phone_number = phone_clean[2:]
    elif phone_clean.startswith("0"):
        phone_number = phone_clean[1:]
    else:
        phone_number = phone_clean

    if is_placeholder_key(settings.MIDTRANS_SERVER_KEY):
        simulated_account_id = f"gopay-acc-sim-{subscriber.id.hex[:8]}"
        return {
            "account_id": simulated_account_id,
            "account_status": "PENDING",
            "redirect_url": f"{callback_url}?account_id={simulated_account_id}&status_code=200&simulated=1",
            "is_simulated": True
        }

    core = get_core_api_client()
    params = {
        "payment_type": "gopay",
        "gopay_partner": {
            "phone_number": phone_number,
            "country_code": "62",
            "redirect_url": callback_url
        }
    }

    try:
        response = core.link_payment_account(params)
        account_id = response.get("account_id")
        actions = response.get("actions", [])
        redirect_url = None
        for action in actions:
            if action.get("name") in ["generate-otp", "activation"]:
                redirect_url = action.get("url")
                break
        if not redirect_url and actions:
            redirect_url = actions[0].get("url")

        return {
            "account_id": account_id,
            "account_status": response.get("account_status"),
            "redirect_url": redirect_url or callback_url,
            "raw": response,
            "is_simulated": False
        }
    except Exception as e:
        logger.error(f"Midtrans link_payment_account error: {e}")
        raise e

def get_gopay_account_token(account_id):
    """
    Panggil core_api.get_payment_account(account_id) untuk mengambil token GoPay
    """
    if is_placeholder_key(settings.MIDTRANS_SERVER_KEY):
        return {
            "token": f"gopay-token-sim-{account_id}",
            "account_status": "ENABLED",
            "is_simulated": True
        }

    core = get_core_api_client()
    try:
        response = core.get_payment_account(account_id)
        metadata = response.get("metadata", {})
        payment_options = metadata.get("payment_options", [])
        token = None
        for opt in payment_options:
            if opt.get("token"):
                token = opt.get("token")
                break
        
        return {
            "token": token,
            "account_status": response.get("account_status"),
            "raw": response,
            "is_simulated": False
        }
    except Exception as e:
        logger.error(f"Midtrans get_payment_account error: {e}")
        raise e

def cancel_subscription(subscription_id):
    """
    Disable / Cancel Subscription di Midtrans
    """
    if is_placeholder_key(settings.MIDTRANS_SERVER_KEY):
        return {"status_message": "Subscription successfully disabled (Simulated)"}

    core = get_core_api_client()
    try:
        return core.disable_subscription(subscription_id)
    except Exception as e:
        logger.error(f"Midtrans disable_subscription error: {e}")
        raise e

def disable_subscription(subscription_id):
    return cancel_subscription(subscription_id)

def enable_subscription(subscription_id):
    """
    Enable Subscription di Midtrans
    """
    if is_placeholder_key(settings.MIDTRANS_SERVER_KEY):
        return {"status_message": "Subscription successfully enabled (Simulated)"}

    core = get_core_api_client()
    try:
        return core.enable_subscription(subscription_id)
    except Exception as e:
        logger.error(f"Midtrans enable_subscription error: {e}")
        raise e
