import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from apps.tenancy.models import TenantScopedModel
from apps.orders.models import Order

class PaymentMethod(models.TextChoices):
    CARD_TO_CARD = 'CARD_TO_CARD', 'کارت به کارت (فیش بانکی)'
    ONLINE_GATEWAY = 'ONLINE_GATEWAY', 'درگاه پرداخت آنلاین'
    CASH_ON_DELIVERY = 'CASH_ON_DELIVERY', 'پرداخت در محل (COD)'
    POS_TERMINAL = 'POS_TERMINAL', 'دستگاه کارتخوان (POS)'

class PaymentVerificationStatus(models.TextChoices):
    PENDING_VERIFICATION = 'PENDING_VERIFICATION', 'در انتظار بررسی و تأیید'
    VERIFIED = 'VERIFIED', 'تأیید شده'
    REJECTED = 'REJECTED', 'رد شده'
    REFUNDED = 'REFUNDED', 'مسترد شده'
    EXPIRED = 'EXPIRED', 'منقضی شده'

class PaymentTransaction(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments', verbose_name="سفارش")
    method = models.CharField(max_length=30, choices=PaymentMethod.choices, default=PaymentMethod.CARD_TO_CARD, verbose_name="روش پرداخت")
    amount = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="مبلغ تراکنش")
    refunded_amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="مبلغ مسترد شده")
    currency = models.CharField(max_length=10, default='IRT', verbose_name="واحد پول")
    status = models.CharField(max_length=30, choices=PaymentVerificationStatus.choices, default=PaymentVerificationStatus.PENDING_VERIFICATION, verbose_name="وضعیت تأیید")
    
    reference_number = models.CharField(max_length=100, blank=True, verbose_name="شماره پیگیری / ارجاع")
    tracking_code = models.CharField(max_length=100, blank=True, verbose_name="کد رهگیری بانکی")
    payer_card_mask = models.CharField(max_length=20, blank=True, verbose_name="۴ رقم آخر کارت واریزکننده")
    receipt_image_url = models.URLField(max_length=1000, blank=True, verbose_name="تصویر فیش واریزی")
    
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_payments')
    verified_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, verbose_name="دلیل رد فیش")

    class Meta:
        verbose_name = 'تراکنش پرداخت'
        verbose_name_plural = 'تراکنش‌های پرداخت'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['store', 'reference_number'],
                condition=~models.Q(reference_number=''),
                name='unique_store_non_empty_reference_number'
            )
        ]

    def __str__(self):
        return f"{self.amount} {self.currency} for {self.order.order_number} ({self.get_status_display()})"
