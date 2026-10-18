import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from apps.tenancy.models import TenantScopedModel, Store
from apps.catalog.models import ProductVariant
from apps.inventory.models import Warehouse

class Customer(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=150, verbose_name="نام و نام خانوادگی مشتری")
    phone_number = models.CharField(max_length=30, db_index=True, verbose_name="شماره تماس")
    email = models.EmailField(blank=True, null=True, verbose_name="ایمیل")
    province = models.CharField(max_length=100, blank=True, verbose_name="استان")
    city = models.CharField(max_length=100, blank=True, verbose_name="شهر")
    postal_code = models.CharField(max_length=20, blank=True, verbose_name="کد پستی")
    address_line = models.TextField(blank=True, verbose_name="نشانی کامل")
    marketing_opt_in = models.BooleanField(default=True, verbose_name="موافقت با دریافت پیام‌های بازاریابی")

    class Meta:
        verbose_name = 'مشتری'
        verbose_name_plural = 'مشتریان'
        unique_together = ('store', 'phone_number')

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"

class OrderChannel(models.TextChoices):
    INSTAGRAM = 'INSTAGRAM', 'اینستاگرام (دایرکت/کامنت)'
    TELEGRAM = 'TELEGRAM', 'تلگرام'
    WHATSAPP = 'WHATSAPP', 'واتساپ'
    WOOCOMMERCE = 'WOOCOMMERCE', 'سایت (ووکامرس)'
    MANUAL = 'MANUAL', 'ثبت دستی / تلفنی'
    POS = 'POS', 'صندوق حضوری (POS)'

class OrderStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'پیش‌نویس'
    PENDING_CONFIRMATION = 'PENDING_CONFIRMATION', 'در انتظار تأیید / پرداخت'
    CONFIRMED = 'CONFIRMED', 'تأیید شده'
    PROCESSING = 'PROCESSING', 'در حال آماده‌سازی و بسته‌بندی'
    PARTIALLY_FULFILLED = 'PARTIALLY_FULFILLED', 'بخشی ارسال شده'
    FULFILLED = 'FULFILLED', 'ارسال شده'
    COMPLETED = 'COMPLETED', 'تحویل شده و تکمیل'
    CANCELLED = 'CANCELLED', 'لغو شده'

class PaymentStatus(models.TextChoices):
    PENDING = 'PENDING', 'در انتظار پرداخت'
    PARTIALLY_PAID = 'PARTIALLY_PAID', 'پرداخت ناقص'
    PAID = 'PAID', 'پرداخت شده'
    REFUNDED = 'REFUNDED', 'مسترد شده'
    FAILED = 'FAILED', 'ناموفق'

class FulfillmentStatus(models.TextChoices):
    UNFULFILLED = 'UNFULFILLED', 'آماده ارسال نشده'
    PARTIALLY_FULFILLED = 'PARTIALLY_FULFILLED', 'ارسال ناقص'
    FULFILLED = 'FULFILLED', 'ارسال کامل'
    RETURNED = 'RETURNED', 'مرجوع شده'

class Order(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=50, db_index=True, verbose_name="شماره سفارش")
    channel = models.CharField(max_length=30, choices=OrderChannel.choices, default=OrderChannel.MANUAL, verbose_name="کانال فروش")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='orders', verbose_name="مشتری")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='orders', verbose_name="انبار مبدا")
    
    order_status = models.CharField(max_length=30, choices=OrderStatus.choices, default=OrderStatus.PENDING_CONFIRMATION, verbose_name="وضعیت سفارش")
    payment_status = models.CharField(max_length=30, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, verbose_name="وضعیت پرداخت")
    fulfillment_status = models.CharField(max_length=30, choices=FulfillmentStatus.choices, default=FulfillmentStatus.UNFULFILLED, verbose_name="وضعیت ارسال")
    
    currency = models.CharField(max_length=10, default='IRT', verbose_name="واحد پول")
    total_items_price = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="مجموع اقلام")
    discount_amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="تخفیف")
    shipping_cost = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="هزینه ارسال")
    tax_amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="مالیات")
    grand_total = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="مبلغ نهایی")
    
    notes = models.TextField(blank=True, verbose_name="یادداشت")
    utm_source = models.CharField(max_length=100, blank=True, verbose_name="منبع تبلیغاتی (UTM Source)")
    utm_medium = models.CharField(max_length=100, blank=True, verbose_name="نوع رسانه (UTM Medium)")
    utm_campaign = models.CharField(max_length=150, blank=True, verbose_name="کمپین (UTM Campaign)")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'سفارش'
        verbose_name_plural = 'سفارش‌ها'
        unique_together = ('store', 'order_number')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_number} - {self.customer.full_name} ({self.get_order_status_display()})"

class OrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='order_items')
    
    variant_sku = models.CharField(max_length=100, verbose_name="کد تنوع کالا در لحظه خرید")
    variant_name = models.CharField(max_length=255, verbose_name="نام تنوع در لحظه خرید")
    quantity = models.PositiveIntegerField(default=1, verbose_name="تعداد")
    unit_price = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="قیمت واحد فروش")
    cost_price_snapshot = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="قیمت تمام‌شده تاریخی (COGS)")
    unit_discount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="تخفیف واحد")
    total_price = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="مبلغ کل ردیف")

    class Meta:
        verbose_name = 'ردیف سفارش'
        verbose_name_plural = 'ردیف‌های سفارش'

    def __str__(self):
        return f"{self.quantity} x {self.variant_sku} in {self.order.order_number}"


class SyncType(models.TextChoices):
    PRODUCTS = 'PRODUCTS', 'همگام‌سازی محصولات'
    ORDERS = 'ORDERS', 'همگام‌سازی سفارشات'
    INVENTORY = 'INVENTORY', 'همگام‌سازی موجودی'
    WEBHOOK = 'WEBHOOK', 'رویداد وب‌هوک'


class SyncStatus(models.TextChoices):
    SUCCESS = 'SUCCESS', 'موفق'
    PARTIAL = 'PARTIAL', 'ناقص'
    FAILED = 'FAILED', 'ناموفق'


class WooCommerceSyncLog(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sync_type = models.CharField(max_length=30, choices=SyncType.choices, verbose_name="نوع همگام‌سازی")
    status = models.CharField(max_length=20, choices=SyncStatus.choices, default=SyncStatus.SUCCESS, verbose_name="وضعیت")
    items_synced = models.PositiveIntegerField(default=0, verbose_name="تعداد رکوردهای همگام‌شده")
    error_details = models.TextField(blank=True, verbose_name="جزئیات خطاهای همگام‌سازی")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'گزارش همگام‌سازی ووکامرس'
        verbose_name_plural = 'گزارش‌های همگام‌سازی ووکامرس'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_sync_type_display()} - {self.get_status_display()} ({self.items_synced} مورد)"
