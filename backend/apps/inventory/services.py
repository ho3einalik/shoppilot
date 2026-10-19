import random
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from .models import (
    InventoryBalance, InventoryMovement, MovementType, Warehouse,
    StockCycleCount, StockCycleCountItem, CycleCountStatus,
    StockReservation, ReservationStatus
)
from apps.audit.services import record_audit_event

class InsufficientStockError(Exception):
    pass

@transaction.atomic
def get_or_create_balance(store, warehouse, variant):
    if warehouse.store_id != store.id:
        raise ValidationError("انبار انتخابی متعلق به این فروشگاه نیست.")
    if variant.product.store_id != store.id:
        raise ValidationError("تنوع کالای انتخابی متعلق به این فروشگاه نیست.")

    balance, _ = InventoryBalance.objects.select_for_update().get_or_create(
        store=store,
        warehouse=warehouse,
        variant=variant,
        defaults={
            'on_hand_quantity': 0,
            'reserved_quantity': 0,
            'quarantined_quantity': 0,
            'incoming_quantity': 0,
        }
    )
    return balance


@transaction.atomic
def reserve_stock(store, warehouse, variant, quantity, reference='', user=None):
    """Pessimistically lock the balance row and reserve stock for an order with scoped StockReservation tracking"""
    if quantity <= 0:
        raise ValueError("Quantity to reserve must be greater than zero.")

    balance = get_or_create_balance(store, warehouse, variant)
    available = balance.available

    if available < quantity:
        raise InsufficientStockError(
            f"موجودی کافی نیست برای {variant.sku}. موجودی قابل فروش: {available}، مقدار درخواستی: {quantity}"
        )

    balance.reserved_quantity += quantity
    balance.save(update_fields=['reserved_quantity', 'updated_at'])

    # Track scoped reservation per order reference
    if reference:
        StockReservation.objects.create(
            store=store,
            order_number=reference,
            warehouse=warehouse,
            variant=variant,
            quantity=quantity,
            fulfilled_quantity=0,
            status=ReservationStatus.ACTIVE
        )

    # Record movement
    InventoryMovement.objects.create(
        store=store,
        warehouse=warehouse,
        variant=variant,
        movement_type=MovementType.RESERVATION,
        quantity=quantity,
        balance_after=balance.on_hand_quantity,
        reference=reference,
        reason=f"رزرو برای سفارش {reference}",
        user=user
    )
    return balance

@transaction.atomic
def release_stock_reservation(store, warehouse, variant, quantity, reference='', user=None):
    """Release previously reserved stock scoped to the specific order reference"""
    if quantity <= 0:
        return None

    balance = get_or_create_balance(store, warehouse, variant)

    if reference:
        matching_reservations = list(StockReservation.objects.select_for_update().filter(
            store=store,
            order_number=reference,
            warehouse=warehouse,
            variant=variant,
            status=ReservationStatus.ACTIVE
        ))
        total_order_active = sum(r.quantity - r.fulfilled_quantity for r in matching_reservations)
        if total_order_active <= 0:
            # Order has no active reservation to release
            return balance

        release_qty = min(quantity, total_order_active)
        needed_release = release_qty
        for r in matching_reservations:
            rem = r.quantity - r.fulfilled_quantity
            take = min(needed_release, rem)
            r.quantity -= take
            if r.quantity <= r.fulfilled_quantity:
                r.status = ReservationStatus.RELEASED
            r.save(update_fields=['quantity', 'status', 'updated_at'])
            needed_release -= take
            if needed_release == 0:
                break
    else:
        release_qty = min(quantity, balance.reserved_quantity)

    balance.reserved_quantity = max(0, balance.reserved_quantity - release_qty)
    balance.save(update_fields=['reserved_quantity', 'updated_at'])

    InventoryMovement.objects.create(
        store=store,
        warehouse=warehouse,
        variant=variant,
        movement_type=MovementType.RESERVATION_RELEASE,
        quantity=-release_qty,
        balance_after=balance.on_hand_quantity,
        reference=reference,
        reason=f"آزادسازی رزرو برای سفارش {reference}",
        user=user
    )
    return balance

@transaction.atomic
def commit_stock_sale(store, warehouse, variant, quantity, reference='', user=None, is_reservation=True):
    """
    Deducts stock for an actual sale with strict inventory check and scoped reservation protection.
    If is_reservation=True (default for fulfilling previously reserved orders):
        - Strictly verifies on_hand_quantity >= quantity.
        - If reference is provided:
            * Scans active StockReservation records for this specific order.
            * Consumes ONLY this order's reservations (marking fulfilled).
            * If order had NO reservation: strictly requires unreserved stock (available >= quantity)
              and does NOT decrement global reserved_quantity (preventing stealing other orders' reservations).
            * If order had partial reservation: fulfills what it had, verifies available stock for the remainder.
        - If reference is empty: falls back to generic deduction min(quantity, reserved_quantity).
    If is_reservation=False (for direct/walk-in sales or exchange returns without prior reservation):
        - Strictly verifies unreserved stock (available >= quantity).
        - Deducts quantity from on_hand_quantity ONLY, protecting all orders' reserved stock.
    """
    if quantity <= 0:
        return None

    balance = get_or_create_balance(store, warehouse, variant)

    # Strictly verify physical on-hand quantity
    if balance.on_hand_quantity < quantity:
        raise InsufficientStockError(
            f"موجودی فیزیکی در انبار {warehouse.name} برای {variant.sku} کافی نیست. "
            f"موجودی فیزیکی موجود: {balance.on_hand_quantity}، مقدار درخواستی: {quantity}"
        )

    if is_reservation:
        if reference:
            order_reservations = list(StockReservation.objects.select_for_update().filter(
                store=store,
                order_number=reference,
                warehouse=warehouse,
                variant=variant,
                status=ReservationStatus.ACTIVE
            ))
            order_active_res = sum(r.quantity - r.fulfilled_quantity for r in order_reservations)

            if order_active_res >= quantity:
                # Fully covered by this order's scoped reservation
                needed = quantity
                for r in order_reservations:
                    rem = r.quantity - r.fulfilled_quantity
                    take = min(needed, rem)
                    r.fulfilled_quantity += take
                    if r.fulfilled_quantity >= r.quantity:
                        r.status = ReservationStatus.FULFILLED
                    r.save(update_fields=['fulfilled_quantity', 'status', 'updated_at'])
                    needed -= take
                    if needed == 0:
                        break

                balance.reserved_quantity = max(0, balance.reserved_quantity - quantity)
                balance.on_hand_quantity -= quantity
            elif order_active_res > 0:
                # Partially covered by this order's reservation
                partial_res = order_active_res
                unreserved_needed = quantity - partial_res
                if balance.available < unreserved_needed:
                    raise InsufficientStockError(
                        f"موجودی آزاد کافی برای تکمیل بخش بدون رزرو سفارش {reference} وجود ندارد. "
                        f"رزرو سفارش: {partial_res}، کسری بدون رزرو: {unreserved_needed}، موجودی آزاد: {balance.available}"
                    )
                for r in order_reservations:
                    r.fulfilled_quantity = r.quantity
                    r.status = ReservationStatus.FULFILLED
                    r.save(update_fields=['fulfilled_quantity', 'status', 'updated_at'])

                balance.reserved_quantity = max(0, balance.reserved_quantity - partial_res)
                balance.on_hand_quantity -= quantity
            else:
                # Order had NO active reservation! Cannot steal other orders' reservations.
                if balance.available < quantity:
                    raise InsufficientStockError(
                        f"سفارش {reference} رزروی برای این کالا ندارد و موجودی آزاد انبار ({balance.available}) کمتر از مقدار درخواستی ({quantity}) است. "
                        f"رزروهای موجود متعلق به سایر سفارش‌ها هستند و امکان مصرف آن‌ها وجود ندارد."
                    )
                balance.on_hand_quantity -= quantity
        else:
            # No order reference provided: fall back to generic deduction
            reserved_deduct = min(quantity, balance.reserved_quantity)
            balance.reserved_quantity = max(0, balance.reserved_quantity - reserved_deduct)
            balance.on_hand_quantity -= quantity

        movement_reason = f"تحویل سفارش {reference}"
    else:
        # Unreserved direct sale: must verify available stock (on_hand - reserved - quarantined)
        if balance.available < quantity:
            raise InsufficientStockError(
                f"موجودی آزاد در انبار {warehouse.name} برای {variant.sku} کافی نیست. "
                f"موجودی آزاد: {balance.available} (کل: {balance.on_hand_quantity}، رزرو شده: {balance.reserved_quantity})، مقدار درخواستی: {quantity}"
            )
        balance.on_hand_quantity -= quantity
        movement_reason = f"فروش مستقیم/تعویض کالا {reference}"

    balance.save(update_fields=['on_hand_quantity', 'reserved_quantity', 'updated_at'])

    InventoryMovement.objects.create(
        store=store,
        warehouse=warehouse,
        variant=variant,
        movement_type=MovementType.SALE,
        quantity=-quantity,
        balance_after=balance.on_hand_quantity,
        reference=reference,
        reason=movement_reason,
        user=user
    )
    return balance

@transaction.atomic
def transfer_stock(store, source_warehouse, dest_warehouse, variant, quantity, reference='', reason='', user=None):
    """Safely transfers stock between two warehouses of the same store with ledger entries"""
    if quantity <= 0:
        raise ValueError("تعداد انتقال باید بیشتر از صفر باشد.")
    if source_warehouse.id == dest_warehouse.id:
        raise ValueError("انبار مبدا و مقصد نمی‌تواند یکسان باشد.")
    if source_warehouse.store_id != store.id or dest_warehouse.store_id != store.id:
        raise ValidationError("انبارهای مبدا و مقصد باید متعلق به همین فروشگاه باشند.")

    src_balance = get_or_create_balance(store, source_warehouse, variant)
    if src_balance.available < quantity:
        raise InsufficientStockError(f"موجودی قابل انتقال در انبار مبدا کافی نیست: {src_balance.available}")

    dest_balance = get_or_create_balance(store, dest_warehouse, variant)

    src_balance.on_hand_quantity -= quantity
    src_balance.save()

    dest_balance.on_hand_quantity += quantity
    dest_balance.save()

    InventoryMovement.objects.create(
        store=store,
        warehouse=source_warehouse,
        variant=variant,
        movement_type=MovementType.TRANSFER_OUT,
        quantity=-quantity,
        balance_after=src_balance.on_hand_quantity,
        reference=reference or f"TRF-{dest_warehouse.name}",
        reason=reason or f"انتقال خروجی به انبار {dest_warehouse.name}",
        user=user
    )

    InventoryMovement.objects.create(
        store=store,
        warehouse=dest_warehouse,
        variant=variant,
        movement_type=MovementType.TRANSFER_IN,
        quantity=quantity,
        balance_after=dest_balance.on_hand_quantity,
        reference=reference or f"TRF-{source_warehouse.name}",
        reason=reason or f"انتقال ورودی از انبار {source_warehouse.name}",
        user=user
    )

    record_audit_event(
        store=store,
        user=user,
        action="STOCK_TRANSFERRED",
        target_type="ProductVariant",
        target_id=str(variant.id),
        changes={'source': source_warehouse.name, 'dest': dest_warehouse.name, 'quantity': quantity}
    )
    return src_balance, dest_balance

@transaction.atomic
def adjust_stock(store, warehouse, variant, new_on_hand, reason='', reference='', user=None):
    """Manual adjustment / stocktake reconciliation with audit trail"""
    if new_on_hand < 0:
        raise ValueError("موجودی فیزیکی جدید نمی‌تواند کمتر از صفر باشد.")

    balance = get_or_create_balance(store, warehouse, variant)
    old_on_hand = balance.on_hand_quantity
    diff = new_on_hand - old_on_hand

    balance.on_hand_quantity = new_on_hand

    balance.save()

    movement = InventoryMovement.objects.create(
        store=store,
        warehouse=warehouse,
        variant=variant,
        movement_type=MovementType.ADJUSTMENT,
        quantity=diff,
        balance_after=balance.on_hand_quantity,
        reference=reference or "MANUAL_ADJUSTMENT",
        reason=reason or "تعدیل دستی انبار",
        user=user
    )

    record_audit_event(
        store=store,
        user=user,
        action="STOCK_ADJUSTED",
        target_type="ProductVariant",
        target_id=str(variant.id),
        changes={'old_on_hand': old_on_hand, 'new_on_hand': new_on_hand, 'diff': diff, 'reason': reason}
    )
    return balance

@transaction.atomic
def receive_stock(store, warehouse, variant, quantity, unit_cost=None, reference='', reason='', user=None):
    """Receive new inventory from supplier purchase order or goods receipt"""
    if quantity <= 0:
        raise ValueError("تعداد ورودی کالا باید بیشتر از صفر باشد.")

    balance = get_or_create_balance(store, warehouse, variant)
    balance.on_hand_quantity += quantity
    balance.save()

    # If incoming quantity was tracked, adjust it
    if balance.incoming_quantity > 0:
        balance.incoming_quantity = max(0, balance.incoming_quantity - quantity)
        balance.save()

    # Optionally update cost price on variant if provided
    if unit_cost is not None and unit_cost > 0:
        variant.cost_price = unit_cost
        variant.save(update_fields=['cost_price', 'updated_at'])

    InventoryMovement.objects.create(
        store=store,
        warehouse=warehouse,
        variant=variant,
        movement_type=MovementType.RECEIPT,
        quantity=quantity,
        balance_after=balance.on_hand_quantity,
        reference=reference or "GOODS_RECEIPT",
        reason=reason or f"ورود کالا از فاکتور خرید {reference}",
        user=user
    )

    record_audit_event(
        store=store,
        user=user,
        action="STOCK_RECEIVED",
        target_type="ProductVariant",
        target_id=str(variant.id),
        changes={'quantity_received': quantity, 'new_on_hand': balance.on_hand_quantity, 'reference': reference}
    )
    return balance

@transaction.atomic
def process_return_stock(store, warehouse, variant, quantity, is_sellable=True, reference='', reason='', user=None):
    """Process customer return into stock (sellable restock or quarantine)"""
    if quantity <= 0:
        raise ValueError("تعداد کالای مرجوعی باید بیشتر از صفر باشد.")

    balance = get_or_create_balance(store, warehouse, variant)

    if is_sellable:
        balance.on_hand_quantity += quantity
        movement_type = MovementType.RETURN
        movement_reason = reason or f"بازگشت کالای سالم به موجودی فروش (RMA: {reference})"
    else:
        balance.on_hand_quantity += quantity
        balance.quarantined_quantity += quantity
        movement_type = MovementType.DAMAGE
        movement_reason = reason or f"قرنطینه کالای مرجوعی معیوب / غیرقابل فروش (RMA: {reference})"

    balance.save()

    InventoryMovement.objects.create(
        store=store,
        warehouse=warehouse,
        variant=variant,
        movement_type=movement_type,
        quantity=quantity,
        balance_after=balance.on_hand_quantity,
        reference=reference or "RMA_RETURN",
        reason=movement_reason,
        user=user
    )

    record_audit_event(
        store=store,
        user=user,
        action="RETURN_PROCESSED",
        target_type="ProductVariant",
        target_id=str(variant.id),
        changes={'quantity': quantity, 'is_sellable': is_sellable, 'reference': reference}
    )
    return balance


@transaction.atomic
def start_cycle_count(store, warehouse, variant_ids=None, notes='', user=None):
    """
    Initializes a stock cycle count / audit session for a warehouse.
    Takes a snapshot of system on-hand balances for included variants.
    """
    if warehouse.store_id != store.id:
        raise ValidationError("انبار انتخابی متعلق به این فروشگاه نیست.")

    # Check for active cycle counts on this warehouse
    active_count = StockCycleCount.objects.filter(
        store=store,
        warehouse=warehouse,
        status__in=[CycleCountStatus.DRAFT, CycleCountStatus.IN_PROGRESS]
    ).first()
    if active_count:
        raise ValidationError(f"یک انبارگردانی در حال انجام ({active_count.count_number}) برای این انبار وجود دارد.")

    date_str = timezone.now().strftime('%y%m%d')
    suffix = random.randint(1000, 9999)
    count_number = f"CC-{date_str}-{suffix}"

    cycle_count = StockCycleCount.objects.create(
        store=store,
        warehouse=warehouse,
        count_number=count_number,
        status=CycleCountStatus.IN_PROGRESS,
        started_at=timezone.now(),
        counted_by=user,
        notes=notes
    )

    from apps.catalog.models import ProductVariant
    if variant_ids:
        variants = ProductVariant.objects.filter(store=store, id__in=variant_ids)
    else:
        variants = ProductVariant.objects.filter(store=store, is_active=True)

    items = []
    for var in variants:
        balance = InventoryBalance.objects.filter(warehouse=warehouse, variant=var).first()
        system_qty = balance.on_hand_quantity if balance else 0
        items.append(
            StockCycleCountItem(
                cycle_count=cycle_count,
                variant=var,
                system_quantity=system_qty,
                counted_quantity=None,
                is_reconciled=False
            )
        )

    StockCycleCountItem.objects.bulk_create(items)

    record_audit_event(
        store=store,
        user=user,
        action="CYCLE_COUNT_STARTED",
        target_type="StockCycleCount",
        target_id=str(cycle_count.id),
        changes={'count_number': count_number, 'items_count': len(items)}
    )
    return cycle_count


@transaction.atomic
def record_cycle_count_items(cycle_count, items_data, user=None):
    """
    Records physical counts on cycle count items.
    items_data: list of dicts with {'variant_id': ..., 'counted_quantity': ..., 'notes': ...}
    """
    cycle_count = StockCycleCount.objects.select_for_update().get(id=cycle_count.id)
    if cycle_count.status not in [CycleCountStatus.DRAFT, CycleCountStatus.IN_PROGRESS]:
        raise ValidationError(f"تنها انبارگردانی‌های در حال انجام قابل ثبت شمارش هستند. وضعیت فعلی: {cycle_count.get_status_display()}")

    items_dict = {str(item.variant_id): item for item in cycle_count.items.select_for_update()}

    for entry in items_data:
        var_id = str(entry['variant_id'])
        item = items_dict.get(var_id)
        if not item:
            continue

        counted_qty = int(entry['counted_quantity'])
        if counted_qty < 0:
            raise ValidationError(f"موجودی شمارش‌شده نمی‌تواند منفی باشد ({counted_qty}).")

        item.counted_quantity = counted_qty
        if 'notes' in entry:
            item.notes = entry['notes']
        item.save()

    return cycle_count


@transaction.atomic
def reconcile_cycle_count(cycle_count, user=None):
    """
    Reconciles inventory based on physical counts.
    Generates ADJUSTMENT ledger entries for variances, then completes the cycle count.
    """
    cycle_count = StockCycleCount.objects.select_for_update().get(id=cycle_count.id)
    if cycle_count.status != CycleCountStatus.IN_PROGRESS:
        raise ValidationError(f"تنها انبارگردانی در حال انجام قابل تطبیق است. وضعیت فعلی: {cycle_count.get_status_display()}")

    items = list(cycle_count.items.select_for_update().select_related('variant'))
    uncounted = [it for it in items if it.counted_quantity is None]
    if uncounted:
        raise ValidationError(f"تعداد {len(uncounted)} قلم کالا هنوز شمارش فیزیکی نشده‌اند و نمی‌توان انبارگردانی را نهایی کرد.")

    reconciled_count = 0
    adjusted_count = 0

    for item in items:
        if not item.is_reconciled:
            diff = item.counted_quantity - item.system_quantity
            if diff != 0:
                adjust_stock(
                    store=cycle_count.store,
                    warehouse=cycle_count.warehouse,
                    variant=item.variant,
                    new_on_hand=item.counted_quantity,
                    reason=f"تطبیق انبارگردانی {cycle_count.count_number} (اختلاف: {diff:+d})",
                    user=user
                )
                adjusted_count += 1

            item.is_reconciled = True
            item.save(update_fields=['is_reconciled'])
            reconciled_count += 1

    cycle_count.status = CycleCountStatus.COMPLETED
    cycle_count.completed_at = timezone.now()
    cycle_count.reconciled_by = user
    cycle_count.save(update_fields=['status', 'completed_at', 'reconciled_by', 'updated_at'])

    record_audit_event(
        store=cycle_count.store,
        user=user,
        action="CYCLE_COUNT_RECONCILED",
        target_type="StockCycleCount",
        target_id=str(cycle_count.id),
        changes={
            'count_number': cycle_count.count_number,
            'reconciled_items': reconciled_count,
            'adjusted_items': adjusted_count
        }
    )
    return cycle_count


@transaction.atomic
def cancel_cycle_count(cycle_count, reason='', user=None):
    cycle_count = StockCycleCount.objects.select_for_update().get(id=cycle_count.id)
    if cycle_count.status == CycleCountStatus.COMPLETED:
        raise ValidationError("انبارگردانی تکمیل‌شده قابل لغو نیست.")

    cycle_count.status = CycleCountStatus.CANCELLED
    if reason:
        cycle_count.notes = f"{cycle_count.notes}\nدلیل لغو: {reason}".strip()
    cycle_count.save(update_fields=['status', 'notes', 'updated_at'])

    record_audit_event(
        store=cycle_count.store,
        user=user,
        action="CYCLE_COUNT_CANCELLED",
        target_type="StockCycleCount",
        target_id=str(cycle_count.id),
        changes={'reason': reason}
    )
    return cycle_count


