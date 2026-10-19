import csv
import io
import random
from decimal import Decimal, InvalidOperation
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import Order, OrderItem, Customer, OrderStatus, PaymentStatus, FulfillmentStatus, OrderChannel
from apps.catalog.models import ProductVariant
from apps.inventory.models import Warehouse
from apps.inventory.services import reserve_stock, release_stock_reservation, commit_stock_sale
from apps.audit.services import record_audit_event

def generate_order_number(store, *, _max_attempts=10):
    """Generate a unique, human-readable order number that is safe under concurrent creation.

    Format: ORD-YYYYMMDD-NNNN (per-store daily serial).
    Strategy: use count()+1 as a candidate, but rely on the DB unique constraint to detect
    collisions and retry with a random tie-break suffix. Bounded to _max_attempts iterations.
    Requires: a unique_together or UniqueConstraint on (store, order_number) in the Order model.
    """
    date_str = timezone.now().strftime('%Y%m%d')
    for attempt in range(_max_attempts):
        count = Order.objects.filter(store=store, created_at__date=timezone.now().date()).count() + 1 + attempt
        # On collision retries, add a random offset to reduce thundering-herd re-collision
        if attempt > 0:
            count += random.randint(0, 9)
        candidate = f"ORD-{date_str}-{count:04d}"
        if not Order.objects.filter(store=store, order_number=candidate).exists():
            return candidate
    # Fallback: use timestamp + random to guarantee uniqueness
    ts = timezone.now().strftime('%H%M%S')
    rand = random.randint(100, 999)
    return f"ORD-{date_str}-{ts}-{rand}"


@transaction.atomic
def create_order(store, customer_data, items_data, warehouse, channel=OrderChannel.MANUAL,
                 shipping_cost=Decimal('0'), discount_amount=Decimal('0'),
                 utm_source='', utm_medium='', utm_campaign='', notes='', user=None):
    """Creates an order, captures cost snapshots, and atomically reserves inventory"""
    from apps.features.services import FeatureService
    FeatureService.enforce_plan_quota(store, 'monthly_orders')

    if not items_data:
        raise ValueError("سفارش باید حداقل دارای یک ردیف کالا باشد.")
    shipping_cost = Decimal(str(shipping_cost))
    if shipping_cost < Decimal('0'):
        raise ValueError("هزینه ارسال نمی‌تواند منفی باشد.")
    discount_amount = Decimal(str(discount_amount))
    if discount_amount < Decimal('0'):
        raise ValueError("مبلغ تخفیف نمی‌تواند منفی باشد.")

    # Upfront validation of all items before any state mutations
    validated_items = []
    total_items_price = Decimal('0')
    for item in items_data:
        variant_id = item.get('variant_id')
        if not variant_id:
            raise ValueError("شناسه تنوع محصول (variant_id) الزامی است.")

        try:
            qty = int(item.get('quantity', 1))
        except (ValueError, TypeError):
            raise ValueError("تعداد کالا باید یک عدد صحیح باشد.")
        if qty <= 0:
            raise ValueError("تعداد کالا باید بزرگتر از صفر باشد.")

        try:
            variant = ProductVariant.objects.select_related('product').get(id=variant_id, store=store)
        except ProductVariant.DoesNotExist:
            raise ValueError(f"تنوع محصول با شناسه {variant_id} در این فروشگاه یافت نشد.")

        try:
            raw_unit_price = item.get('unit_price')
            unit_price = Decimal(str(raw_unit_price)) if raw_unit_price is not None else variant.retail_price
        except (ValueError, InvalidOperation):
            raise ValueError("قیمت واحد نامعتبر است.")
        if unit_price < Decimal('0'):
            raise ValueError("قیمت واحد نمی‌تواند منفی باشد.")
        if unit_price == Decimal('0') and variant.retail_price > Decimal('0'):
            unit_price = variant.retail_price

        try:
            unit_discount = Decimal(str(item.get('unit_discount', 0)))
        except (ValueError, InvalidOperation):
            raise ValueError("تخفیف واحد نامعتبر است.")
        if unit_discount < Decimal('0'):
            raise ValueError("تخفیف ردیف کالا نمی‌تواند منفی باشد.")
        if unit_discount > unit_price:
            raise ValueError(f"تخفیف ردیف کالا ({unit_discount}) نمی‌تواند از قیمت واحد ({unit_price}) بیشتر باشد.")

        item_total = (unit_price - unit_discount) * qty
        total_items_price += item_total
        validated_items.append({
            'variant': variant,
            'quantity': qty,
            'unit_price': unit_price,
            'unit_discount': unit_discount,
            'item_total': item_total,
        })

    # Validate order-level discount does not exceed payable items and shipping
    max_allowable_discount = total_items_price + shipping_cost
    if discount_amount > max_allowable_discount:
        raise ValueError(
            f"مبلغ تخفیف سفارش ({discount_amount}) نمی‌تواند از مجموع اقلام و هزینه ارسال ({max_allowable_discount}) بیشتر باشد."
        )

    grand_total = max(Decimal('0'), total_items_price + shipping_cost - discount_amount)

    # IDENTITY FIX: Do not fall back to a shared placeholder phone number.
    # Merging all phoneless customers under '09000000000' corrupts CRM data by conflating
    # unrelated customers. Phone is required for customer identity.
    phone = customer_data.get('phone_number') or customer_data.get('phone')
    if not phone or not str(phone).strip():
        raise ValueError("شماره تماس مشتری الزامی است. از شماره پیش‌فرض مشترک استفاده نکنید.")
    phone = str(phone).strip()

    name = customer_data.get('full_name') or customer_data.get('name') or 'مشتری بدون نام'

    # CONSENT FIX: Default marketing_opt_in to False, not True.
    # Opt-in requires explicit consent. Never assume consent when it is absent.
    # Only update an existing customer's consent if the caller explicitly supplies the field.
    opt_in = customer_data.get('marketing_opt_in', False)

    customer, created = Customer.objects.get_or_create(
        store=store,
        phone_number=phone,
        defaults={
            'full_name': name,
            'city': customer_data.get('city', ''),
            'province': customer_data.get('province', ''),
            'address_line': customer_data.get('address_line', '') or customer_data.get('address', ''),
            'postal_code': customer_data.get('postal_code', ''),
            'email': customer_data.get('email', ''),
            'marketing_opt_in': opt_in,
        }
    )
    if not created and 'marketing_opt_in' in customer_data and customer.marketing_opt_in != opt_in:
        customer.marketing_opt_in = opt_in
        customer.save(update_fields=['marketing_opt_in', 'updated_at'])

    # Collision-safe order creation with savepoint retry loop
    order = None
    for attempt in range(5):
        candidate_order_number = generate_order_number(store)
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    store=store,
                    order_number=candidate_order_number,
                    channel=channel,
                    customer=customer,
                    warehouse=warehouse,
                    currency=store.currency,
                    order_status=OrderStatus.CONFIRMED,
                    payment_status=PaymentStatus.PENDING,
                    fulfillment_status=FulfillmentStatus.UNFULFILLED,
                    total_items_price=total_items_price,
                    shipping_cost=shipping_cost,
                    discount_amount=discount_amount,
                    grand_total=grand_total,
                    utm_source=utm_source,
                    utm_medium=utm_medium,
                    utm_campaign=utm_campaign,
                    notes=notes,
                    created_by=user
                )
                break
        except IntegrityError:
            if attempt == 4:
                raise

    for item_info in validated_items:
        variant = item_info['variant']
        qty = item_info['quantity']

        # Atomic reservation check
        reserve_stock(
            store=store,
            warehouse=warehouse,
            variant=variant,
            quantity=qty,
            reference=order.order_number,
            user=user
        )

        OrderItem.objects.create(
            order=order,
            variant=variant,
            variant_sku=variant.sku,
            variant_name=f"{variant.product.name} ({variant.name})",
            quantity=qty,
            unit_price=item_info['unit_price'],
            cost_price_snapshot=variant.cost_price,  # Historical margin preservation!
            unit_discount=item_info['unit_discount'],
            total_price=item_info['item_total']
        )

    record_audit_event(
        store=store,
        user=user,
        action="ORDER_CREATED",
        target_type="Order",
        target_id=str(order.id),
        changes={'order_number': order.order_number, 'grand_total': str(order.grand_total)}
    )

    import logging
    _logger = logging.getLogger(__name__)

    def _dispatch_order_created():
        try:
            from apps.automation.services import trigger_automation
            from apps.automation.models import TriggerEvent
            trigger_automation(
                store=store,
                trigger_event=TriggerEvent.ORDER_CREATED,
                payload={
                    'order_id': str(order.id),
                    'order_number': order.order_number,
                    'customer_name': customer.full_name,
                    'customer_phone': customer.phone_number,
                    'grand_total': float(order.grand_total),
                    'items_count': len(items_data),
                    'idempotency_key': f"order_created_{order.id}"
                }
            )
        except Exception as exc:
            _logger.error(
                "Automation dispatch failed for ORDER_CREATED event",
                exc_info=True,
                extra={'order_id': str(order.id), 'error': str(exc)}
            )

    transaction.on_commit(_dispatch_order_created)
    return order

@transaction.atomic
def cancel_order(order, reason='', user=None):
    """Cancels order and releases reserved inventory. Rejects cancellation of fulfilled orders."""
    if order.order_status in [OrderStatus.CANCELLED, OrderStatus.COMPLETED, OrderStatus.FULFILLED] or order.fulfillment_status == FulfillmentStatus.FULFILLED:
        raise ValueError(
            f"سفارش با وضعیت {order.get_order_status_display()} قابل لغو مستقیم نیست. "
            "برای سفارش‌های ارسال‌شده، از فرآیند ثبت مرجوعی (RMA) استفاده نمایید."
        )

    order = Order.objects.select_for_update().get(id=order.id)
    if order.order_status in [OrderStatus.CANCELLED, OrderStatus.COMPLETED, OrderStatus.FULFILLED] or order.fulfillment_status == FulfillmentStatus.FULFILLED:
        raise ValueError(f"سفارش با وضعیت {order.get_order_status_display()} قابل لغو نیست.")

    # Release reservations for each item
    for item in order.items.all():
        release_stock_reservation(
            store=order.store,
            warehouse=order.warehouse,
            variant=item.variant,
            quantity=item.quantity,
            reference=order.order_number,
            user=user
        )

    old_status = order.order_status
    order.order_status = OrderStatus.CANCELLED
    order.save()

    record_audit_event(
        store=order.store,
        user=user,
        action="ORDER_CANCELLED",
        target_type="Order",
        target_id=str(order.id),
        changes={'old_status': old_status, 'new_status': OrderStatus.CANCELLED, 'reason': reason}
    )

    def _dispatch_order_cancelled():
        import logging
        _dlogger = logging.getLogger(__name__)
        try:
            from apps.automation.services import trigger_automation
            from apps.automation.models import TriggerEvent
            trigger_automation(
                store=order.store,
                trigger_event=TriggerEvent.ORDER_CANCELLED,
                payload={
                    'order_id': str(order.id),
                    'order_number': order.order_number,
                    'customer_name': order.customer.full_name,
                    'customer_phone': order.customer.phone_number,
                    'grand_total': float(order.grand_total),
                    'idempotency_key': f"order_cancelled_{order.id}"
                }
            )
        except Exception:
            _dlogger.error(
                "Automation dispatch failed for ORDER_CANCELLED order_id=%s",
                order.id, exc_info=True
            )

    transaction.on_commit(_dispatch_order_cancelled)
    return order

@transaction.atomic
def fulfill_order(order, tracking_number='', shipping_cost=None, user=None):
    """Commits reserved stock to permanent sale and marks order fulfilled. Idempotent against duplicate requests."""
    if order.order_status == OrderStatus.CANCELLED:
        raise ValueError("سفارش لغو شده قابل ارسال نیست.")

    # Idempotent return if already fulfilled
    if order.order_status in [OrderStatus.FULFILLED, OrderStatus.COMPLETED] or order.fulfillment_status == FulfillmentStatus.FULFILLED:
        from apps.fulfillment.models import Shipment
        existing_shipment = Shipment.objects.filter(order=order).first()
        return order, existing_shipment

    order = Order.objects.select_for_update().get(id=order.id)
    if order.order_status in [OrderStatus.FULFILLED, OrderStatus.COMPLETED] or order.fulfillment_status == FulfillmentStatus.FULFILLED:
        from apps.fulfillment.models import Shipment
        existing_shipment = Shipment.objects.filter(order=order).first()
        return order, existing_shipment

    for item in order.items.all():
        commit_stock_sale(
            store=order.store,
            warehouse=order.warehouse,
            variant=item.variant,
            quantity=item.quantity,
            reference=order.order_number,
            user=user
        )

    order.order_status = OrderStatus.FULFILLED
    order.fulfillment_status = FulfillmentStatus.FULFILLED
    order.save()

    # Record shipment using fulfillment service with idempotency key
    from apps.fulfillment.services import create_shipment
    from apps.fulfillment.models import Carrier
    shipment = create_shipment(
        store=order.store,
        order=order,
        tracking_number=tracking_number or f"TRK-{str(order.id)[:8].upper()}",
        carrier=Carrier.IRPOST,
        shipping_cost=shipping_cost if shipping_cost is not None else order.shipping_cost,
        idempotency_key=f"ship_{order.id}"
    )

    record_audit_event(
        store=order.store,
        user=user,
        action="ORDER_FULFILLED",
        target_type="Order",
        target_id=str(order.id),
        changes={'tracking_number': shipment.tracking_number}
    )

    def _dispatch_order_fulfilled():
        import logging
        _dlogger = logging.getLogger(__name__)
        try:
            from apps.automation.services import trigger_automation
            from apps.automation.models import TriggerEvent
            trigger_automation(
                store=order.store,
                trigger_event=TriggerEvent.ORDER_FULFILLED,
                payload={
                    'order_id': str(order.id),
                    'order_number': order.order_number,
                    'customer_name': order.customer.full_name,
                    'customer_phone': order.customer.phone_number,
                    'tracking_number': shipment.tracking_number,
                    'idempotency_key': f"order_fulfilled_{order.id}"
                }
            )
        except Exception:
            _dlogger.error(
                "Automation dispatch failed for ORDER_FULFILLED order_id=%s",
                order.id, exc_info=True
            )

    transaction.on_commit(_dispatch_order_fulfilled)
    return order, shipment

def import_orders_from_csv(store, file_content, user=None):
    """
    Parses and validates CSV with columns:
    customer_name, customer_phone, sku, quantity, unit_price, channel, city, address
    Returns dict with summary: created, skipped, errors.
    """
    decoded = file_content.decode('utf-8-sig') if isinstance(file_content, bytes) else file_content
    reader = csv.DictReader(io.StringIO(decoded))

    created_count = 0
    errors = []
    default_warehouse = Warehouse.objects.filter(store=store, is_active=True).first()
    if not default_warehouse:
        default_warehouse = Warehouse.objects.create(store=store, name="انبار مرکزی", is_default=True)

    row_index = 1
    for row in reader:
        row_index += 1
        phone = row.get('customer_phone', '').strip()
        name = row.get('customer_name', '').strip()
        sku = row.get('sku', '').strip()
        qty_str = row.get('quantity', '1').strip()
        price_str = row.get('unit_price', '0').strip()
        channel = row.get('channel', 'MANUAL').strip().upper()

        if not phone or not sku:
            errors.append({'row': row_index, 'error': 'شماره تماس یا کد SKU خالی است.'})
            continue

        try:
            qty = int(qty_str)
            price = Decimal(price_str)
        except Exception:
            errors.append({'row': row_index, 'error': f'مقدار عددی تعداد یا قیمت نامعتبر است: {qty_str}, {price_str}'})
            continue

        variant = ProductVariant.objects.filter(store=store, sku=sku).first()
        if not variant:
            errors.append({'row': row_index, 'error': f'تنوع کالا با کد SKU={sku} یافت نشد.'})
            continue

        try:
            create_order(
                store=store,
                customer_data={
                    'full_name': name or 'مشتری ایمپورت شده',
                    'phone_number': phone,
                    'city': row.get('city', ''),
                    'address_line': row.get('address', ''),
                },
                items_data=[{
                    'variant_id': str(variant.id),
                    'quantity': qty,
                    'unit_price': price if price > 0 else variant.retail_price,
                }],
                warehouse=default_warehouse,
                channel=channel if channel in OrderChannel.values else OrderChannel.MANUAL,
                user=user
            )
            created_count += 1
        except Exception as e:
            errors.append({'row': row_index, 'error': str(e)})

    return {
        'total_rows': row_index - 1,
        'created': created_count,
        'failed': len(errors),
        'errors': errors
    }
