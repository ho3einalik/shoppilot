import uuid
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.orders.models import Order, OrderItem, Customer, OrderChannel, OrderStatus, PaymentStatus, FulfillmentStatus
from apps.catalog.models import ProductVariant
from apps.inventory.models import Warehouse
from apps.inventory.services import commit_stock_sale, get_or_create_balance, reserve_stock
from apps.payments.models import PaymentTransaction, PaymentMethod, PaymentVerificationStatus
from apps.audit.services import record_audit_event
from apps.finance.models import AccountsPayableReceivable, DebtEntityType, DebtStatus
from .models import B2BClientProfile, VolumeTierDiscount, POSTerminal, POSRegisterSession, POSSessionStatus, ProformaInvoice, ProformaStatus, B2BTier

def calculate_b2b_price(variant, quantity, client=None):
    """
    Calculate applicable unit price considering MOQ / Volume Tier discounts and B2B VIP tiers.
    """
    # 1. Volume Tier Discount (MOQ)
    vol_tier = VolumeTierDiscount.objects.filter(
        variant=variant,
        min_quantity__lte=quantity
    ).order_by('-min_quantity').first()

    base_price = vol_tier.unit_price if vol_tier else variant.retail_price

    # 2. Client tier-based discount
    if client and client.tier:
        tier_discounts = {
            B2BTier.VIP: Decimal('0.15'),
            B2BTier.GOLD: Decimal('0.10'),
            B2BTier.SILVER: Decimal('0.05'),
            B2BTier.STANDARD: Decimal('0.00'),
        }
        discount_rate = tier_discounts.get(client.tier, Decimal('0.00'))
        final_price = round(base_price * (Decimal('1') - discount_rate))
        return max(Decimal('0'), final_price)

    return base_price


@transaction.atomic
def pos_quick_checkout(store, session_id, items_data, customer_phone="09000000000", customer_name="خریدار حضوری", payment_method=PaymentMethod.POS_TERMINAL, user=None, notes=""):
    """
    Real-time In-Person POS quick sale.
    Instantly commits stock sale from terminal warehouse, creates order, and issues payment receipt.
    """
    try:
        session = POSRegisterSession.objects.select_for_update().get(id=session_id, store=store, status=POSSessionStatus.OPEN)
    except POSRegisterSession.DoesNotExist:
        raise ValidationError("شیفت صندوقداری فعال یا بازی برای این پایانه یافت نشد.")

    warehouse = session.terminal.warehouse
    if not warehouse:
        warehouse = Warehouse.objects.filter(store=store).first()
        if not warehouse:
            raise ValidationError("هیچ انباری برای کسر موجودی فروشگاه تعریف نشده است.")

    # Get or create customer
    customer, _ = Customer.objects.get_or_create(
        store=store,
        phone_number=customer_phone,
        defaults={'full_name': customer_name or 'خریدار حضوری'}
    )

    order_number = f"POS-{timezone.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    order = Order.objects.create(
        store=store,
        order_number=order_number,
        channel=OrderChannel.POS,
        customer=customer,
        warehouse=warehouse,
        order_status=OrderStatus.COMPLETED,
        payment_status=PaymentStatus.PAID,
        fulfillment_status=FulfillmentStatus.FULFILLED,
        currency=store.currency,
        notes=notes or f"فروش حضوری صندوق {session.terminal.name}",
        created_by=user
    )

    total_amount = Decimal('0')

    for item in items_data:
        variant_id = item.get('variant_id')
        qty = int(item.get('quantity', 1))
        unit_price = Decimal(str(item.get('unit_price', 0)))

        variant = ProductVariant.objects.get(id=variant_id, store=store)
        if unit_price <= 0:
            unit_price = variant.retail_price

        row_total = unit_price * qty
        total_amount += row_total

        from apps.inventory.services import InsufficientStockError
        try:
            # Atomic stock sale deduction from terminal warehouse
            commit_stock_sale(
                store=store,
                warehouse=warehouse,
                variant=variant,
                quantity=qty,
                reference=order.order_number,
                user=user,
                is_reservation=False
            )
        except InsufficientStockError as e:
            raise ValidationError(f"موجودی کافی در انبار {warehouse.name} برای تنوع {variant.sku} وجود ندارد: {str(e)}")

        OrderItem.objects.create(
            order=order,
            variant=variant,
            variant_sku=variant.sku,
            variant_name=variant.name or variant.product.name,
            quantity=qty,
            unit_price=unit_price,
            cost_price_snapshot=variant.cost_price or Decimal('0'),
            total_price=row_total
        )

    order.total_items_price = total_amount
    order.grand_total = total_amount
    order.save()

    # Create Instant Verified Payment
    PaymentTransaction.objects.create(
        store=store,
        order=order,
        method=payment_method,
        amount=total_amount,
        currency=store.currency,
        status=PaymentVerificationStatus.VERIFIED,
        reference_number=f"POS-{uuid.uuid4().hex[:8].upper()}",
        tracking_code=f"TRK-{uuid.uuid4().hex[:6].upper()}",
        verified_by=user,
        verified_at=timezone.now()
    )

    # Increment session totals
    session.total_sales += total_amount
    session.save()

    record_audit_event(
        store=store,
        user=user,
        action="POS_QUICK_SALE",
        target_type="Order",
        target_id=str(order.id),
        changes={
            'order_number': order.order_number,
            'grand_total': str(total_amount),
            'terminal': session.terminal.name,
            'items_count': len(items_data)
        }
    )

    return order


@transaction.atomic
def convert_proforma_to_order(proforma, user=None):
    """
    Convert an accepted B2B proforma invoice into a confirmed order,
    reserving warehouse stock and updating client accounts receivable ledger.
    """
    proforma = ProformaInvoice.objects.select_for_update().get(id=proforma.id)
    if proforma.status == ProformaStatus.CONVERTED:
        raise ValidationError("این پیش‌فاکتور قبلاً به سفارش نهایی تبدیل شده است.")

    client = B2BClientProfile.objects.select_for_update().get(id=proforma.client_id)
    store = proforma.store

    if not client.is_approved:
        raise ValidationError(f"حساب مشتری عمده‌فروش '{client.company_name}' هنوز توسط مدیریت تأیید نشده است.")

    # Credit limit check
    if client.current_debt + proforma.grand_total > client.credit_limit:
        raise ValidationError(
            f"مبلغ این سفارش ({proforma.grand_total:,} تومان) از سقف اعتبار باقیمانده همکار ({client.available_credit:,} تومان) فراتر می‌رود."
        )

    warehouse = Warehouse.objects.filter(store=store).first()
    if not warehouse:
        raise ValidationError("هیچ انباری در فروشگاه ثبت نشده است.")

    order_number = f"B2B-{timezone.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    order = Order.objects.create(
        store=store,
        order_number=order_number,
        channel=OrderChannel.MANUAL,
        customer=client.customer,
        warehouse=warehouse,
        order_status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.PENDING,
        fulfillment_status=FulfillmentStatus.UNFULFILLED,
        currency=store.currency,
        total_items_price=proforma.subtotal,
        discount_amount=proforma.discount,
        tax_amount=proforma.tax,
        grand_total=proforma.grand_total,
        notes=f"تبدیل‌شده از پیش‌فاکتور {proforma.invoice_number}. {proforma.notes}",
        created_by=user
    )

    # Process items and reserve stock
    for item in proforma.items:
        variant_id = item.get('variant_id')
        qty = int(item.get('quantity', 1))
        unit_price = Decimal(str(item.get('unit_price', 0)))

        variant = ProductVariant.objects.get(id=variant_id, store=store)
        row_total = unit_price * qty

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
            variant_name=variant.name or variant.product.name,
            quantity=qty,
            unit_price=unit_price,
            cost_price_snapshot=variant.cost_price or Decimal('0'),
            total_price=row_total
        )

    # Update Client Debt
    client.current_debt += proforma.grand_total
    client.save()

    # Create Accounts Receivable Record
    due_date = (timezone.now() + timezone.timedelta(days=client.payment_terms_days)).date()
    AccountsPayableReceivable.objects.create(
        store=store,
        entity_type=DebtEntityType.CUSTOMER_CREDIT,
        customer=client.customer,
        title=f"طلب نسیه بابت سفارش عمده {order.order_number} (پیش‌فاکتور {proforma.invoice_number})",
        total_amount=proforma.grand_total,
        paid_amount=Decimal('0'),
        due_date=due_date,
        status=DebtStatus.PENDING,
        notes=f"مشتری همکار: {client.company_name} - مهلت تسویه: {client.payment_terms_days} روز"
    )

    # Mark Proforma as Converted
    proforma.status = ProformaStatus.CONVERTED
    proforma.save()

    record_audit_event(
        store=store,
        user=user,
        action="PROFORMA_CONVERTED_TO_ORDER",
        target_type="ProformaInvoice",
        target_id=str(proforma.id),
        changes={
            'order_number': order.order_number,
            'client': client.company_name,
            'grand_total': str(proforma.grand_total)
        }
    )

    return order


@transaction.atomic
def create_quick_sku_order(store, client, sku_items, notes='', user=None):
    """
    Rapid wholesale ordering using SKU list.
    Applies volume tier pricing and MOQ, generates a formal B2B Proforma.
    Enforces client approval and pessimistic credit limit verification.
    """
    if not sku_items:
        raise ValidationError("حداقل یک قلم کالا با کد SKU الزامی است.")

    # Concurrency safe client retrieval & approval check
    client = B2BClientProfile.objects.select_for_update().get(id=client.id, store=store)
    if not client.is_approved:
        raise ValidationError(f"حساب مشتری عمده‌فروش '{client.company_name}' هنوز توسط مدیریت تأیید نشده است.")

    from datetime import timedelta
    items_json = []
    subtotal = Decimal('0')

    for entry in sku_items:
        sku = str(entry.get('sku', '')).strip()
        quantity = int(entry.get('quantity', 1))
        if quantity <= 0:
            raise ValidationError(f"تعداد برای کد {sku} باید بزرگتر از صفر باشد.")

        variant = ProductVariant.objects.filter(store=store, sku__iexact=sku).first()
        if not variant:
            raise ValidationError(f"کالایی با کد {sku} در انبار این فروشگاه یافت نشد.")

        # Check for Volume Tier Discount
        tier = VolumeTierDiscount.objects.filter(
            store=store,
            variant=variant,
            min_quantity__lte=quantity
        ).order_by('-min_quantity').first()

        if tier:
            unit_price = tier.unit_price
        elif variant.wholesale_price > Decimal('0'):
            unit_price = variant.wholesale_price
        else:
            unit_price = variant.retail_price

        row_total = unit_price * quantity
        subtotal += row_total

        items_json.append({
            'variant_id': str(variant.id),
            'sku': variant.sku,
            'name': f"{variant.product.name} - {variant.name}",
            'quantity': quantity,
            'unit_price': str(unit_price),
            'total_price': str(row_total),
            'tier_applied': tier.tier_label if tier else 'قیمت عمده استاندارد'
        })

    # Credit limit validation under select_for_update lock
    if client.current_debt + subtotal > client.credit_limit:
        raise ValidationError(
            f"مبلغ این سفارش ({subtotal:,} تومان) از سقف اعتبار باقیمانده همکار ({client.available_credit:,} تومان) فراتر می‌رود."
        )

    invoice_number = f"PI-SKU-{timezone.now().strftime('%y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
    valid_until = timezone.now() + timedelta(days=client.payment_terms_days or 14)

    proforma = ProformaInvoice.objects.create(
        store=store,
        invoice_number=invoice_number,
        client=client,
        subtotal=subtotal,
        discount=Decimal('0'),
        tax=Decimal('0'),
        grand_total=subtotal,
        status=ProformaStatus.SENT,
        valid_until=valid_until,
        items=items_json,
        notes=notes or f"ثبت سفارش سریع بر اساس کد SKU برای {client.company_name}"
    )

    record_audit_event(
        store=store,
        user=user,
        action="WHOLESALE_QUICK_SKU_ORDER",
        target_type="ProformaInvoice",
        target_id=str(proforma.id),
        changes={'client': client.company_name, 'grand_total': str(subtotal), 'items_count': len(items_json)}
    )
    return proforma


def generate_pos_receipt(store, order_id):
    """
    Constructs a receipt data structure and formatted 80mm thermal receipt text
    for point-of-sale customer receipts.
    """
    order = Order.objects.filter(store=store, id=order_id).select_related('customer', 'warehouse', 'created_by').prefetch_related('items').first()
    if not order:
        raise ValidationError("سفارش مورد نظر یافت نشد.")

    items_list = []
    for item in order.items.all():
        items_list.append({
            'sku': item.variant_sku,
            'name': item.variant_name,
            'quantity': item.quantity,
            'unit_price': int(item.unit_price),
            'discount': int(item.unit_discount * item.quantity),
            'total_price': int(item.total_price)
        })

    created_at_str = order.created_at.strftime('%Y/%m/%d %H:%M') if order.created_at else ''
    cashier = order.created_by.get_full_name() if order.created_by and hasattr(order.created_by, 'get_full_name') else (order.created_by.phone if order.created_by else 'صندوقدار')

    receipt_lines = [
        "=" * 40,
        f"{store.name.center(40)}",
        f"فاکتور فروش صندوق حضوری".center(40),
        "=" * 40,
        f"شماره فاکتور: {order.order_number}",
        f"تاریخ و ساعت: {created_at_str}",
        f"صندوقدار: {cashier}",
        f"مشتری: {order.customer.full_name} ({order.customer.phone_number})",
        "-" * 40,
        f"{'شرح کالا':<20}{'تعداد':^6}{'مبلغ کل (تومان)':>14}",
        "-" * 40,
    ]

    for it in items_list:
        name_trunc = it['name'][:18]
        receipt_lines.append(f"{name_trunc:<20}{it['quantity']:^6}{it['total_price']:>14,}")

    receipt_lines.extend([
        "-" * 40,
        f"مجموع اقلام: {int(order.total_items_price):,}",
        f"تخفیف: {int(order.discount_amount):,}",
        f"مالیات: {int(order.tax_amount):,}",
        "=" * 40,
        f"مبلغ قابل پرداخت: {int(order.grand_total):,} تومان",
        "=" * 40,
        "از خرید و اعتماد شما سپاسگزاریم".center(40),
        "امکان تعویض یا مرجوعی کالا تا ۷ روز با فاکتور".center(40),
        "=" * 40,
    ])

    return {
        'store': {
            'id': str(store.id),
            'name': store.name,
            'currency': order.currency
        },
        'order': {
            'id': str(order.id),
            'order_number': order.order_number,
            'created_at': created_at_str,
            'cashier': cashier,
            'payment_status': order.get_payment_status_display(),
            'channel': order.get_channel_display()
        },
        'customer': {
            'name': order.customer.full_name,
            'phone': order.customer.phone_number
        },
        'items': items_list,
        'financials': {
            'total_items_price': int(order.total_items_price),
            'discount_amount': int(order.discount_amount),
            'shipping_cost': int(order.shipping_cost),
            'tax_amount': int(order.tax_amount),
            'grand_total': int(order.grand_total)
        },
        'thermal_receipt_text': "\n".join(receipt_lines)
    }

