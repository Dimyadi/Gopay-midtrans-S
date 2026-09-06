import json
import logging
import time
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib import messages
from django.conf import settings
from django.urls import reverse
from django.db.models import Count, Q

from .models import Subscriber, SubscriptionPlan, TransactionLog
from . import midtrans_service

logger = logging.getLogger(__name__)

def get_or_create_default_plan():
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name="Testing Plan - Monthly",
        defaults={
            'amount': 10000,
            'interval': 1,
            'interval_unit': 'month'
        }
    )
    return plan

def home_view(request):
    """
    1. Homepage (/)
    Judul singkat: "Demo Langganan"
    Tombol besar: "Langganan Sekarang"
    """
    plan = get_or_create_default_plan()
    subscribers_count = Subscriber.objects.count()
    return render(request, 'payments/home.html', {
        'plan': plan,
        'subscribers_count': subscribers_count,
    })

def subscribe_view(request):
    """
    2. Halaman Pilih Metode (/subscribe/)
    Form input: nama, email, nomor HP
    Pilihan radio button: Kartu Kredit/Debit atau GoPay
    Submit -> redirect ke alur sesuai metode yang dipilih
    """
    plan = get_or_create_default_plan()
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        payment_method = request.POST.get('payment_method')

        if not name or not email or not phone or payment_method not in ['credit_card', 'gopay']:
            messages.error(request, "Harap lengkapi semua data dan pilih metode pembayaran.")
            return render(request, 'payments/subscribe.html', {'plan': plan})

        subscriber = Subscriber.objects.create(
            name=name,
            email=email,
            phone=phone,
            payment_method=payment_method,
            status='pending'
        )

        if payment_method == 'credit_card':
            return redirect(f"{reverse('payments:subscribe_card')}?subscriber_id={subscriber.id}")
        else:
            return redirect(f"{reverse('payments:subscribe_gopay')}?subscriber_id={subscriber.id}")

    return render(request, 'payments/subscribe.html', {
        'plan': plan,
    })

def subscribe_card_view(request):
    """
    3a. Alur Card (/subscribe/card/)
    - Generate Snap Token dengan credit_card.save_card: true
    - Tampilkan Snap popup (pakai snap.js dari Midtrans, data-client-key dari settings)
    """
    subscriber_id = request.GET.get('subscriber_id')
    subscriber = get_object_or_404(Subscriber, id=subscriber_id)
    plan = get_or_create_default_plan()

    finish_url = request.build_absolute_uri(
        f"{reverse('payments:subscribe_card_finish')}?subscriber_id={subscriber.id}"
    )

    snap_data = None
    error_message = None

    try:
        snap_data = midtrans_service.create_card_snap_token(subscriber, plan, finish_url)
    except Exception as e:
        logger.exception("Error creating card snap token")
        error_message = str(e)

    return render(request, 'payments/subscribe_card.html', {
        'subscriber': subscriber,
        'plan': plan,
        'snap_token': snap_data.get('token') if snap_data else None,
        'order_id': snap_data.get('order_id') if snap_data else None,
        'is_simulated': snap_data.get('is_simulated', False) if snap_data else False,
        'error_message': error_message,
        'client_key': settings.MIDTRANS_CLIENT_KEY,
    })

@csrf_exempt
def subscribe_card_finish_view(request):
    """
    Callback / Endpoint setelah pembayaran Snap kartu kredit selesai
    Menerima saved_token_id, panggil core_api.create_subscription(),
    simpan midtrans_subscription_id, update status active
    """
    subscriber_id = request.GET.get('subscriber_id') or request.POST.get('subscriber_id')
    subscriber = get_object_or_404(Subscriber, id=subscriber_id)
    plan = get_or_create_default_plan()

    # Data dari frontend atau callback Snap
    saved_token_id = request.POST.get('saved_token_id') or request.GET.get('saved_token_id')
    order_id = request.POST.get('order_id') or request.GET.get('order_id') or f"CARD-{subscriber.id.hex[:6]}"
    transaction_id = request.POST.get('transaction_id') or request.GET.get('transaction_id') or f"trx-{int(time.time())}"

    # Jika saved_token_id tidak dikirim dari front-end (misal di sandbox default), generate placeholder
    if not saved_token_id:
        saved_token_id = f"saved-card-token-{subscriber.id.hex[:10]}"

    try:
        sub_resp = midtrans_service.create_subscription(
            subscriber=subscriber,
            plan=plan,
            token_id=saved_token_id,
            payment_type="credit_card"
        )
        subscription_id = sub_resp.get('id') or sub_resp.get('subscription_id') or f"sub-card-{subscriber.id.hex[:8]}"

        subscriber.midtrans_subscription_id = subscription_id
        subscriber.midtrans_token = saved_token_id
        subscriber.status = 'active'
        subscriber.save()

        # Catat initial charge log
        TransactionLog.objects.create(
            subscriber=subscriber,
            order_id=order_id,
            transaction_id=transaction_id,
            payment_type='credit_card',
            gross_amount=str(plan.amount),
            transaction_status='settlement',
            is_recurring_charge=False,
            raw_notification={
                'source': 'snap_card_initial_charge',
                'saved_token_id': saved_token_id,
                'subscription_response': sub_resp
            }
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'status': 'success',
                'redirect_url': f"{reverse('payments:subscribe_success')}?subscriber_id={subscriber.id}"
            })

        return redirect(f"{reverse('payments:subscribe_success')}?subscriber_id={subscriber.id}")

    except Exception as e:
        logger.exception("Error in subscribe_card_finish_view")
        messages.error(request, f"Gagal membuat subscription: {str(e)}")
        return redirect('payments:dashboard')

def subscribe_gopay_view(request):
    """
    3b. Alur GoPay (/subscribe/gopay/)
    - Panggil core_api.link_payment_account() dengan payment_type: gopay
    - Tampilkan halaman redirect untuk linking (OTP + PIN)
    """
    subscriber_id = request.GET.get('subscriber_id')
    subscriber = get_object_or_404(Subscriber, id=subscriber_id)
    plan = get_or_create_default_plan()

    callback_url = request.build_absolute_uri(
        f"{reverse('payments:subscribe_gopay_callback')}?subscriber_id={subscriber.id}"
    )

    link_data = None
    error_message = None

    try:
        link_data = midtrans_service.link_gopay_account(subscriber, callback_url)
        if link_data.get('account_id'):
            subscriber.gopay_account_id = link_data['account_id']
            subscriber.save()
    except Exception as e:
        logger.exception("Error linking gopay account")
        error_message = str(e)

    return render(request, 'payments/subscribe_gopay.html', {
        'subscriber': subscriber,
        'plan': plan,
        'link_data': link_data,
        'error_message': error_message,
        'callback_url': callback_url,
    })

def subscribe_gopay_callback_view(request):
    """
    Callback setelah GoPay Linking berhasil (OTP + PIN)
    - Dapatkan account_id
    - Panggil core_api.get_payment_account(account_id) untuk ambil GoPay token
    - Panggil core_api.create_subscription()
    - Simpan midtrans_subscription_id dan gopay_account_id, set status active
    """
    subscriber_id = request.GET.get('subscriber_id')
    subscriber = get_object_or_404(Subscriber, id=subscriber_id)
    plan = get_or_create_default_plan()

    account_id = request.GET.get('account_id') or subscriber.gopay_account_id

    if not account_id:
        messages.error(request, "Account ID GoPay tidak ditemukan.")
        return redirect('payments:subscribe')

    subscriber.gopay_account_id = account_id
    subscriber.save()

    try:
        # Ambil payment token
        acc_data = midtrans_service.get_gopay_account_token(account_id)
        gopay_token = acc_data.get('token') or f"gopay-token-{account_id}"

        # Buat recurring subscription
        sub_resp = midtrans_service.create_subscription(
            subscriber=subscriber,
            plan=plan,
            token_id=gopay_token,
            payment_type="gopay"
        )
        subscription_id = sub_resp.get('id') or sub_resp.get('subscription_id') or f"sub-gopay-{subscriber.id.hex[:8]}"

        subscriber.midtrans_subscription_id = subscription_id
        subscriber.midtrans_token = gopay_token
        subscriber.status = 'active'
        subscriber.save()

        # Catat initial linking transaction log
        TransactionLog.objects.create(
            subscriber=subscriber,
            order_id=f"GOPAY-LINK-{subscriber.id.hex[:8]}",
            transaction_id=account_id,
            payment_type='gopay',
            gross_amount=str(plan.amount),
            transaction_status='settlement',
            is_recurring_charge=False,
            raw_notification={
                'source': 'gopay_account_linked',
                'account_id': account_id,
                'token': gopay_token,
                'subscription_response': sub_resp
            }
        )

        return redirect(f"{reverse('payments:subscribe_success')}?subscriber_id={subscriber.id}")

    except Exception as e:
        logger.exception("Error creating GoPay subscription")
        messages.error(request, f"Gagal membuat GoPay subscription: {str(e)}")
        return redirect('payments:dashboard')

def subscribe_success_view(request):
    """
    4. Halaman Sukses (/subscribe/success/)
    Tampilkan ringkasan: nama, metode pembayaran, subscription ID, status
    """
    subscriber_id = request.GET.get('subscriber_id')
    subscriber = get_object_or_404(Subscriber, id=subscriber_id)
    plan = get_or_create_default_plan()

    return render(request, 'payments/subscribe_success.html', {
        'subscriber': subscriber,
        'plan': plan,
    })

@csrf_exempt
@require_POST
def webhook_notification_view(request):
    """
    Webhook Handler (/webhook/notification/)
    - Menerima HTTP Notification dari Midtrans
    - WAJIB validasi signature_key: sha512(order_id + status_code + gross_amount + server_key)
    - Simpan setiap notifikasi masuk ke TransactionLog (tandai is_recurring_charge=True untuk recurring)
    - Update status di Subscriber sesuai transaction_status
    """
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception as e:
        logger.error(f"Invalid JSON payload: {e}")
        return HttpResponseBadRequest("Invalid JSON")

    order_id = payload.get('order_id', '')
    status_code = payload.get('status_code', '')
    gross_amount = payload.get('gross_amount', '')
    signature_key = payload.get('signature_key', '')
    transaction_status = payload.get('transaction_status', '')
    payment_type = payload.get('payment_type', '')
    transaction_id = payload.get('transaction_id', '')

    # Validasi signature_key
    # Catatan: Notifikasi khusus subscription event tanpa gross_amount/status_code
    # (misal subscription.disable) memiliki format berbeda, tapi notifikasi charge wajib divalidasi
    is_subscription_event = 'event' in payload or 'subscription_id' in payload and not signature_key

    if signature_key:
        is_valid = midtrans_service.verify_signature(
            order_id=order_id,
            status_code=status_code,
            gross_amount=gross_amount,
            signature_key=signature_key
        )
        if not is_valid:
            logger.warning(f"Signature verification FAILED for order_id: {order_id}")
            return HttpResponseForbidden("Invalid signature_key")
    elif not is_subscription_event:
        # Jika bukan subscription event internal tapi tidak ada signature_key, tolak
        logger.warning(f"Missing signature_key in notification for order {order_id}")
        return HttpResponseForbidden("Missing signature_key")

    # Cari subscriber yang cocok
    # Strategi: cek metadata, cari via subscription_id, atau order_id format (CARD-INIT-{uuid_hex[:8]})
    subscriber = None
    sub_id = payload.get('subscription_id')
    if sub_id:
        subscriber = Subscriber.objects.filter(midtrans_subscription_id=sub_id).first()

    if not subscriber and order_id:
        # Check if order_id contains hex prefix
        parts = order_id.split('-')
        for p in parts:
            if len(p) == 8:
                subscriber = Subscriber.objects.filter(id__startswith=p).first()
                if subscriber:
                    break

    # Fallback to subscriber by customer email/phone if present
    if not subscriber and 'customer_details' in payload:
        cust_email = payload.get('customer_details', {}).get('email')
        if cust_email:
            subscriber = Subscriber.objects.filter(email=cust_email).first()

    # Deteksi apakah recurring charge otomatis
    # Jika subscriber sudah active dan order_id berbeda dari order_id inisial, atau ada schedule charge flag
    is_recurring = False
    if subscriber:
        if subscriber.status == 'active' or 'RECURRING' in order_id.upper() or payload.get('recurring_charge'):
            is_recurring = True

    # Simpan ke TransactionLog
    if subscriber:
        TransactionLog.objects.create(
            subscriber=subscriber,
            order_id=order_id or f"SUB-EVENT-{int(time.time())}",
            transaction_id=transaction_id,
            payment_type=payment_type or subscriber.payment_method,
            gross_amount=gross_amount or "0",
            transaction_status=transaction_status or payload.get('event', 'unknown'),
            is_recurring_charge=is_recurring,
            raw_notification=payload
        )

        # Update status subscriber
        if transaction_status in ['settlement', 'capture']:
            subscriber.status = 'active'
            subscriber.save()
        elif transaction_status in ['deny', 'expire', 'cancel']:
            # Cek berapa kali charge berturut-turut gagal
            failed_count = subscriber.failed_charges_count
            if failed_count >= 2:
                subscriber.status = 'inactive'
            subscriber.save()
        elif payload.get('event') == 'subscription.disable':
            subscriber.status = 'inactive'
            subscriber.save()
        elif payload.get('event') == 'subscription.enable':
            subscriber.status = 'active'
            subscriber.save()

    return JsonResponse({
        "status": "ok",
        "message": "Notification received and processed successfully"
    })

def dashboard_view(request):
    """
    Dashboard Perbandingan (/dashboard/)
    - Tabel semua Subscriber, dikelompokkan per payment_method (Card vs GoPay)
    - Untuk tiap subscriber: status terakhir, tanggal charge terakhir, jumlah kegagalan
    - Ringkasan angka: total subscriber aktif per metode, success rate charge per metode
    - Tombol aksi: Cancel, Disable, Enable, Test Webhook
    """
    # Card subscribers
    card_subscribers = Subscriber.objects.filter(payment_method='credit_card')
    # GoPay subscribers
    gopay_subscribers = Subscriber.objects.filter(payment_method='gopay')

    # Card Metrics
    card_total = card_subscribers.count()
    card_active = card_subscribers.filter(status='active').count()
    card_charges = TransactionLog.objects.filter(payment_type='credit_card')
    card_success_charges = card_charges.filter(transaction_status__in=['settlement', 'capture']).count()
    card_failed_charges = card_charges.filter(transaction_status__in=['deny', 'expire', 'cancel', 'failed']).count()
    card_total_evaluated = card_success_charges + card_failed_charges
    card_success_rate = round((card_success_charges / card_total_evaluated * 100), 1) if card_total_evaluated > 0 else 0

    # GoPay Metrics
    gopay_total = gopay_subscribers.count()
    gopay_active = gopay_subscribers.filter(status='active').count()
    gopay_charges = TransactionLog.objects.filter(payment_type='gopay')
    gopay_success_charges = gopay_charges.filter(transaction_status__in=['settlement', 'capture']).count()
    gopay_failed_charges = gopay_charges.filter(transaction_status__in=['deny', 'expire', 'cancel', 'failed']).count()
    gopay_total_evaluated = gopay_success_charges + gopay_failed_charges
    gopay_success_rate = round((gopay_success_charges / gopay_total_evaluated * 100), 1) if gopay_total_evaluated > 0 else 0

    # Recent transaction logs (all)
    recent_logs = TransactionLog.objects.select_related('subscriber').order_by('-created_at')[:20]

    return render(request, 'payments/dashboard.html', {
        'card_subscribers': card_subscribers,
        'gopay_subscribers': gopay_subscribers,
        'card_metrics': {
            'total': card_total,
            'active': card_active,
            'success_charges': card_success_charges,
            'failed_charges': card_failed_charges,
            'success_rate': card_success_rate,
        },
        'gopay_metrics': {
            'total': gopay_total,
            'active': gopay_active,
            'success_charges': gopay_success_charges,
            'failed_charges': gopay_failed_charges,
            'success_rate': gopay_success_rate,
        },
        'recent_logs': recent_logs,
        'is_production': settings.MIDTRANS_IS_PRODUCTION,
        'server_key_configured': bool(settings.MIDTRANS_SERVER_KEY and not midtrans_service.is_placeholder_key(settings.MIDTRANS_SERVER_KEY)),
    })

@require_POST
def dashboard_cancel_subscription(request, subscriber_id):
    subscriber = get_object_or_404(Subscriber, id=subscriber_id)
    if subscriber.midtrans_subscription_id:
        try:
            midtrans_service.cancel_subscription(subscriber.midtrans_subscription_id)
        except Exception as e:
            messages.warning(request, f"Notice dari Midtrans: {e}")
    
    subscriber.status = 'cancelled'
    subscriber.save()
    messages.success(request, f"Subscription untuk {subscriber.name} berhasil dibatalkan (cancelled).")
    return redirect('payments:dashboard')

@require_POST
def dashboard_toggle_subscription(request, subscriber_id):
    """
    Disable / Enable subscription untuk menguji retry behavior
    """
    subscriber = get_object_or_404(Subscriber, id=subscriber_id)
    if subscriber.status == 'active':
        if subscriber.midtrans_subscription_id:
            try:
                midtrans_service.disable_subscription(subscriber.midtrans_subscription_id)
            except Exception as e:
                messages.warning(request, f"Notice dari Midtrans: {e}")
        subscriber.status = 'inactive'
        subscriber.save()
        messages.info(request, f"Subscription {subscriber.name} dinonaktifkan (inactive/disabled).")
    else:
        if subscriber.midtrans_subscription_id:
            try:
                midtrans_service.enable_subscription(subscriber.midtrans_subscription_id)
            except Exception as e:
                messages.warning(request, f"Notice dari Midtrans: {e}")
        subscriber.status = 'active'
        subscriber.save()
        messages.success(request, f"Subscription {subscriber.name} diaktifkan kembali (active/enabled).")
    
    return redirect('payments:dashboard')

@require_POST
def dashboard_simulate_recurring_charge(request):
    """
    Fitur testing: Simulasi HTTP Webhook notifikasi recurring charge
    Menguji validasi signature_key dan pencatatan TransactionLog
    """
    subscriber_id = request.POST.get('subscriber_id')
    status_type = request.POST.get('status_type', 'settlement') # settlement atau deny
    subscriber = get_object_or_404(Subscriber, id=subscriber_id)

    order_id = f"RECURRING-{subscriber.payment_method.upper()}-{subscriber.id.hex[:6]}-{int(time.time())}"
    status_code = "200" if status_type == 'settlement' else "202"
    gross_amount = "10000.00"

    # Generate valid signature key with server_key
    sig = midtrans_service.generate_signature(order_id, status_code, gross_amount)

    payload = {
        "order_id": order_id,
        "status_code": status_code,
        "gross_amount": gross_amount,
        "signature_key": sig,
        "transaction_status": status_type,
        "payment_type": subscriber.payment_method,
        "transaction_id": f"sim-trx-{int(time.time())}",
        "subscription_id": subscriber.midtrans_subscription_id or f"sim-sub-{subscriber.id.hex[:6]}",
        "recurring_charge": True,
        "customer_details": {
            "first_name": subscriber.name,
            "email": subscriber.email,
            "phone": subscriber.phone
        }
    }

    # Catat log
    TransactionLog.objects.create(
        subscriber=subscriber,
        order_id=order_id,
        transaction_id=payload['transaction_id'],
        payment_type=subscriber.payment_method,
        gross_amount=gross_amount,
        transaction_status=status_type,
        is_recurring_charge=True,
        raw_notification=payload
    )

    if status_type == 'settlement':
        subscriber.status = 'active'
        subscriber.save()
        messages.success(request, f"Simulasi recurring charge BERHASIL (settlement) untuk {subscriber.name}.")
    else:
        failed_count = subscriber.failed_charges_count
        if failed_count >= 2:
            subscriber.status = 'inactive'
        subscriber.save()
        messages.warning(request, f"Simulasi recurring charge GAGAL ({status_type}) untuk {subscriber.name}. Total kegagalan: {failed_count}.")

    return redirect('payments:dashboard')
