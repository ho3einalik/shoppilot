import random
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import Supplier, PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus
from apps.inventory.services import receive_stock
from apps.audit.services import record_audit_event

def generate_po_number():
    date_str = timezone.now().strftime('%y%m%d')
    suffix = random.randint(1000, 9999)
    return f"PO-{date_str}-{suffix}"

@transaction.atomic
def create_purchase_order(store, supplier, warehouse, items_data, user=None, notes='', expected_delivery_date=None):
    if not items_data:
        raise ValidationError("سفارش خرید باید حداقل دارای یک ردیف کالا باشد.")

    po_number = generate_po_number()
    po = PurchaseOrder.objects.create(
        store=store,
        po_number=po_number,
        supplier=supplier,
        warehouse=warehouse,
        status=PurchaseOrderStatus.DRAFT,
        currency=store.currency,
        expected_delivery_date=expected_delivery_date,
        notes=notes,
        created_by=user,
        total_amount=Decimal('0')
    )

    total_amount = Decimal('0')
    for item in items_data:
        variant = item['variant']
        qty = int(item['quantity_ordered'])
        unit_cost = Decimal(str(item['unit_cost']))
        row_total = unit_cost * qty

        PurchaseOrderItem.objects.create(
            purchase_order=po,
            variant=variant,
            quantity_ordered=qty,
            quantity_received=0,
            unit_cost=unit_cost,
            total_cost=row_total
        )
        total_amount += row_total

    po.total_amount = total_amount
    po.save(update_fields=['total_amount'])

    record_audit_event(
        store=store,
        user=user,
        action="PURCHASE_ORDER_CREATED",
        target_type="PurchaseOrder",
        target_id=str(po.id),
        changes={'po_number': po.po_number, 'supplier': supplier.name, 'total_amount': str(total_amount)}
    )
    return po

@transaction.atomic
def approve_purchase_order(po, user=None):
    if po.status != PurchaseOrderStatus.DRAFT:
        raise ValidationError(f"تنها سفارشات در وضعیت پیش‌نویس قابل تایید هستند. وضعیت فعلی: {po.get_status_display()}")

    po.status = PurchaseOrderStatus.APPROVED
    po.save(update_fields=['status', 'updated_at'])

    record_audit_event(
        store=po.store,
        user=user,
        action="PURCHASE_ORDER_APPROVED",
        target_type="PurchaseOrder",
        target_id=str(po.id),
        changes={'new_status': po.status}
    )
    return po

@transaction.atomic
def mark_purchase_order_sent(po, user=None):
    if po.status not in [PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.APPROVED]:
        raise ValidationError(f"امکان ارسال سفارش خرید در وضعیت {po.get_status_display()} وجود ندارد.")

    po.status = PurchaseOrderStatus.SENT
    po.save(update_fields=['status', 'updated_at'])

    record_audit_event(
        store=po.store,
        user=user,
        action="PURCHASE_ORDER_SENT",
        target_type="PurchaseOrder",
        target_id=str(po.id),
        changes={'new_status': po.status}
    )
    return po

@transaction.atomic
def receive_po_goods(po, receipts_data, user=None):
    """
    Receive items into inventory warehouse with QC inspection and record Accounts Payable liability.
    receipts_data format: [
        {
            'item_id': uuid,
            'quantity_received': int,
            'quantity_accepted': int (optional, defaults to quantity_received - quantity_rejected),
            'quantity_rejected': int (optional, defaults to 0),
            'rejection_reason': str (optional),
            'inspection_notes': str (optional)
        }
    ]
    """
    from .models import GoodsReceiptInspection

    po = PurchaseOrder.objects.select_for_update().get(id=po.id)
    if po.status in [PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.CANCELLED, PurchaseOrderStatus.COMPLETED]:
        raise ValidationError(f"امکان رسید کالا برای این سفارش وجود ندارد (وضعیت: {po.get_status_display()})")

    items_dict = {str(item.id): item for item in po.items.select_for_update()}
    received_anything = False
    total_batch_cost = Decimal('0')

    for receipt in receipts_data:
        item_id = str(receipt.get('item_id', ''))
        try:
            qty_received = int(receipt.get('quantity_received', 0))
        except (ValueError, TypeError):
            continue

        item = items_dict.get(item_id)
        if not item:
            raise ValidationError(f"ردیف کالای انتخابی {item_id} در این سفارش خرید یافت نشد.")

        qty_rejected = int(receipt.get('quantity_rejected', 0))
        if 'quantity_accepted' in receipt:
            qty_accepted = int(receipt.get('quantity_accepted', 0))
            if qty_received <= 0:
                qty_received = qty_accepted + qty_rejected
        else:
            qty_accepted = max(0, qty_received - qty_rejected)

        if qty_received <= 0:
            continue

        if qty_accepted + qty_rejected > qty_received:
            raise ValidationError(
                f"مجموع اقلام تاییدشده ({qty_accepted}) و مردود ({qty_rejected}) نمی‌تواند از کل اقلام دریافتی ({qty_received}) بیشتر باشد."
            )

        if qty_received > item.remaining_quantity:
            raise ValidationError(
                f"تعداد ورودی ({qty_received}) برای {item.variant.sku} نمی‌تواند بیشتر از مانده سفارش ({item.remaining_quantity}) باشد."
            )

        rejection_reason = receipt.get('rejection_reason', '')
        inspection_notes = receipt.get('inspection_notes', '')

        # 1. Save Quality Control / Goods Receipt Inspection record
        GoodsReceiptInspection.objects.create(
            store=po.store,
            purchase_order=po,
            variant=item.variant,
            quantity_received=qty_received,
            quantity_accepted=qty_accepted,
            quantity_rejected=qty_rejected,
            rejection_reason=rejection_reason,
            inspection_notes=inspection_notes,
            inspected_by=user
        )

        # 2. ONLY quantity_accepted enters active warehouse inventory via receive_stock
        if qty_accepted > 0:
            receive_stock(
                store=po.store,
                warehouse=po.warehouse,
                variant=item.variant,
                quantity=qty_accepted,
                unit_cost=item.unit_cost,
                reference=po.po_number,
                reason=f"رسید انبار پس از بازرسی کیفیت از سفارش خرید {po.po_number}",
                user=user
            )

        item.quantity_received += qty_received
        item.save(update_fields=['quantity_received'])
        total_batch_cost += item.unit_cost * qty_accepted
        received_anything = True

    if not received_anything:
        raise ValidationError("هیچ کالایی با تعداد معتبر جهت تحویل و رسید انبار مشخص نشده است.")


    # Check overall PO completion status
    all_completed = all(i.is_fully_received for i in po.items.all())
    po.status = PurchaseOrderStatus.COMPLETED if all_completed else PurchaseOrderStatus.PARTIALLY_RECEIVED
    po.save(update_fields=['status', 'updated_at'])

    # Synchronize Accounts Payable (AP) liability in apps.finance
    if total_batch_cost > 0:
        try:
            from apps.finance.models import AccountsPayableReceivable, DebtEntityType, DebtStatus
            due_date = (timezone.now() + timezone.timedelta(days=po.supplier.lead_time_days or 30)).date()
            ap_record = AccountsPayableReceivable.objects.filter(
                store=po.store,
                supplier=po.supplier,
                title__contains=po.po_number
            ).first()

            if ap_record:
                ap_record.total_amount += total_batch_cost
                if ap_record.status == DebtStatus.SETTLED and ap_record.paid_amount < ap_record.total_amount:
                    ap_record.status = DebtStatus.PARTIALLY_PAID
                ap_record.save(update_fields=['total_amount', 'status', 'updated_at'])
            else:
                AccountsPayableReceivable.objects.create(
                    store=po.store,
                    entity_type=DebtEntityType.SUPPLIER_DEBT,
                    supplier=po.supplier,
                    title=f"بدهی بابت سفارش خرید {po.po_number}",
                    total_amount=total_batch_cost,
                    paid_amount=Decimal('0'),
                    due_date=due_date,
                    status=DebtStatus.PENDING,
                    notes=f"تامین‌کننده: {po.supplier.name} - انبار: {po.warehouse.name}"
                )
        except Exception:
            pass

    record_audit_event(
        store=po.store,
        user=user,
        action="PURCHASE_ORDER_GOODS_RECEIVED",
        target_type="PurchaseOrder",
        target_id=str(po.id),
        changes={'status': po.status, 'receipts_count': len(receipts_data), 'batch_cost': str(total_batch_cost)}
    )
    return po
