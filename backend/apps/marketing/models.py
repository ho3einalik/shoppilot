import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from apps.tenancy.models import TenantScopedModel
from apps.orders.models import Customer
from apps.catalog.models import ProductVariant

class DiscountType(models.TextChoices):
    PERCENTAGE = 'PERCENTAGE', 'درصدی (%)'
    FIXED_AMOUNT = 'FIXED_AMOUNT', 'مبلغ ثابت (تومان)'

class Coupon(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, db_index=True, verbose_name="کد تخفیف")
    description = models.CharField(max_length=255, blank=True, verbose_name="عنوان یا مناسبت تخفیف")
    discount_type = models.CharField(
        max_length=20,
        choices=DiscountType.choices,
        default=DiscountType.PERCENTAGE,
        verbose_name="نوع محاسبه تخفیف"
    )
    discount_value = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="مقدار تخفیف (درصد یا تومان)")
    min_order_amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="حداقل مبلغ سفارش")
    max_discount_amount = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True, verbose_name="سقف تخفیف (برای درصدی)")
    start_date = models.DateTimeField(null=True, blank=True, verbose_name="تاریخ شروع اعتبار")
    end_date = models.DateTimeField(null=True, blank=True, verbose_name="تاریخ انقضا")
    max_uses = models.IntegerField(default=0, verbose_name="حداکثر دفعات مجاز استفاده (۰ = نامحدود)")
    uses_count = models.IntegerField(default=0, verbose_name="تعداد دفعات استفاده‌شده")
    is_stackable = models.BooleanField(default=False, verbose_name="امکان ترکیب با سایر کوپن‌ها")
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = 'کد تخفیف'
        verbose_name_plural = 'کدهای تخفیف'
        unique_together = ('store', 'code')
        ordering = ['-created_at']

    def is_valid(self, order_amount=None):
        now = timezone.now()
        if not self.is_active:
            return False, "این کد تخفیف غیرفعال است."
        if self.start_date and now < self.start_date:
            return False, "زمان استفاده از این کد تخفیف هنوز شروع نشده است."
        if self.end_date and now > self.end_date:
            return False, "مهلت استفاده از این کد تخفیف منقضی شده است."
        if self.max_uses > 0 and self.uses_count >= self.max_uses:
            return False, "ظرفیت استفاده از این کد تخفیف تکمیل شده است."
        if order_amount is not None and order_amount < self.min_order_amount:
            return False, f"حداقل مبلغ سفارش برای اعمال این تخفیف {self.min_order_amount:,} تومان است."
        return True, "کد تخفیف معتبر است."

    def calculate_discount(self, order_amount):
        valid, msg = self.is_valid(order_amount)
        if not valid:
            return Decimal('0')
        if self.discount_type == DiscountType.PERCENTAGE:
            calc = (Decimal(str(self.discount_value)) / Decimal('100')) * Decimal(str(order_amount))
            if self.max_discount_amount and calc > self.max_discount_amount:
                return self.max_discount_amount
            return calc
        else:
            return min(Decimal(str(self.discount_value)), Decimal(str(order_amount)))

    def __str__(self):
        return f"{self.code} - {self.get_discount_type_display()} ({self.discount_value})"


class LoyaltyTier(models.TextChoices):
    BRONZE = 'BRONZE', 'سطح برنزی (عادی)'
    SILVER = 'SILVER', 'سطح نقره‌ای (۵٪ تخفیف دائمی)'
    GOLD = 'GOLD', 'سطح طلایی (۱۰٪ تخفیف دائمی)'
    PLATINUM = 'PLATINUM', 'سطح پلاتینیوم VIP (۱۵٪ تخفیف دائمی)'


class CustomerLoyaltyAccount(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, related_name='loyalty_account', verbose_name="مشتری")
    tier = models.CharField(
        max_length=20,
        choices=LoyaltyTier.choices,
        default=LoyaltyTier.BRONZE,
        verbose_name="سطح وفاداری"
    )
    points_balance = models.IntegerField(default=0, verbose_name="موجودی امتیازهای فعال")
    lifetime_points = models.IntegerField(default=0, verbose_name="مجموع امتیازهای کسب‌شده")
    referral_code = models.CharField(max_length=30, blank=True, verbose_name="کد معرف اختصاصی")

    class Meta:
        verbose_name = 'حساب باشگاه مشتریان'
        verbose_name_plural = 'حساب‌های باشگاه مشتریان'

    def __str__(self):
        return f"{self.customer.full_name}: {self.points_balance} امتیاز ({self.get_tier_display()})"


class LoyaltyActionType(models.TextChoices):
    PURCHASE = 'PURCHASE', 'خرید و ثبت سفارش'
    REFERRAL = 'REFERRAL', 'معرفی مشتری جدید'
    REDEMPTION = 'REDEMPTION', 'استفاده از امتیاز برای تخفیف'
    ADMIN_ADJUSTMENT = 'ADMIN_ADJUSTMENT', 'تعدیل دستی توسط مدیر'
    PROMOTION = 'PROMOTION', 'پاداش کمپین ویژه'
    REFUND_REVERSAL = 'REFUND_REVERSAL', 'کسر امتیاز به علت عودت کالا'


class LoyaltyPointsLedger(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(
        CustomerLoyaltyAccount,
        on_delete=models.CASCADE,
        related_name='ledger_entries',
        verbose_name="حساب باشگاه مشتریان"
    )
    points_delta = models.IntegerField(verbose_name="تغییر امتیاز (مثبت یا منفی)")
    action_type = models.CharField(
        max_length=30,
        choices=LoyaltyActionType.choices,
        default=LoyaltyActionType.PURCHASE,
        verbose_name="نوع عملیات"
    )
    order = models.ForeignKey(
        'orders.Order',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loyalty_ledger_entries',
        verbose_name="سفارش مرتبط"
    )
    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="کاربر ثبت‌کننده (در صورت تعدیل دستی)"
    )
    note = models.CharField(max_length=255, blank=True, verbose_name="توضیحات تراکنش امتیاز")

    class Meta:
        verbose_name = 'دفتر کل تراکنش‌های امتیاز وفاداری'
        verbose_name_plural = 'دفتر کل تراکنش‌های امتیازات وفاداری'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.account.customer.full_name}: {self.points_delta:+d} ({self.get_action_type_display()})"


class ProductBundle(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="نام بسته / باندل")
    sku = models.CharField(max_length=100, db_index=True, verbose_name="کد SKU پکیج")
    bundle_price = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="قیمت کل پکیج")
    description = models.TextField(blank=True, verbose_name="توضیحات پکیج تخفیفی")
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = 'بسته ترکیبی (Bundle)'
        verbose_name_plural = 'بسته‌های ترکیبی (Bundles)'
        unique_together = ('store', 'sku')

    def __str__(self):
        return f"باندل {self.name} ({self.bundle_price:,} تومان)"


class ProductBundleItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bundle = models.ForeignKey(ProductBundle, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='bundle_items')
    quantity = models.PositiveIntegerField(default=1, verbose_name="تعداد در هر پکیج")

    class Meta:
        verbose_name = 'آیتم بسته ترکیبی'
        verbose_name_plural = 'آیتم‌های بسته ترکیبی'


class AbandonedCartStatus(models.TextChoices):
    PENDING = 'PENDING', 'رهاشده (در انتظار بازگشت)'
    RECOVERED = 'RECOVERED', 'بازیابی‌شده و خرید موفق'
    EXPIRED = 'EXPIRED', 'منقضی شده'


class RecoveryDeliveryStatus(models.TextChoices):
    NOT_SENT = 'NOT_SENT', 'ارسال نشده'
    SENT = 'SENT', 'ارسال موفق'
    FAILED = 'FAILED', 'خطا در ارسال'
    NOT_CONFIGURED = 'NOT_CONFIGURED', 'درگاه پیامک پیکربندی نشده'
    SIMULATED = 'SIMULATED', 'شبیه‌سازی تستی'


class AbandonedCart(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='abandoned_carts')
    phone_or_email = models.CharField(max_length=150, verbose_name="شماره تماس یا ایمیل مشتری")
    cart_items = models.JSONField(default=list, verbose_name="اقلام سبد خرید")
    total_amount = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="ارزش کل سبد")
    status = models.CharField(max_length=20, choices=AbandonedCartStatus.choices, default=AbandonedCartStatus.PENDING)
    recovery_coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="کوپن تخفیف اختصاصی بازیابی")
    recovery_sms_sent_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان ارسال پیامک یادآوری")
    delivery_status = models.CharField(
        max_length=30,
        choices=RecoveryDeliveryStatus.choices,
        default=RecoveryDeliveryStatus.NOT_SENT,
        verbose_name="وضعیت ارسال پیامک بازیابی"
    )
    recovery_attempts = models.PositiveIntegerField(default=0, verbose_name="تعداد دفعات تلاش برای ارسال")
    last_delivery_error = models.CharField(max_length=255, blank=True, verbose_name="آخرین پیام یا خطای درگاه")
    recovered_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان تکمیل خرید")

    class Meta:
        verbose_name = 'سبد خرید رهاشده'
        verbose_name_plural = 'سبدهای خرید رهاشده'
        ordering = ['-created_at']

    def __str__(self):
        return f"سبد رهاشده {self.phone_or_email} ({self.total_amount:,} تومان) - {self.get_delivery_status_display()}"


class ReferralStatus(models.TextChoices):
    INVITED = 'INVITED', 'دعوت شده'
    CONVERTED = 'CONVERTED', 'خرید موفق معرف'
    CANCELLED = 'CANCELLED', 'لغو شده'


class CustomerReferral(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    referrer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='referrals_made', verbose_name="مشتری معرف")
    referee_phone = models.CharField(max_length=20, verbose_name="شماره تماس دوست معرفی‌شده")
    referred_customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='referred_by_set', verbose_name="مشتری ثبت‌نامی")
    referral_code = models.CharField(max_length=30, verbose_name="کد معرف استفاده‌شده")
    status = models.CharField(max_length=20, choices=ReferralStatus.choices, default=ReferralStatus.INVITED)
    points_awarded = models.IntegerField(default=50, verbose_name="امتیازهای پاداش معرف")

    class Meta:
        verbose_name = 'معرفی مشتری (Referral)'
        verbose_name_plural = 'معرفی‌های مشتریان'
        ordering = ['-created_at']

    def clean(self):
        super().clean()
        if self.referrer and self.referrer.phone_number:
            if self.referrer.phone_number.strip() == self.referee_phone.strip():
                from django.core.exceptions import ValidationError
                raise ValidationError("مشتری نمی‌تواند شماره تماس خود را به عنوان معرف ثبت کند.")

    def __str__(self):
        return f"{self.referrer.full_name} -> {self.referee_phone} ({self.get_status_display()})"


class RecommendationType(models.TextChoices):
    CROSS_SELL = 'CROSS_SELL', 'فروش مکمل (Cross-sell)'
    UPSELL = 'UPSELL', 'فروش نسخه برتر (Upsell)'
    SIMILAR = 'SIMILAR', 'کالای مشابه یا جایگزین'


class ProductRecommendation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='source_recommendations', verbose_name="کالای اصلی")
    recommended_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='target_recommendations', verbose_name="کالای پیشنهادی")
    recommendation_type = models.CharField(max_length=20, choices=RecommendationType.choices, default=RecommendationType.CROSS_SELL)
    discount_incentive_percent = models.IntegerField(default=0, verbose_name="درصد تخفیف تشویقی خرید همزمان")

    class Meta:
        verbose_name = 'پیشنهاد کالای مکمل'
        verbose_name_plural = 'پیشنهادات کالاهای مکمل'
        unique_together = ('store', 'source_variant', 'recommended_variant')

    def __str__(self):
        return f"{self.source_variant.sku} -> {self.recommended_variant.sku} ({self.get_recommendation_type_display()})"


class CampaignAttribution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField('orders.Order', on_delete=models.CASCADE, related_name='campaign_attribution', verbose_name="سفارش")
    campaign = models.ForeignKey('social.SocialCampaign', on_delete=models.SET_NULL, null=True, blank=True, related_name='attributed_orders', verbose_name="کمپین سوشال")
    utm_source = models.CharField(max_length=100, blank=True, verbose_name="منبع (utm_source)")
    utm_medium = models.CharField(max_length=100, blank=True, verbose_name="رسانه (utm_medium)")
    utm_campaign = models.CharField(max_length=100, blank=True, verbose_name="کمپین (utm_campaign)")
    attributed_revenue = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="درآمد منتسب‌شده")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'انتساب سفارش به کمپین'
        verbose_name_plural = 'انتساب‌های سفارشات به کمپین‌ها'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order.order_number}: {self.utm_source}/{self.utm_campaign} ({self.attributed_revenue:,} تومان)"


class CampaignChannel(models.TextChoices):
    SMS = 'SMS', 'پیامک اطلاع‌رسانی'
    EMAIL = 'EMAIL', 'ایمیل مارکتینگ'


class CampaignStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'پیش‌نویس'
    SCHEDULED = 'SCHEDULED', 'زمان‌بندی شده'
    SENDING = 'SENDING', 'در حال ارسال'
    SENT = 'SENT', 'ارسال شده و پایان‌یافته'
    CANCELLED = 'CANCELLED', 'لغو شده'


class MarketingCampaign(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="نام کمپین بازاریابی")
    target_segment = models.CharField(max_length=50, default='ALL', verbose_name="بخش هدف مشتریان (Segment)")
    channel = models.CharField(
        max_length=20,
        choices=CampaignChannel.choices,
        default=CampaignChannel.SMS,
        verbose_name="کانال ارسال"
    )
    message_template = models.TextField(verbose_name="متن پیام کمپین")
    status = models.CharField(
        max_length=20,
        choices=CampaignStatus.choices,
        default=CampaignStatus.DRAFT,
        verbose_name="وضعیت کمپین"
    )
    recipient_count = models.PositiveIntegerField(default=0, verbose_name="تعداد کل مخاطبان واجد شرایط")
    sent_count = models.PositiveIntegerField(default=0, verbose_name="تعداد پیام‌های ارسال‌شده")
    delivered_count = models.PositiveIntegerField(default=0, verbose_name="تعداد پیام‌های تحویل‌شده")
    failed_count = models.PositiveIntegerField(default=0, verbose_name="تعداد پیام‌های ناموفق")
    attributed_revenue = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="درآمد منتسب‌شده")
    attributed_orders_count = models.PositiveIntegerField(default=0, verbose_name="تعداد سفارشات منتسب‌شده")
    scheduled_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان مقرر ارسال")
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان اتمام ارسال")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'کمپین بازاریابی'
        verbose_name_plural = 'کمپین‌های بازاریابی'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_channel_display()}) - {self.get_status_display()}"

