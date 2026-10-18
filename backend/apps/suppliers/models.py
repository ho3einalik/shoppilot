import uuid
from decimal import Decimal
from django.db import models
from django.conf import settings
from apps.tenancy.models import TenantScopedModel
from apps.catalog.models import ProductVariant
from apps.inventory.models import Warehouse

class PaymentTerms(models.TextChoices):
    CASH = 'CASH', 'نقدی'
    NET_7 = 'NET_7', 'تسویه ۷ روزه'
    NET_15 = 'NET_15', 'تسویه ۱۵ روزه'
    NET_30 = 'NET_30', 'تسویه ۳۰ روزه'
    NET_60 = 'NET_60', 'تسویه ۶۰ روزه'
    CONSIGNMENT = 'CONSIGNMENT', 'امانی'

class Supplier(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="نام تامین‌کننده / شرکت")
    contact_name = models.CharField(max_length=150, blank=True, verbose_name="نام رابط / مسئول فروش")
    phone_number = models.CharField(max_length=50, blank=True, verbose_name="شماره تماس")
    email = models.EmailField(blank=True, null=True, verbose_name="ایمیل")
    address = models.TextField(blank=True, verbose_name="آدرس / نشانی")
    tax_id = models.CharField(max_length=50, blank=True, verbose_name="شناسه ملی / کد اقتصادی")
    lead_time_days = models.PositiveIntegerField(default=3, verbose_name="مدت زمان ارسال سفارش (روز)")
    payment_terms = models.CharField(
        max_length=30,
        choices=PaymentTerms.choices,
        default=PaymentTerms.CASH,
        verbose_name="شرایط تسویه"
    )
    notes = models.TextField(blank=True, verbose_name="یادداشت‌های داخلی")
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = 'تامین‌کننده'
        verbose_name_plural = 'تامین‌کنندگان'
        unique_together = ('store', 'name')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.store.name})"


class PurchaseOrderStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'پیش‌نویس'
    APPROVED = 'APPROVED', 'تأیید شده'
    SENT = 'SENT', 'ارسال شده به تامین‌کننده'
    PARTIALLY_RECEIVED = 'PARTIALLY_RECEIVED', 'رسید ناقص'
    COMPLETED = 'COMPLETED', 'تحویل کامل و بسته شده'
    CANCELLED = 'CANCELLED', 'لغو شده'


class PurchaseOrder(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    po_number = models.CharField(max_length=50, db_index=True, verbose_name="شماره سفارش خرید (PO)")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_orders', verbose_name="تامین‌کننده")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='purchase_orders', verbose_name="انبار مقصد")
    status = models.CharField(
        max_length=30,
        choices=PurchaseOrderStatus.choices,
        default=PurchaseOrderStatus.DRAFT,
        verbose_name="وضعیت سفارش خرید"
    )
    currency = models.CharField(max_length=10, default='IRT', verbose_name="واحد پول")
    total_amount = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="مبلغ کل سفارش")
    expected_delivery_date = models.DateField(blank=True, null=True, verbose_name="تاریخ تحویل پیش‌بینی‌شده")
    notes = models.TextField(blank=True, verbose_name="توضیحات و شرایط خرید")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ثبت‌کننده")

    class Meta:
        verbose_name = 'سفارش خرید (PO)'
        verbose_name_plural = 'سفارشات خرید (PO)'
        unique_together = ('store', 'po_number')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.po_number} - {self.supplier.name} ({self.get_status_display()})"


class PurchaseOrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='purchase_order_items', verbose_name="تنوع کالا")
    quantity_ordered = models.PositiveIntegerField(verbose_name="تعداد سفارش‌داده‌شده")
    quantity_received = models.PositiveIntegerField(default=0, verbose_name="تعداد تحویل‌گرفته‌شده")
    unit_cost = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="قیمت خرید واحد (تومان)")
    total_cost = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="مبلغ کل ردیف")

    class Meta:
        verbose_name = 'ردیف سفارش خرید'
        verbose_name_plural = 'ردیف‌های سفارش خرید'

    @property
    def remaining_quantity(self):
        return max(0, self.quantity_ordered - self.quantity_received)

    @property
    def is_fully_received(self):
        return self.quantity_received >= self.quantity_ordered

    def __str__(self):
        return f"{self.variant.sku} x {self.quantity_ordered} ({self.quantity_received} received)"


class RejectionReason(models.TextChoices):
    DEFECTIVE = 'DEFECTIVE', 'کالای معیوب یا دارای نقص فنی'
    DAMAGED = 'DAMAGED', 'آسیب‌دیده در حین حمل و نقل'
    WRONG_ITEM = 'WRONG_ITEM', 'ارسال کالای اشتباه'
    EXPIRED = 'EXPIRED', 'منقضی شده یا فاسد'
    SPEC_MISMATCH = 'SPEC_MISMATCH', 'عدم انطباق با مشخصات سفارش'
    OTHER = 'OTHER', 'سایر موارد'


class GoodsReceiptInspection(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name='inspections',
        verbose_name="سفارش خرید"
    )
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.PROTECT,
        related_name='goods_inspections',
        verbose_name="تنوع کالا"
    )
    quantity_received = models.PositiveIntegerField(verbose_name="تعداد کل اقلام تحویلی")
    quantity_accepted = models.PositiveIntegerField(verbose_name="تعداد اقلام تاییدشده و وارده به انبار")
    quantity_rejected = models.PositiveIntegerField(default=0, verbose_name="تعداد اقلام مردودشده (غیرقابل ورود به انبار)")
    rejection_reason = models.CharField(
        max_length=30,
        choices=RejectionReason.choices,
        blank=True,
        verbose_name="علت رد اقلام"
    )
    inspection_notes = models.TextField(blank=True, verbose_name="گزارش کارشناسی و بازرسی فنی")
    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="کارشناس کنترل کیفیت"
    )
    inspected_at = models.DateTimeField(auto_now_add=True, verbose_name="زمان بازرسی")

    class Meta:
        verbose_name = 'برگه بازرسی و کنترل کیفیت ورودی انبار'
        verbose_name_plural = 'برگه‌های بازرسی و کنترل کیفیت ورودی انبار'
        ordering = ['-inspected_at']

    def __str__(self):
        return f"بازرسی {self.purchase_order.po_number} - {self.variant.sku}: تایید={self.quantity_accepted}، رد={self.quantity_rejected}"
