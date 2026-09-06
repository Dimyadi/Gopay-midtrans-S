from django.conf import settings

def midtrans_context(request):
    return {
        'MIDTRANS_CLIENT_KEY': settings.MIDTRANS_CLIENT_KEY,
        'MIDTRANS_SNAP_URL': settings.MIDTRANS_SNAP_URL,
        'MIDTRANS_IS_PRODUCTION': settings.MIDTRANS_IS_PRODUCTION,
    }
