import uuid
from django.db import models
from django.conf import settings
from apps.tenancy.models import TenantScopedModel
from apps.orders.models import Customer

class ThreadChannel(models.TextChoices):
    INSTAGRAM_DM = 'INSTAGRAM_DM', 'دایرکت اینستاگرام'
    TELEGRAM = 'TELEGRAM', 'تلگرام'
    WHATSAPP = 'WHATSAPP', 'واتساپ'
    WEB_CHAT = 'WEB_CHAT', 'چت آنلاین وب‌سایت'

class ThreadStatus(models.TextChoices):
    OPEN = 'OPEN', 'باز (در انتظار پاسخ ما)'
    PENDING_CUSTOMER = 'PENDING_CUSTOMER', 'در انتظار پاسخ مشتری'
    RESOLVED = 'RESOLVED', 'پاسخ داده شده و بسته'
    SPAM = 'SPAM', 'اسپم'

class SenderType(models.TextChoices):
    CUSTOMER = 'CUSTOMER', 'مشتری'
    AGENT = 'AGENT', 'پشتیبان انسانی'
    AI_ASSISTANT = 'AI_ASSISTANT', 'دستیار هوش مصنوعی'

class ConversationThread(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.CharField(
        max_length=30,
        choices=ThreadChannel.choices,
        default=ThreadChannel.INSTAGRAM_DM,
        verbose_name="کانال ارتباطی"
    )
    external_thread_id = models.CharField(max_length=150, blank=True, verbose_name="شناسه گفتگو در پلتفرم خارجی")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name='threads', verbose_name="مشتری شناسایی‌شده")
    contact_name = models.CharField(max_length=150, verbose_name="نام مخاطب")
    contact_handle = models.CharField(max_length=150, blank=True, verbose_name="آیدی کاربری (مثلاً @username)")
    status = models.CharField(
        max_length=30,
        choices=ThreadStatus.choices,
        default=ThreadStatus.OPEN,
        verbose_name="وضعیت گفتگو"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_threads',
        verbose_name="پشتیبان مسئول"
    )
    last_message_preview = models.CharField(max_length=255, blank=True, verbose_name="پیش‌نمایش آخرین پیام")
    unread_count = models.IntegerField(default=0, verbose_name="تعداد پیام‌های خوانده‌نشده")
    last_message_at = models.DateTimeField(auto_now=True, verbose_name="زمان آخرین پیام")

    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='threads', verbose_name="سفارش مرتبط")
    internal_notes = models.TextField(blank=True, verbose_name="یادداشت‌های محرمانه داخلی تیم")
    auto_reply_enabled = models.BooleanField(default=False, verbose_name="پاسخ‌دهی خودکار بدون تأیید انسانی")
    tags = models.JSONField(default=list, blank=True, verbose_name="برچسب‌های گفتگو")

    class Meta:
        verbose_name = 'مکالمه و پیام دایرکت'
        verbose_name_plural = 'مکالمات و پیام‌های دایرکت'
        ordering = ['-last_message_at']

    def __str__(self):
        return f"[{self.get_channel_display()}] {self.contact_name} ({self.contact_handle})"


class ChatMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(ConversationThread, on_delete=models.CASCADE, related_name='messages')
    sender_type = models.CharField(
        max_length=20,
        choices=SenderType.choices,
        default=SenderType.CUSTOMER,
        verbose_name="فرستنده پیام"
    )
    sender_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    text = models.TextField(verbose_name="متن پیام")
    media_url = models.CharField(max_length=500, blank=True, verbose_name="لینک فایل یا تصویر ضمیمه")
    is_ai_generated = models.BooleanField(default=False, verbose_name="پیشنهاد هوش مصنوعی")
    was_edited_by_human = models.BooleanField(default=False, verbose_name="ویرایش شده توسط کاربر قبل از ارسال")
    external_message_id = models.CharField(max_length=150, blank=True, db_index=True, verbose_name="شناسه پیام در پلتفرم خارجی")
    delivery_status = models.CharField(
        max_length=30,
        default='SENT',
        choices=[
            ('SENT', 'ارسال شده'),
            ('DELIVERED', 'تحویل شده'),
            ('FAILED', 'خطا در ارسال'),
            ('LOCAL_ONLY', 'ذخیره محلی (آفلاین)')
        ],
        verbose_name="وضعیت تحویل"
    )
    error_message = models.TextField(blank=True, verbose_name="متن خطای ارسال خارجی")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'پیام گفتگو'
        verbose_name_plural = 'پیام‌های گفتگو'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender_type}: {self.text[:30]}"
