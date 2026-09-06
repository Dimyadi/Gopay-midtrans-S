import uuid
from django.db import models

class Subscriber(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('credit_card', 'Credit / Debit Card'),
        ('gopay', 'GoPay'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, verbose_name="Nama Lengkap")
    email = models.EmailField(verbose_name="Alamat Email")
    phone = models.CharField(max_length=50, verbose_name="Nomor Telepon/HP")
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHOD_CHOICES, verbose_name="Metode Pembayaran")
    
    midtrans_subscription_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Midtrans Subscription ID"
    )
    midtrans_token = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Midtrans Token (Saved Card Token / GoPay Token)"
    )
    gopay_account_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="GoPay Account ID"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="Status Langganan"
    )
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Dibuat Pada")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Diperbarui Pada")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Subscriber"
        verbose_name_plural = "Subscribers"

    def __str__(self):
        return f"{self.name} ({self.get_payment_method_display()}) - {self.status}"

    @property
    def last_charge_log(self):
        return self.transactionlog_set.order_by('-created_at').first()

    @property
    def last_charge_date(self):
        last_log = self.last_charge_log
        return last_log.created_at if last_log else None

    @property
    def failed_charges_count(self):
        return self.transactionlog_set.filter(
            transaction_status__in=['deny', 'expire', 'cancel', 'failed', 'failure']
        ).count()

    @property
    def successful_charges_count(self):
        return self.transactionlog_set.filter(
            transaction_status__in=['settlement', 'capture']
        ).count()


class SubscriptionPlan(models.Model):
    INTERVAL_UNIT_CHOICES = [
        ('day', 'Hari'),
        ('week', 'Minggu'),
        ('month', 'Bulan'),
    ]

    name = models.CharField(max_length=255, default="Testing Plan - Monthly", verbose_name="Nama Paket")
    amount = models.IntegerField(default=10000, verbose_name="Harga (IDR)")
    interval = models.IntegerField(default=1, verbose_name="Interval")
    interval_unit = models.CharField(
        max_length=20,
        choices=INTERVAL_UNIT_CHOICES,
        default='month',
        verbose_name="Satuan Interval"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Subscription Plan"
        verbose_name_plural = "Subscription Plans"

    def __str__(self):
        return f"{self.name} - Rp {self.amount:,}/{self.interval} {self.get_interval_unit_display()}"


class TransactionLog(models.Model):
    subscriber = models.ForeignKey(
        Subscriber,
        on_delete=models.CASCADE,
        related_name='transactionlog_set',
        verbose_name="Subscriber"
    )
    order_id = models.CharField(max_length=255, verbose_name="Order ID")
    transaction_id = models.CharField(max_length=255, null=True, blank=True, verbose_name="Transaction ID")
    payment_type = models.CharField(max_length=50, verbose_name="Payment Type")
    gross_amount = models.CharField(max_length=50, verbose_name="Gross Amount")
    transaction_status = models.CharField(max_length=50, verbose_name="Transaction Status")
    is_recurring_charge = models.BooleanField(
        default=False,
        verbose_name="Recurring Charge Otomatis?"
    )
    raw_notification = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Raw Notification Payload"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Waktu Transaksi")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Transaction Log"
        verbose_name_plural = "Transaction Logs"

    def __str__(self):
        recurring_tag = " [RECURRING]" if self.is_recurring_charge else " [FIRST]"
        return f"{self.order_id} - {self.transaction_status} ({self.payment_type}){recurring_tag}"
