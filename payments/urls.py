from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # 1. Homepage
    path('', views.home_view, name='home'),
    
    # 2. Halaman Pilih Metode
    path('subscribe/', views.subscribe_view, name='subscribe'),
    
    # 3a. Alur Card
    path('subscribe/card/', views.subscribe_card_view, name='subscribe_card'),
    path('subscribe/card/finish/', views.subscribe_card_finish_view, name='subscribe_card_finish'),
    
    # 3b. Alur GoPay
    path('subscribe/gopay/', views.subscribe_gopay_view, name='subscribe_gopay'),
    path('subscribe/gopay/callback/', views.subscribe_gopay_callback_view, name='subscribe_gopay_callback'),
    
    # 4. Halaman Sukses
    path('subscribe/success/', views.subscribe_success_view, name='subscribe_success'),
    
    # Webhook Handler
    path('webhook/notification/', views.webhook_notification_view, name='webhook_notification'),
    
    # Dashboard & Actions
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('dashboard/cancel/<uuid:subscriber_id>/', views.dashboard_cancel_subscription, name='dashboard_cancel'),
    path('dashboard/toggle/<uuid:subscriber_id>/', views.dashboard_toggle_subscription, name='dashboard_toggle'),
    path('dashboard/simulate-charge/', views.dashboard_simulate_recurring_charge, name='dashboard_simulate_charge'),
]
