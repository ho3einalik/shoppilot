import uuid
from django.db import models
from django.conf import settings
from apps.tenancy.models import TenantScopedModel
from apps.catalog.models import ProductVariant

class Warehouse(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, verbose_name="نام انبار")
    code = models.CharField(max_length=50, blank=True, verbose_name="کد انبار")
    address = models.TextField(blank=True, verbose_name="آدرس انبار")
    is_default = models.BooleanField(default=False, verbose_name="انبار پیش‌فرض")
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = 'انبار'
        verbose_name_plural = 'انبارها'
        unique_together = ('store', 'name')

    def __str__(self):
        return f"{self.name} ({self.store.name})"

class InventoryBalance(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='balances')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='balances')
    
    on_hand_quantity = models.IntegerField(default=0, verbose_name="موجودی فیزیکی")
    reserved_quantity = models.IntegerField(default=0, verbose_name="موجودی رزرو شده")
    quarantined_quantity = models.IntegerField(default=0, verbose_name="موجودی قرنطینه/مرجوعی")
    incoming_quantity = models.IntegerField(default=0, verbose_name="موجودی در راه")
    reorder_point = models.IntegerField(default=5, verbose_name="نقطه سفارش مجدد")

    class Meta:
        verbose_name = 'موجودی انبار'
        verbose_name_plural = 'موجودی‌های انبار'
        unique_together = ('warehouse', 'variant')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(on_hand_quantity__gte=0),
                name='inventory_on_hand_non_negative'
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_quantity__gte=0),
                name='inventory_reserved_non_negative'
            ),
            models.CheckConstraint(
                condition=models.Q(quarantined_quantity__gte=0),
                name='inventory_quarantined_non_negative'
            ),
        ]



    @property
    def available(self):
        return max(0, self.on_hand_quantity - self.reserved_quantity - self.quarantined_quantity)

    def __str__(self):
        return f"{self.variant.sku} @ {self.warehouse.name}: {self.available} available ({self.on_hand_quantity} on hand)"

class MovementType(models.TextChoices):
    RECEIPT = 'RECEIPT', 'ورود کالا (رسید)'
    SALE = 'SALE', 'خروج کالا (فروش)'
    RESERVATION = 'RESERVATION', 'رزرو موجودی'
    RESERVATION_RELEASE = 'RESERVATION_RELEASE', 'آزادسازی رزرو'
    ADJUSTMENT = 'ADJUSTMENT', 'تعدیل دستی انبار'
    TRANSFER_IN = 'TRANSFER_IN', 'انتقال ورودی از انبار دیگر'
    TRANSFER_OUT = 'TRANSFER_OUT', 'انتقال خروجی به انبار دیگر'
    RETURN = 'RETURN', 'مرجوعی به انبار'
    DAMAGE = 'DAMAGE', 'ضایعات / خسارت'

class InventoryMovement(TenantScopedModel):
    """Immutable double-entry inventory ledger"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='movements')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=30, choices=MovementType.choices, db_index=True, verbose_name="نوع تراکنش")
    quantity = models.IntegerField(verbose_name="تعداد تغییر (مثبت یا منفی)")
    balance_after = models.IntegerField(verbose_name="موجودی فیزیکی پس از تراکنش")
    reference = models.CharField(max_length=150, blank=True, verbose_name="شماره سند / مرجع (سفارش و غیره)")
    reason = models.CharField(max_length=255, blank=True, verbose_name="دلیل یا شرح")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="کاربر ثبت‌کننده")

    class Meta:
        verbose_name = 'گردش انبار'
        verbose_name_plural = 'گردش‌های انبار'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.movement_type}] {self.quantity} x {self.variant.sku} @ {self.warehouse.name}"


class CycleCountStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'پیش‌نویس انبارگردانی'
    IN_PROGRESS = 'IN_PROGRESS', 'در حال شمارش'
    COMPLETED = 'COMPLETED', 'تطبیق داده شده و نهایی'
    CANCELLED = 'CANCELLED', 'لغو شده'


class StockCycleCount(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='cycle_counts', verbose_name="انبار")
    count_number = models.CharField(max_length=50, db_index=True, verbose_name="شماره انبارگردانی")
    status = models.CharField(max_length=20, choices=CycleCountStatus.choices, default=CycleCountStatus.DRAFT, verbose_name="وضعیت")
    started_at = models.DateTimeField(null=True, blank=True, verbose_name="شروع انبارگردانی")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="پایان انبارگردانی")
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='cycle_counts_performed', verbose_name="مسئول شمارش")
    reconciled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='cycle_counts_reconciled', verbose_name="تأییدکننده تطبیق")
    notes = models.TextField(blank=True, verbose_name="توضیحات و یادداشت‌ها")

    class Meta:
        verbose_name = 'انبارگردانی'
        verbose_name_plural = 'انبارگردانی‌ها'
        unique_together = ('store', 'count_number')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.count_number} @ {self.warehouse.name} ({self.get_status_display()})"


class StockCycleCountItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cycle_count = models.ForeignKey(StockCycleCount, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='cycle_count_items', verbose_name="تنوع کالا")
    system_quantity = models.IntegerField(default=0, verbose_name="موجودی سیستم قبل از شمارش")
    counted_quantity = models.IntegerField(null=True, blank=True, verbose_name="موجودی فیزیکی شمارش‌شده")
    is_reconciled = models.BooleanField(default=False, verbose_name="تطبیق داده شده")
    notes = models.CharField(max_length=255, blank=True, verbose_name="توضیحات مغایرت")

    class Meta:
        verbose_name = 'ردیف انبارگردانی'
        verbose_name_plural = 'ردیف‌های انبارگردانی'
        unique_together = ('cycle_count', 'variant')

    @property
    def variance(self):
        if self.counted_quantity is None:
            return 0
        return self.counted_quantity - self.system_quantity

    def __str__(self):
        return f"{self.variant.sku}: سیستم={self.system_quantity}, شمارش={self.counted_quantity}"


class ReservationStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'فعال'
    RELEASED = 'RELEASED', 'آزاد شده'
    FULFILLED = 'FULFILLED', 'مصرف شده (ارسال سفارش)'


class StockReservation(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=150, db_index=True, verbose_name="شماره سفارش مرجع")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='reservations')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='reservations')
    quantity = models.PositiveIntegerField(verbose_name="تعداد رزرو شده")
    fulfilled_quantity = models.PositiveIntegerField(default=0, verbose_name="تعداد مصرف شده")
    status = models.CharField(
        max_length=20,
        choices=ReservationStatus.choices,
        default=ReservationStatus.ACTIVE,
        db_index=True,
        verbose_name="وضعیت رزرو"
    )

    class Meta:
        verbose_name = 'رزرو موجودی'
        verbose_name_plural = 'رزروهای موجودی'
        indexes = [
            models.Index(fields=['store', 'order_number', 'variant', 'warehouse']),
        ]

    @property
    def remaining_active(self):
        if self.status != ReservationStatus.ACTIVE:
            return 0
        return max(0, self.quantity - self.fulfilled_quantity)

    def __str__(self):
        return f"Reservation {self.order_number}: {self.quantity} x {self.variant.sku} ({self.status})"


