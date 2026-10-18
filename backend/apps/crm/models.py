import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from apps.tenancy.models import TenantScopedModel
from apps.orders.models import Customer

class CustomerSegment(models.TextChoices):
    CHAMPION = 'CHAMPION', 'مشتری طلایی (Champion)'
    LOYAL = 'LOYAL', 'مشتری وفادار (Loyal)'
    POTENTIAL_LOYALIST = 'POTENTIAL_LOYALIST', 'مشتری مستعد وفاداری'
    NEW = 'NEW', 'مشتری جدید'
    NEED_ATTENTION = 'NEED_ATTENTION', 'نیازمند توجه'
    AT_RISK = 'AT_RISK', 'در خطر ریزش (At Risk)'
    HIBERNATING = 'HIBERNATING', 'غیرفعال و خوابیده'
    LOST = 'LOST', 'از دست رفته'

class InteractionType(models.TextChoices):
    CALL = 'CALL', 'تماس تلفنی'
    WHATSAPP = 'WHATSAPP', 'واتساپ'
    INSTAGRAM_DM = 'INSTAGRAM_DM', 'دایرکت اینستاگرام'
    SMS = 'SMS', 'پیامک'
    IN_PERSON = 'IN_PERSON', 'مراجعه حضوری'
    SUPPORT_TICKET = 'SUPPORT_TICKET', 'تیکت پشتیبانی'
    INTERNAL_NOTE = 'INTERNAL_NOTE', 'یادداشت داخلی تیم'

class CustomerProfile(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='crm_profile', verbose_name="مشتری")
    segment = models.CharField(
        max_length=30,
        choices=CustomerSegment.choices,
        default=CustomerSegment.NEW,
        verbose_name="بخش‌بندی RFM"
    )
    recency_days = models.IntegerField(default=0, verbose_name="تعداد روز از آخرین خرید")
    frequency_orders_count = models.IntegerField(default=0, verbose_name="تعداد کل سفارش‌ها")
    monetary_total_spent = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="ارزش طول عمر مشتری (LTV)")
    average_order_value = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="میانگین مبلغ هر سفارش (AOV)")
    
    tags = models.JSONField(default=list, blank=True, verbose_name="برچسب‌ها (Tags)")
    internal_notes = models.TextField(blank=True, verbose_name="یادداشت‌های محرمانه پشتیبانی")
    preferred_channel = models.CharField(max_length=50, blank=True, default="INSTAGRAM", verbose_name="کانال ارتباطی ترجیحی")
    instagram_handle = models.CharField(max_length=100, blank=True, verbose_name="آیدی اینستاگرام")
    telegram_handle = models.CharField(max_length=100, blank=True, verbose_name="آیدی تلگرام")
    
    refunds_deducted = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="مجموع مبالغ مرجوعی کسرشده")
    segment_reason = models.CharField(max_length=255, blank=True, verbose_name="علت بخش‌بندی RFM")
    last_calculated_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان آخرین محاسبه RFM")
    last_interaction_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان آخرین تعامل")

    class Meta:
        verbose_name = 'پروفایل CRM مشتری'
        verbose_name_plural = 'پروفایل‌های CRM مشتریان'
        ordering = ['-monetary_total_spent']

    def __str__(self):
        return f"CRM: {self.customer.full_name} ({self.get_segment_display()}) - LTV: {self.monetary_total_spent}"


class CustomerInteraction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(CustomerProfile, on_delete=models.CASCADE, related_name='interactions')
    interaction_type = models.CharField(
        max_length=30,
        choices=InteractionType.choices,
        default=InteractionType.INTERNAL_NOTE,
        verbose_name="نوع تعامل"
    )
    summary = models.CharField(max_length=255, verbose_name="خلاصه موضوع")
    details = models.TextField(blank=True, verbose_name="شرح کامل مکالمه / نتیجه")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    follow_up_needed = models.BooleanField(default=False, verbose_name="نیازمند پیگیری بعدی")
    follow_up_date = models.DateField(null=True, blank=True, verbose_name="تاریخ پیگیری")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'سایقه تعامل با مشتری'
        verbose_name_plural = 'سوابق تعاملات مشتریان'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_interaction_type_display()} - {self.summary}"
