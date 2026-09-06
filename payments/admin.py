from django.contrib import admin
from .models import Subscriber, SubscriptionPlan, TransactionLog

@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'payment_method', 'status', 'midtrans_subscription_id', 'created_at')
    list_filter = ('payment_method', 'status', 'created_at')
    search_fields = ('name', 'email', 'phone', 'midtrans_subscription_id')
    readonly_fields = ('id', 'created_at', 'updated_at')

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'interval', 'interval_unit')

@admin.register(TransactionLog)
class TransactionLogAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'subscriber', 'payment_type', 'gross_amount', 'transaction_status', 'is_recurring_charge', 'created_at')
    list_filter = ('payment_type', 'transaction_status', 'is_recurring_charge', 'created_at')
    search_fields = ('order_id', 'transaction_id', 'subscriber__name')
    readonly_fields = ('created_at',)
