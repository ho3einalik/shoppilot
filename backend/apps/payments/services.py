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

    # Lock order and check total verified payments to prevent overpayment race conditions
    order = Order.objects.select_for_update().get(id=payment.order_id)
    total_verified = sum(
        p.amount for p in order.payments.filter(status=PaymentVerificationStatus.VERIFIED)
    )

    if total_verified + payment.amount > order.grand_total:
        from rest_framework.exceptions import ValidationError
        raise ValidationError(
            f"تأیید این تراکنش باعث پرداخت بیش از سقف سفارش خواهد شد. مجموع تأییدشده: {total_verified}، تراکنش فعلی: {payment.amount}، مبلغ کل: {order.grand_total}"
        )

    payment.status = PaymentVerificationStatus.VERIFIED
    payment.verified_by = user
    payment.verified_at = timezone.now()
    payment.save()

    new_total_verified = total_verified + payment.amount
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
        action="PAYMENT_VERIFIED",
        target_type="PaymentTransaction",
        target_id=str(payment.id),
        changes={'order_number': order.order_number, 'amount': str(payment.amount), 'order_payment_status': order.payment_status}
    )

    if order.payment_status == PaymentStatus.PAID:
        import logging
        _logger = logging.getLogger(__name__)

        def _dispatch_order_paid():
            try:
                from apps.automation.services import trigger_automation
                from apps.automation.models import TriggerEvent
                trigger_automation(
                    store=payment.store,
                    trigger_event=TriggerEvent.ORDER_PAID,
                    payload={
                        'order_id': str(order.id),
                        'order_number': order.order_number,
                        'customer_name': order.customer.full_name,
                        'customer_phone': order.customer.phone_number,
                        'amount': float(payment.amount),
                        'idempotency_key': f"order_paid_{order.id}"
                    }
                )
            except Exception as exc:
                # Log structured error — do not silently swallow. Automation failures
                # should be visible and recoverable, not masked by a bare pass.
                _logger.error(
                    "Automation dispatch failed for ORDER_PAID event",
                    exc_info=True,
                    extra={'order_id': str(order.id), 'payment_id': str(payment.id), 'error': str(exc)}
                )

        transaction.on_commit(_dispatch_order_paid)

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
def process_payment_refund(payment, amount=None, reason="", user=None):
    """
    Safely and idempotently refunds a verified payment transaction.
    Pessimistically locks PaymentTransaction and Order to prevent over-refunds.
    Supports partial and cumulative refunds.
    """
    from rest_framework.exceptions import ValidationError
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

    payment.refunded_amount = curr_refunded + refund_amount
    if payment.refunded_amount >= payment.amount:
        payment.status = PaymentVerificationStatus.REFUNDED

    payment.rejection_reason = f"مسترد شده: {reason} (مبلغ استرداد: {refund_amount})" if reason else f"مسترد شده (مبلغ: {refund_amount})"
    payment.save(update_fields=['status', 'refunded_amount', 'rejection_reason', 'updated_at'])

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
        changes={'order_number': order.order_number, 'refund_amount': str(refund_amount), 'reason': reason}
    )
    return payment

