import base64
import hashlib
import hmac
import json
import logging
import urllib.request
import urllib.error
from decimal import Decimal
from typing import Dict, Any, Optional

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.tenancy.models import Store
from apps.catalog.models import Product, ProductVariant, ProductStatus
from apps.inventory.models import Warehouse, InventoryBalance
from apps.orders.models import (
    Order, OrderItem, Customer, OrderChannel, OrderStatus,
    PaymentStatus, FulfillmentStatus, WooCommerceSyncLog,
    SyncType, SyncStatus
)
from apps.features.adapters import get_integration_adapter
from apps.features.security import validate_custom_url

logger = logging.getLogger(__name__)


def get_wc_config(store: Store) -> Dict[str, Any]:
    adapter = get_integration_adapter('ecommerce_woocommerce')
    if not adapter:
        raise ValidationError("آداپتور ووکامرس در سیستم ثبت نشده است.")
    
    config = adapter.get_config(store, decrypted=True)
    store_url = (config.get('store_url') or '').strip().rstrip('/')
    ck = config.get('consumer_key')
    cs = config.get('consumer_secret')

    if not store_url or not ck or not cs:
        raise ValidationError("تنظیمات اتصال ووکامرس (آدرس سایت، کلید یا رمز API) تکمیل نشده است.")

    validate_custom_url(store_url)
    auth_str = f"{ck}:{cs}"
    auth_header = f"Basic {base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')}"

    return {
        'store_url': store_url,
        'auth_header': auth_header,
        'sync_inventory': config.get('sync_inventory', True),
        'sync_orders': config.get('sync_orders', True),
        'webhook_secret': config.get('webhook_secret', ''),
    }


def sync_woocommerce_products(store: Store) -> Dict[str, Any]:
    """
    Fetches products from WooCommerce REST API and synchronizes them into ShopPilot catalog.
    """
    try:
        conf = get_wc_config(store)
    except ValidationError as e:
        WooCommerceSyncLog.objects.create(
            store=store,
            sync_type=SyncType.PRODUCTS,
            status=SyncStatus.FAILED,
            items_synced=0,
            error_details=str(e)
        )
        raise

    url = f"{conf['store_url']}/wp-json/wc/v3/products?per_page=50"
    req = urllib.request.Request(
        url,
        headers={
            'Authorization': conf['auth_header'],
            'Accept': 'application/json',
            'User-Agent': 'ShopPilot-Commerce/1.0'
        },
        method='GET'
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            products_data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        err_msg = f"خطا در دریافت کاتالوگ محصولات از ووکامرس: {str(e)}"
        WooCommerceSyncLog.objects.create(
            store=store,
            sync_type=SyncType.PRODUCTS,
            status=SyncStatus.FAILED,
            items_synced=0,
            error_details=err_msg
        )
        raise ValidationError(err_msg)

    synced_count = 0
    with transaction.atomic():
        for wc_item in products_data:
            wc_id = wc_item.get('id')
            title = wc_item.get('name', '').strip()
            slug = wc_item.get('slug', '') or f"wc-{wc_id}"
            price_val = Decimal(str(wc_item.get('price') or 0))
            sku = (wc_item.get('sku') or f"WC-{wc_id}").strip()

            product, _ = Product.objects.get_or_create(
                store=store,
                slug=slug,
                defaults={
                    'name': title,
                    'description': wc_item.get('description', ''),
                    'status': ProductStatus.ACTIVE
                }
            )

            variant, created = ProductVariant.objects.get_or_create(
                store=store,
                sku=sku,
                defaults={
                    'product': product,
                    'name': 'پیش‌فرض',
                    'retail_price': price_val,
                    'is_active': True
                }
            )
            if not created:
                variant.retail_price = price_val
                variant.save(update_fields=['retail_price'])

            synced_count += 1

    WooCommerceSyncLog.objects.create(
        store=store,
        sync_type=SyncType.PRODUCTS,
        status=SyncStatus.SUCCESS,
        items_synced=synced_count,
        error_details=""
    )

    return {
        'status': 'SUCCESS',
        'synced_items': synced_count,
        'message': f'{synced_count} محصول از ووکامرس با موفقیت همگام شد.'
    }


def push_inventory_to_woocommerce(store: Store, variant: ProductVariant) -> Dict[str, Any]:
    """
    Pushes available stock quantity of a variant from ShopPilot to WooCommerce.
    ShopPilot acts as the authoritative single source of truth for inventory.
    """
    try:
        conf = get_wc_config(store)
    except Exception as e:
        return {'status': 'SKIPPED', 'reason': str(e)}

    if not conf.get('sync_inventory'):
        return {'status': 'SKIPPED', 'reason': 'همگام‌سازی موجودی در تنظیمات غیرفعال است.'}

    # Calculate net available inventory in default warehouse
    balance = InventoryBalance.objects.filter(variant=variant, warehouse__store=store).first()
    available_qty = balance.available if balance else 0

    # Search WooCommerce product by SKU
    sku_encoded = urllib.parse.quote(variant.sku)
    search_url = f"{conf['store_url']}/wp-json/wc/v3/products?sku={sku_encoded}"
    req = urllib.request.Request(
        search_url,
        headers={'Authorization': conf['auth_header'], 'Accept': 'application/json'},
        method='GET'
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            results = json.loads(resp.read().decode('utf-8'))
            if not results:
                return {'status': 'NOT_FOUND', 'message': f'محصول با SKU {variant.sku} در ووکامرس یافت نشد.'}

            wc_product_id = results[0]['id']

            # Update stock in WooCommerce
            update_url = f"{conf['store_url']}/wp-json/wc/v3/products/{wc_product_id}"
            payload = {
                'manage_stock': True,
                'stock_quantity': available_qty
            }
            update_req = urllib.request.Request(
                update_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Authorization': conf['auth_header'],
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                method='PUT'
            )
            with urllib.request.urlopen(update_req, timeout=15) as update_resp:
                if update_resp.status in (200, 201):
                    WooCommerceSyncLog.objects.create(
                        store=store,
                        sync_type=SyncType.INVENTORY,
                        status=SyncStatus.SUCCESS,
                        items_synced=1,
                        error_details=""
                    )
                    return {
                        'status': 'SUCCESS',
                        'variant_sku': variant.sku,
                        'synced_stock': available_qty
                    }
    except Exception as e:
        logger.error(f"WooCommerce inventory push failed for SKU {variant.sku}: {e}")
        WooCommerceSyncLog.objects.create(
            store=store,
            sync_type=SyncType.INVENTORY,
            status=SyncStatus.FAILED,
            items_synced=0,
            error_details=str(e)
        )
        return {'status': 'FAILED', 'error': str(e)}

    return {'status': 'FAILED', 'error': 'خطای نامشخص در همگام‌سازی موجودی'}


def ingest_woocommerce_order_payload(store: Store, wc_order: Dict[str, Any]) -> Order:
    """
    Ingests or updates a single WooCommerce order into ShopPilot idempotently.
    """
    wc_id = wc_order.get('id')
    order_number = f"WC-{wc_order.get('number') or wc_id}"

    # Check if order already exists
    existing = Order.objects.filter(store=store, order_number=order_number).first()
    if existing:
        # Update statuses if needed
        wc_status = wc_order.get('status', '').lower()
        if wc_status in ('completed', 'processing') and existing.payment_status != PaymentStatus.PAID:
            existing.payment_status = PaymentStatus.PAID
            existing.save(update_fields=['payment_status'])
        return existing

    billing = wc_order.get('billing', {})
    phone = (billing.get('phone') or '').strip()
    if not phone:
        phone = f"0900000{str(wc_id)[-4:]}"

    first_name = billing.get('first_name', '').strip()
    last_name = billing.get('last_name', '').strip()
    full_name = f"{first_name} {last_name}".strip() or f"مشتری ووکامرس #{wc_id}"

    customer, _ = Customer.objects.get_or_create(
        store=store,
        phone_number=phone,
        defaults={
            'full_name': full_name,
            'email': billing.get('email', '') or None,
            'city': billing.get('city', ''),
            'province': billing.get('state', ''),
            'address_line': billing.get('address_1', ''),
            'postal_code': billing.get('postcode', ''),
            'marketing_opt_in': True,
        }
    )

    warehouse = Warehouse.objects.filter(store=store, is_default=True, is_active=True).first()
    if not warehouse:
        warehouse = Warehouse.objects.filter(store=store, is_active=True).first()
    if not warehouse:
        warehouse = Warehouse.objects.create(store=store, name="انبار پیش‌فرض سایت", is_default=True)

    # Status mapping
    wc_status = (wc_order.get('status') or 'processing').lower()
    if wc_status in ('processing', 'completed'):
        ord_status = OrderStatus.CONFIRMED if wc_status == 'processing' else OrderStatus.COMPLETED
        pay_status = PaymentStatus.PAID
    elif wc_status in ('cancelled', 'failed'):
        ord_status = OrderStatus.CANCELLED
        pay_status = PaymentStatus.FAILED
    else:
        ord_status = OrderStatus.PENDING_CONFIRMATION
        pay_status = PaymentStatus.PENDING

    grand_total = Decimal(str(wc_order.get('total') or 0))
    shipping_cost = Decimal(str(wc_order.get('shipping_total') or 0))
    discount_amount = Decimal(str(wc_order.get('discount_total') or 0))

    order = Order.objects.create(
        store=store,
        order_number=order_number,
        channel=OrderChannel.WOOCOMMERCE,
        customer=customer,
        warehouse=warehouse,
        order_status=ord_status,
        payment_status=pay_status,
        fulfillment_status=FulfillmentStatus.UNFULFILLED,
        currency=wc_order.get('currency', 'IRT'),
        shipping_cost=shipping_cost,
        discount_amount=discount_amount,
        grand_total=grand_total,
        notes=wc_order.get('customer_note', '')
    )

    total_items = Decimal('0')
    for item in wc_order.get('line_items', []):
        qty = int(item.get('quantity', 1))
        unit_price = Decimal(str(item.get('price') or 0))
        item_total = unit_price * qty
        sku = (item.get('sku') or f"WC-PROD-{item.get('product_id')}").strip()
        name = item.get('name', 'کالای ووکامرس')

        product, _ = Product.objects.get_or_create(
            store=store,
            slug=f"prod-{item.get('product_id')}",
            defaults={'name': name, 'status': ProductStatus.ACTIVE}
        )
        variant, _ = ProductVariant.objects.get_or_create(
            store=store,
            sku=sku,
            defaults={
                'product': product,
                'name': name,
                'retail_price': unit_price,
                'is_active': True
            }
        )

        OrderItem.objects.create(
            order=order,
            variant=variant,
            variant_sku=sku,
            variant_name=name,
            quantity=qty,
            unit_price=unit_price,
            cost_price_snapshot=variant.cost_price,
            total_price=item_total
        )
        total_items += item_total

    order.total_items_price = total_items
    order.save(update_fields=['total_items_price'])

    return order


def sync_woocommerce_orders(store: Store) -> Dict[str, Any]:
    """
    Polls recent WooCommerce orders and ingests new ones.
    """
    try:
        conf = get_wc_config(store)
    except ValidationError as e:
        WooCommerceSyncLog.objects.create(
            store=store,
            sync_type=SyncType.ORDERS,
            status=SyncStatus.FAILED,
            items_synced=0,
            error_details=str(e)
        )
        raise

    url = f"{conf['store_url']}/wp-json/wc/v3/orders?status=processing,pending,on-hold,completed&per_page=20"
    req = urllib.request.Request(
        url,
        headers={
            'Authorization': conf['auth_header'],
            'Accept': 'application/json',
            'User-Agent': 'ShopPilot-Commerce/1.0'
        },
        method='GET'
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            orders_data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        err_msg = f"خطا در دریافت سفارشات از ووکامرس: {str(e)}"
        WooCommerceSyncLog.objects.create(
            store=store,
            sync_type=SyncType.ORDERS,
            status=SyncStatus.FAILED,
            items_synced=0,
            error_details=err_msg
        )
        raise ValidationError(err_msg)

    synced_count = 0
    with transaction.atomic():
        for wc_ord in orders_data:
            ingest_woocommerce_order_payload(store, wc_ord)
            synced_count += 1

    WooCommerceSyncLog.objects.create(
        store=store,
        sync_type=SyncType.ORDERS,
        status=SyncStatus.SUCCESS,
        items_synced=synced_count,
        error_details=""
    )

    return {
        'status': 'SUCCESS',
        'synced_count': synced_count,
        'message': f'{synced_count} سفارش از ووکامرس با موفقیت بررسی و دریافت شد.'
    }


def handle_woocommerce_webhook(store: Store, topic: str, raw_body: bytes, signature_header: str) -> Dict[str, Any]:
    """
    Validates HMAC-SHA256 signature and processes real-time webhook events from WooCommerce.
    """
    conf = get_wc_config(store)
    secret = conf.get('webhook_secret')

    if secret and signature_header:
        expected_sig = base64.b64encode(hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).digest()).decode('utf-8')
        if not hmac.compare_digest(expected_sig, signature_header):
            raise ValidationError("امضای وب‌هوک ووکامرس نامعتبر است.")

    payload = json.loads(raw_body.decode('utf-8'))

    if topic.startswith('order.'):
        order = ingest_woocommerce_order_payload(store, payload)
        WooCommerceSyncLog.objects.create(
            store=store,
            sync_type=SyncType.WEBHOOK,
            status=SyncStatus.SUCCESS,
            items_synced=1,
            error_details=f"رویداد {topic} برای سفارش {order.order_number}"
        )
        return {'status': 'ORDER_SYNCED', 'order_id': str(order.id), 'order_number': order.order_number}

    return {'status': 'PROCESSED', 'topic': topic}
