import uuid
from django.db import models
from django.conf import settings
from apps.tenancy.models import Store, TenantScopedModel


class SubscriptionTier(models.TextChoices):
    FREE = 'FREE', 'طرح رایگان (Free)'
    STARTER = 'STARTER', 'طرح پایه و استارتر (Starter)'
    PRO = 'PRO', 'طرح حرفه‌ای (Pro)'
    ENTERPRISE = 'ENTERPRISE', 'طرح سازمانی (Enterprise)'


class IntegrationState(models.TextChoices):
    # Core precise lifecycle states
    NOT_CONFIGURED = 'NOT_CONFIGURED', 'هنوز تنظیم نشده'
    CONFIGURED = 'CONFIGURED', 'اطلاعات ذخیره شده، اما اتصال تست نشده'
    TESTING = 'TESTING', 'تست در حال اجرا'
    TEST_FAILED = 'TEST_FAILED', 'تست ناموفق'
    READY = 'READY', 'تست موفق و آماده فعال‌سازی'
    ACTIVE = 'ACTIVE', 'فعال و عملیاتی'
    DISABLED = 'DISABLED', 'غیرفعال'
    REAUTH_REQUIRED = 'REAUTH_REQUIRED', 'نیازمند احراز هویت مجدد'
    ERROR = 'ERROR', 'خطای عملیاتی'

    # Compatibility states with existing modules & tests
    CONNECTED = 'CONNECTED', 'متصل و آماده به کار'
    CONNECTION_TESTED = 'CONNECTION_TESTED', 'اتصال با موفقیت تست شده'
    DISABLED_BY_STORE = 'DISABLED_BY_STORE', 'غیرفعال توسط فروشگاه'
    PLAN_RESTRICTED = 'PLAN_RESTRICTED', 'نیازمند ارتقای اشتراک'
    UNAVAILABLE = 'UNAVAILABLE', 'موقتاً در دسترس نیست'
    NEEDS_REAUTH = 'NEEDS_REAUTH', 'نیازمند اتصال مجدد / انقضای توکن'
    FAILED_RECOVERY = 'FAILED_RECOVERY', 'خطای ارتباط - در انتظار بازیابی'
    MOCKED = 'MOCKED', 'شبیه‌سازی / حالت تستی'
    MANUAL_ONLY = 'MANUAL_ONLY', 'فقط حالت دستی'


class StoreIntegrationConfig(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration_id = models.CharField(max_length=60, db_index=True, verbose_name="شناسه یکتای اتصال")
    status = models.CharField(
        max_length=40,
        choices=IntegrationState.choices,
        default=IntegrationState.NOT_CONFIGURED,
        verbose_name="وضعیت اتصال"
    )
    config_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="تنظیمات رمزنگاری‌شده اتصال"
    )
    is_active = models.BooleanField(default=False, verbose_name="فعال بودن اتصال")
    last_tested_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان آخرین تست")
    last_test_success = models.BooleanField(null=True, blank=True, verbose_name="نتیجه آخرین تست")
    last_test_result = models.JSONField(default=dict, blank=True, verbose_name="جزئیات نتیجه آخرین تست")
    last_test_error = models.TextField(blank=True, verbose_name="پیام خطای آخرین تست")
    last_connected_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان آخرین اتصال موفق")

    class Meta:
        verbose_name = "تنظیمات اتصال خارجی فروشگاه"
        verbose_name_plural = "تنظیمات اتصالات خارجی فروشگاه‌ها"
        unique_together = ('store', 'integration_id')
        ordering = ['integration_id']

    def __str__(self):
        return f"{self.integration_id} - {self.store.name} ({self.status})"



class StoreFeatureSetting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.OneToOneField(
        Store,
        on_delete=models.CASCADE,
        related_name='feature_settings',
        verbose_name="فروشگاه"
    )
    tier = models.CharField(
        max_length=30,
        choices=SubscriptionTier.choices,
        default=SubscriptionTier.FREE,
        verbose_name="سطح اشتراک فروشگاه"
    )
    enabled_features = models.JSONField(
        default=list,
        blank=True,
        verbose_name="ویژگی‌های صراحتاً فعال‌شده"
    )
    disabled_features = models.JSONField(
        default=list,
        blank=True,
        verbose_name="ویژگی‌های صراحتاً غیرفعال‌شده توسط کاربر"
    )
    feature_configs = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="تنظیمات اختصاصی ماژول‌ها"
    )
    integration_states = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="وضعیت اتصالات سرویس‌های خارجی"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیمات ماژول‌ها و ویژگی‌های فروشگاه"
        verbose_name_plural = "تنظیمات ماژول‌های فروشگاه‌ها"

    def __str__(self):
        return f"Feature Settings: {self.store.name} ({self.get_tier_display()})"


class InvoiceStatus(models.TextChoices):
    PENDING = 'PENDING', 'در انتظار پرداخت'
    PAID = 'PAID', 'پرداخت شده'
    FAILED = 'FAILED', 'ناموفق'
    CANCELLED = 'CANCELLED', 'لغو شده'


class BillingCycle(models.TextChoices):
    MONTHLY = 'MONTHLY', 'ماهانه'
    ANNUAL = 'ANNUAL', 'سالانه'


class SubscriptionInvoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='subscription_invoices',
        verbose_name="فروشگاه"
    )
    tier = models.CharField(
        max_length=30,
        choices=SubscriptionTier.choices,
        verbose_name="سطح اشتراک"
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=0,
        verbose_name="مبلغ پرداختی (تومان)"
    )
    billing_cycle = models.CharField(
        max_length=20,
        choices=BillingCycle.choices,
        default=BillingCycle.MONTHLY,
        verbose_name="دوره صورتحساب"
    )
    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.PENDING,
        verbose_name="وضعیت صورتحساب"
    )
    payment_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="شناسه ارجاع پرداخت"
    )
    authority = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="شناسه ارجاع درگاه (Authority)"
    )
    gateway = models.CharField(
        max_length=50,
        default='zarinpal',
        verbose_name="درگاه پرداخت"
    )
    gateway_tracking_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="کد رهگیری درگاه"
    )
    payment_attempt_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="زمان شروع درخواست پرداخت"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="اطلاعات تکمیلی و لاگ تأیید"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "صورتحساب اشتراک"
        verbose_name_plural = "صورتحساب‌های اشتراک"
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice {self.id} - {self.store.name} - {self.tier} ({self.status})"

