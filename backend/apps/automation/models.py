import uuid
from django.db import models
from apps.tenancy.models import TenantScopedModel

class TriggerEvent(models.TextChoices):
    ORDER_CREATED = 'ORDER_CREATED', 'ثبت سفارش جدید'
    ORDER_PAID = 'ORDER_PAID', 'پرداخت موفق سفارش'
    ORDER_FULFILLED = 'ORDER_FULFILLED', 'ارسال سفارش (تحویل به پست)'
    ORDER_CANCELLED = 'ORDER_CANCELLED', 'لغو سفارش'
    STOCK_LOW = 'STOCK_LOW', 'کاهش موجودی به زیر حد بحرانی'
    NEW_CUSTOMER = 'NEW_CUSTOMER', 'عضویت مشتری جدید'
    RETURN_REQUESTED = 'RETURN_REQUESTED', 'ثبت درخواست مرجوعی'

class ExecutionStatus(models.TextChoices):
    PENDING = 'PENDING', 'در انتظار اجرا'
    RUNNING = 'RUNNING', 'در حال اجرا'
    SUCCESS = 'SUCCESS', 'موفق'
    FAILED = 'FAILED', 'خطا در اجرا'
    SKIPPED = 'SKIPPED', 'عدم انطباق شرایط (رد شد)'

class AutomationRule(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, verbose_name="عنوان قانون اتوماسیون")
    description = models.TextField(blank=True, verbose_name="شرح عملکرد قانون")
    trigger = models.CharField(
        max_length=30,
        choices=TriggerEvent.choices,
        verbose_name="رویداد محرک (Trigger)"
    )
    conditions = models.JSONField(default=dict, blank=True, verbose_name="شرایط اجرا (Conditions)")
    actions = models.JSONField(default=list, verbose_name="اقدامات اجرایی (Actions)")
    is_active = models.BooleanField(default=True, verbose_name="فعال")
    execution_count = models.IntegerField(default=0, verbose_name="تعداد دفعات اجرا")
    last_executed_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان آخرین اجرا")

    class Meta:
        verbose_name = 'قانون اتوماسیون'
        verbose_name_plural = 'قوانین اتوماسیون'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_trigger_display()})"


class AutomationExecutionLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name='logs')
    idempotency_key = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="کلید انحصار (Idempotency Key)"
    )
    trigger_event = models.CharField(max_length=50, verbose_name="نوع رویداد")
    event_payload = models.JSONField(default=dict, verbose_name="داده‌های رویداد")
    status = models.CharField(
        max_length=20,
        choices=ExecutionStatus.choices,
        default=ExecutionStatus.SUCCESS,
        verbose_name="وضعیت اجرا"
    )
    details = models.TextField(blank=True, verbose_name="گزارش خروجی اقدامات")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'لاگ اجرای اتوماسیون'
        verbose_name_plural = 'لاگ‌های اجرای اتوماسیون'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['rule', 'idempotency_key'],
                name='unique_rule_execution_idempotency',
                condition=models.Q(idempotency_key__isnull=False)
            )
        ]

    def __str__(self):
        return f"Log: {self.rule.name} - {self.status} at {self.created_at}"


class OutboxStatus(models.TextChoices):
    PENDING = 'PENDING', 'در انتظار ارسال'
    PROCESSING = 'PROCESSING', 'در حال پردازش'
    DELIVERED = 'DELIVERED', 'تحویل شده'
    FAILED = 'FAILED', 'ناموفق'


class OutboxEvent(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=50, db_index=True, verbose_name="نوع رویداد")
    event_key = models.CharField(max_length=150, blank=True, db_index=True, verbose_name="شناسه یکتای رویداد")
    payload = models.JSONField(default=dict, verbose_name="داده‌های رویداد")
    status = models.CharField(
        max_length=20,
        choices=OutboxStatus.choices,
        default=OutboxStatus.PENDING,
        db_index=True,
        verbose_name="وضعیت رویداد"
    )
    retry_count = models.IntegerField(default=0, verbose_name="تعداد تلاش‌ها")
    max_retries = models.IntegerField(default=5, verbose_name="حداکثر دفعات تلاش")
    last_error = models.TextField(blank=True, verbose_name="آخرین خطا")
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="زمان تلاش مجدد")
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان تکمیل پردازش")

    class Meta:
        verbose_name = 'رویداد خروجی (Outbox)'
        verbose_name_plural = 'رویدادهای خروجی (Outbox)'
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['status', 'next_retry_at']),
        ]

    def __str__(self):
        return f"Outbox: {self.event_type} ({self.status}) - {self.id}"


