import uuid
from decimal import Decimal
from django.db import models
from apps.tenancy.models import TenantScopedModel, Store

class Category(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, verbose_name="نام دسته‌بندی")
    slug = models.SlugField(max_length=150, blank=True)
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')

    class Meta:
        verbose_name = 'دسته‌بندی'
        verbose_name_plural = 'دسته‌بندی‌ها'
        unique_together = ('store', 'slug')
        ordering = ['name']

    def __str__(self):
        return self.name

class ProductStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'پیش‌نویس'
    ACTIVE = 'ACTIVE', 'فعال'
    ARCHIVED = 'ARCHIVED', 'بایگانی‌شده'

class Product(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, verbose_name="نام محصول")
    slug = models.SlugField(max_length=255, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    brand = models.CharField(max_length=100, blank=True, verbose_name="برند")
    description = models.TextField(blank=True, verbose_name="توضیحات")
    status = models.CharField(max_length=20, choices=ProductStatus.choices, default=ProductStatus.ACTIVE, verbose_name="وضعیت")

    class Meta:
        verbose_name = 'محصول'
        verbose_name_plural = 'محصولات'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

class ProductVariant(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    name = models.CharField(max_length=150, verbose_name="عنوان تنوع (رنگ/سایز)")
    sku = models.CharField(max_length=100, db_index=True, verbose_name="شناسه کالا (SKU)")
    barcode = models.CharField(max_length=100, blank=True, null=True, db_index=True, verbose_name="بارکد")
    
    # Monetary values in Decimal (Toman / Rial based on store setting)
    cost_price = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="قیمت خرید/تمام‌شده")
    retail_price = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="قیمت فروش عادی")
    wholesale_price = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True, verbose_name="قیمت عمده‌فروشی")
    
    weight_grams = models.PositiveIntegerField(default=0, verbose_name="وزن به گرم")
    is_active = models.BooleanField(default=True, verbose_name="فعال")

    class Meta:
        verbose_name = 'تنوع محصول'
        verbose_name_plural = 'تنوع‌های محصول'
        unique_together = ('store', 'sku')

    def __str__(self):
        return f"{self.product.name} - {self.name} ({self.sku})"

class ProductImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image_url = models.URLField(max_length=1000, verbose_name="آدرس تصویر")
    is_primary = models.BooleanField(default=False, verbose_name="تصویر شاخص")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']


class ProductPriceHistory(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='price_history', verbose_name="تنوع کالا")
    old_retail_price = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="قیمت فروش قبلی")
    new_retail_price = models.DecimalField(max_digits=14, decimal_places=0, verbose_name="قیمت فروش جدید")
    old_cost_price = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="قیمت خرید قبلی")
    new_cost_price = models.DecimalField(max_digits=14, decimal_places=0, default=Decimal('0'), verbose_name="قیمت خرید جدید")
    reason = models.CharField(max_length=255, blank=True, verbose_name="دلیل تغییر قیمت")
    changed_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="تغییردهنده")

    class Meta:
        verbose_name = 'تاریخچه تغییر قیمت'
        verbose_name_plural = 'تاریخچه تغییرات قیمت'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.variant.sku}: {self.old_retail_price:,} -> {self.new_retail_price:,}"
