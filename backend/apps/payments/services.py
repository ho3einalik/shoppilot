from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import PaymentTransaction, PaymentVerificationStatus
from apps.orders.models import Order, PaymentStatus
from apps.audit.services import record_audit_event

@transaction.atomic
def verify_payment_transaction(payment, user):
    """Manually approves card-to-card or gateway transaction and syncs order payment status idempotently"""
    payment = PaymentTransaction.objects.select_for_update().get(id=payment.id)
    if payment.status == PaymentVerificationStatus.VERIFIED:
        return payment

    # Lock order and check total net verified payments (amount - refunded_amount) to prevent overpayment race conditions
    order = Order.objects.select_for_update().get(id=payment.order_id)
    total_verified = sum(
        max(Decimal('0'), p.amount - (getattr(p, 'refunded_amount', Decimal('0')) or Decimal('0')))
        for p in order.payments.filter(
            status__in=[PaymentVerificationStatus.VERIFIED, PaymentVerificationStatus.REFUNDED]
        ).exclude(id=payment.id)
    )

    from .models import PaymentMethod
    is_online = payment.method == PaymentMethod.ONLINE_GATEWAY
    curr_refunded = getattr(payment, 'refunded_amount', Decimal('0')) or Decimal('0')
    payment_net = max(Decimal('0'), payment.amount - curr_refunded)
    is_overpayment = (total_verified + payment_net) > order.grand_total

    if is_overpayment and not is_online:
        from rest_framework.exceptions import ValidationError
        raise ValidationError(
            f"تأیید این تراکنش باعث پرداخت بیش از سقف سفارش خواهد شد. مجموع تأییدشده خالص: {total_verified}، تراکنش فعلی: {payment.amount}، مبلغ کل: {order.grand_total}"
        )

    excess_amount = max(Decimal('0'), (total_verified + payment_net) - order.grand_total)

    payment.status = PaymentVerificationStatus.VERIFIED
    payment.verified_by = user
    payment.verified_at = timezone.now()
    if excess_amount > 0:
        overpay_note = f"[اضافه پرداخت معلق] مبلغ {excess_amount:,.0f} {payment.currency} مازاد بر مبلغ کل سفارش پرداخت شده است (تأیید دیرهنگام تراکنش). در انتظار استرداد وجه."
        payment.rejection_reason = f"{payment.rejection_reason} | {overpay_note}" if payment.rejection_reason else overpay_note
    payment.save()

    new_total_verified = total_verified + payment_net
    if new_total_verified >= order.grand_total:
        order.payment_status = PaymentStatus.PAID
    elif new_total_verified > 0:
        order.payment_status = PaymentStatus.PARTIALLY_PAID
    else:
        order.payment_status = PaymentStatus.PENDING
    order.save()

    record_audit_event(
        store=payment.store,
        user=user,
        action="PAYMENT_VERIFIED" if excess_amount == 0 else "OVERPAYMENT_VERIFIED",
        target_type="PaymentTransaction",
        target_id=str(payment.id),
        changes={
            'order_number': order.order_number,
            'amount': str(payment.amount),
            'excess_amount': str(excess_amount),
            'order_payment_status': order.payment_status
        }
    )

    if excess_amount > 0:
        # Attempt automatic refund if gateway refund credentials exist or manual refund can be staged
        try:
            process_payment_refund(
                payment=payment,
                amount=excess_amount,
                reason="استرداد اضافه پرداخت سفارش ناشی از تایید دیرهنگام تراکنش",
                user=user,
                is_manual=None
            )
        except Exception as exc:
            # If auto-refund cannot be executed immediately (e.g. gateway error/missing credentials),
            # mark as queued for background retry and audit log.
            payment.refresh_from_db()
            fail_note = f"[اضافه پرداخت - استرداد ناموفق/معلق] خطا در درگاه: {str(exc)}. در صف تلاش مجدد."
            payment.rejection_reason = f"{payment.rejection_reason} | {fail_note}" if payment.rejection_reason else fail_note
            payment.save(update_fields=['rejection_reason'])

    if order.payment_status == PaymentStatus.PAID:
        from apps.automation.services import publish_outbox_event
        from apps.automation.models import TriggerEvent
        publish_outbox_event(
            store=payment.store,
            event_type=TriggerEvent.ORDER_PAID,
            payload={
                'order_id': str(order.id),
                'order_number': order.order_number,
                'customer_name': order.customer.full_name if order.customer else '',
                'customer_phone': order.customer.phone_number if order.customer else '',
                'amount': float(payment.amount),
                'excess_amount': float(excess_amount),
                'idempotency_key': f"order_paid_{order.id}"
            },
            event_key=f"order_paid_{order.id}"
        )

    return payment

@transaction.atomic
def reject_payment_transaction(payment, reason, user):
    """Rejects card-to-card payment transaction with reason idempotently"""
    payment = PaymentTransaction.objects.select_for_update().get(id=payment.id)
    if payment.status == PaymentVerificationStatus.REJECTED:
        return payment

    payment.status = PaymentVerificationStatus.REJECTED
    payment.rejection_reason = reason
    payment.verified_by = user
    payment.verified_at = timezone.now()
    payment.save()

    order = Order.objects.select_for_update().get(id=payment.order_id)
    total_verified = sum(
        p.amount for p in order.payments.filter(status=PaymentVerificationStatus.VERIFIED)
    )
    if total_verified == 0:
        order.payment_status = PaymentStatus.PENDING
    elif total_verified < order.grand_total:
        order.payment_status = PaymentStatus.PARTIALLY_PAID
    order.save()

    record_audit_event(
        store=payment.store,
        user=user,
        action="PAYMENT_REJECTED",
        target_type="PaymentTransaction",
        target_id=str(payment.id),
        changes={'order_number': order.order_number, 'reason': reason}
    )
    return payment


@transaction.atomic
def process_payment_refund(payment, amount=None, reason="", user=None, is_manual=None):
    """
    Safely and idempotently refunds a verified payment transaction.
    Pessimistically locks PaymentTransaction and Order to prevent over-refunds.
    Supports partial and cumulative refunds.

    For online payment gateway transactions (method == PaymentMethod.ONLINE_GATEWAY):
    - If is_manual is False: caller explicitly demands automated gateway refund.
      Calls payment gateway refund API. If gateway is unconfigured or rejects,
      raises ValidationError instead of falsely recording successful refund.
    - If is_manual is True: staff explicitly chose manual refund (card-to-card/Paya),
      recorded as manual refund with audit trail.
    - If is_manual is None (default): if gateway credentials are fully configured,
      attempts gateway refund. If gateway is unconfigured, records as manual refund
      with an explicit audit note.
    """
    from rest_framework.exceptions import ValidationError
    from .models import PaymentMethod
    payment = PaymentTransaction.objects.select_for_update().get(id=payment.id)
    if payment.status not in [PaymentVerificationStatus.VERIFIED, PaymentVerificationStatus.REFUNDED]:
        raise ValidationError("تنها تراکنش‌های تأییدشده قابل استرداد (ریفاند) هستند.")

    order = Order.objects.select_for_update().get(id=payment.order_id)
    curr_refunded = getattr(payment, 'refunded_amount', Decimal('0')) or Decimal('0')
    remaining_refundable = payment.amount - curr_refunded

    if remaining_refundable <= Decimal('0'):
        raise ValidationError("این تراکنش قبلاً به طور کامل استرداد شده است.")

    refund_amount = Decimal(str(amount)) if amount is not None else remaining_refundable

    if refund_amount <= 0:
        raise ValidationError("مبلغ استرداد باید بزرگتر از صفر باشد.")

    if refund_amount > remaining_refundable:
        raise ValidationError(
            f"مبلغ درخواستی برای استرداد ({refund_amount}) نمی‌تواند از مانده قابل استرداد تراکنش ({remaining_refundable}) بیشتر باشد."
        )

    # Online gateway check: If online transaction and not marked as manual refund, call gateway refund API
    gateway_refund_ref = ""
    effective_manual = bool(is_manual) if is_manual is not None else False

    if payment.method == PaymentMethod.ONLINE_GATEWAY:
        from .gateways import get_payment_gateway
        gateway = get_payment_gateway('zarinpal')
        has_creds = gateway and hasattr(gateway, 'has_refund_credentials') and gateway.has_refund_credentials(payment.store)

        if is_manual is False or (is_manual is None and has_creds):
            if not gateway:
                raise ValidationError("درگاه پرداخت جهت استرداد آنلاین خودکار پیکربندی نشده است. در صورت بازگشت دستی وجه، گزینه «استرداد دستی» را انتخاب فرمایید.")

            res = gateway.refund_payment(
                authority=payment.reference_number,
                amount=refund_amount,
                store=payment.store,
                currency=payment.currency
            )
            if not res.success:
                raise ValidationError(
                    f"استرداد خودکار از طریق درگاه با خطا مواجه شد ({res.message}). "
                    "در صورت استرداد دستی وجه به حساب مشتری، گزینه «استرداد دستی» (is_manual=True) را انتخاب نمایید."
                )
            gateway_refund_ref = res.tracking_code
            effective_manual = False
        else:
            effective_manual = True
    else:
        effective_manual = True

    payment.refunded_amount = curr_refunded + refund_amount
    if payment.refunded_amount >= payment.amount:
        payment.status = PaymentVerificationStatus.REFUNDED

    prefix = "[استرداد دستی] " if effective_manual else ("[استرداد درگاه] " if payment.method == PaymentMethod.ONLINE_GATEWAY else "")
    extra = f" (کد پیگیری: {gateway_refund_ref})" if gateway_refund_ref else ""
    payment.rejection_reason = f"{prefix}مسترد شده: {reason}{extra} (مبلغ: {refund_amount})" if reason else f"{prefix}مسترد شده{extra} (مبلغ: {refund_amount})"
    if gateway_refund_ref:
        payment.tracking_code = gateway_refund_ref
    payment.save(update_fields=['status', 'refunded_amount', 'rejection_reason', 'tracking_code', 'updated_at'])

    # Recalculate net verified paid across all payments for order
    all_order_payments = order.payments.all()
    net_verified = sum(
        max(Decimal('0'), p.amount - (getattr(p, 'refunded_amount', Decimal('0')) or Decimal('0')))
        for p in all_order_payments
        if p.status in [PaymentVerificationStatus.VERIFIED, PaymentVerificationStatus.REFUNDED]
    )

    if net_verified == 0:
        order.payment_status = PaymentStatus.REFUNDED
    elif net_verified < order.grand_total:
        order.payment_status = PaymentStatus.PARTIALLY_PAID
    else:
        order.payment_status = PaymentStatus.PAID
    order.save(update_fields=['payment_status', 'updated_at'])

    record_audit_event(
        store=payment.store,
        user=user,
        action="PAYMENT_REFUNDED",
        target_type="PaymentTransaction",
        target_id=str(payment.id),
        changes={
            'order_number': order.order_number,
            'refund_amount': str(refund_amount),
            'reason': reason,
            'is_manual': is_manual,
            'gateway_tracking_code': gateway_refund_ref
        }
    )
    return payment


def reconcile_pending_online_payments(store=None, max_age_hours=24):
    """
    Background reconciliation job for unresolved online payments.
    Examines PENDING_VERIFICATION online payments created more than 20 minutes ago.
    Verifies authority with the gateway:
    - If paid: verifies transaction and settles order.
    - If definitively failed / not found: marks EXPIRED.
    - If communication error: leaves for next cycle.
    """
    import datetime
    from .models import PaymentMethod
    now = timezone.now()
    cutoff_ttl = now - datetime.timedelta(minutes=20)
    cutoff_max = now - datetime.timedelta(hours=max_age_hours)

    qs = PaymentTransaction.objects.filter(
        method=PaymentMethod.ONLINE_GATEWAY,
        status=PaymentVerificationStatus.PENDING_VERIFICATION,
        created_at__lt=cutoff_ttl,
        created_at__gte=cutoff_max
    ).select_related('store', 'order')

    if store:
        qs = qs.filter(store=store)

    from .gateways import get_payment_gateway
    gateway = get_payment_gateway('zarinpal')

    reconciled = []
    expired = []
    errors = []

    for tx in qs:
        if not tx.reference_number or tx.reference_number.startswith('REQ_'):
            # Transaction was never assigned a gateway authority
            tx.status = PaymentVerificationStatus.EXPIRED
            tx.rejection_reason = "انقضای خودکار: شناسه درگاه دریافت نشد."
            tx.save(update_fields=['status', 'rejection_reason', 'updated_at'])
            expired.append(str(tx.id))
            continue

        try:
            res = gateway.verify_payment(
                authority=tx.reference_number,
                amount=tx.amount,
                store=tx.store,
                currency=tx.currency
            )
            if res.success:
                with transaction.atomic():
                    p = PaymentTransaction.objects.select_for_update().get(id=tx.id)
                    if p.status in [PaymentVerificationStatus.PENDING_VERIFICATION, PaymentVerificationStatus.EXPIRED]:
                        p.tracking_code = res.tracking_code
                        p.save(update_fields=['tracking_code'])
                        verify_payment_transaction(p, user=None)
                        reconciled.append(str(tx.id))
            elif res.status == 'COMMUNICATION_ERROR':
                errors.append({'id': str(tx.id), 'error': 'COMMUNICATION_ERROR'})
            else:
                with transaction.atomic():
                    p = PaymentTransaction.objects.select_for_update().get(id=tx.id)
                    if p.status == PaymentVerificationStatus.PENDING_VERIFICATION:
                        p.status = PaymentVerificationStatus.EXPIRED
                        p.rejection_reason = f"تطبیق خودکار: درگاه پرداخت تراکنش را رد یا منقضی اعلام کرد ({res.message})"
                        p.save(update_fields=['status', 'rejection_reason', 'updated_at'])
                        expired.append(str(tx.id))
        except Exception as exc:
            errors.append({'id': str(tx.id), 'error': str(exc)})

    return {
        'reconciled_count': len(reconciled),
        'reconciled_ids': reconciled,
        'expired_count': len(expired),
        'expired_ids': expired,
        'errors': errors
    }


def retry_pending_overpayment_refunds(store=None):
    """
    Background reconciliation job for unresolved overpayments.
    Scans verified transactions with unresolved overpayments and attempts to process refund.
    """
    import logging
    logger = logging.getLogger(__name__)

    qs = PaymentTransaction.objects.filter(
        status=PaymentVerificationStatus.VERIFIED,
        rejection_reason__contains="[اضافه پرداخت"
    ).select_related('order', 'store')
    if store:
        qs = qs.filter(store=store)

    results = {'attempted': 0, 'succeeded': 0, 'failed': 0, 'details': []}
    for payment in qs:
        try:
            with transaction.atomic():
                p = PaymentTransaction.objects.select_for_update().get(id=payment.id)
                order = Order.objects.select_for_update().get(id=p.order_id)
                all_payments = order.payments.filter(
                    status__in=[PaymentVerificationStatus.VERIFIED, PaymentVerificationStatus.REFUNDED]
                )
                total_net = sum(
                    max(Decimal('0'), tx.amount - (getattr(tx, 'refunded_amount', Decimal('0')) or Decimal('0')))
                    for tx in all_payments
                )
                if total_net <= order.grand_total:
                    continue

                excess_remaining = total_net - order.grand_total
                curr_refunded = getattr(p, 'refunded_amount', Decimal('0')) or Decimal('0')
                refundable_on_this_tx = max(Decimal('0'), p.amount - curr_refunded)
                amount_to_refund = min(excess_remaining, refundable_on_this_tx)

                if amount_to_refund <= Decimal('0'):
                    continue

                results['attempted'] += 1
                process_payment_refund(
                    payment=p,
                    amount=amount_to_refund,
                    reason="استرداد دوره‌ای اضافه پرداخت سفارش از صف پس‌زمینه",
                    user=None,
                    is_manual=None
                )
                results['succeeded'] += 1
                results['details'].append({'payment_id': str(p.id), 'amount': str(amount_to_refund), 'status': 'SUCCESS'})
                logger.info("Successfully retried overpayment refund for payment %s (amount %s)", p.id, amount_to_refund)
        except Exception as exc:
            results['failed'] += 1
            results['details'].append({'payment_id': str(payment.id), 'status': 'FAILED', 'error': str(exc)})
            logger.warning("Retry refund for overpayment %s failed: %s", payment.id, exc)

    return results


