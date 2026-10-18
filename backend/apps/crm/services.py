from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Max, Count
from .models import CustomerProfile, CustomerSegment
from apps.orders.models import Customer, Order, OrderStatus, PaymentStatus

def recalculate_customer_rfm(customer):
    """Calculate exact Recency, Frequency, and Monetary (LTV) metrics for a single customer, deducting refunds"""
    from apps.returns.models import ReturnRequest, RefundStatus

    orders = Order.objects.filter(
        customer=customer,
        payment_status=PaymentStatus.PAID
    ).exclude(order_status=OrderStatus.CANCELLED)
    
    order_count = orders.count()
    refunds_total = ReturnRequest.objects.filter(
        customer=customer,
        refund_status=RefundStatus.REFUNDED
    ).aggregate(total=Sum('refund_amount'))['total'] or Decimal('0')

    if order_count == 0:
        gross_total = Decimal('0')
        net_spent = Decimal('0')
        aov = Decimal('0')
        recency = 999
        segment = CustomerSegment.NEW
        segment_reason = "مشتری جدید بدون ثبت سفارش پرداختی"
    else:
        gross_total = orders.aggregate(total=Sum('grand_total'))['total'] or Decimal('0')
        net_spent = max(Decimal('0'), gross_total - refunds_total)
        aov = (net_spent / order_count) if order_count else Decimal('0')
        latest_date = orders.aggregate(latest=Max('created_at'))['latest']
        recency = (timezone.now() - latest_date).days if latest_date else 999

        # RFM Segmentation heuristic with explicit reasons
        if order_count >= 4 and recency <= 45:
            segment = CustomerSegment.CHAMPION
            segment_reason = f"تعداد سفارش بالا ({order_count}) و خرید اخیر در کمتر از ۴۵ روز گذشته (روز {recency})"
        elif order_count >= 2 and recency <= 60:
            segment = CustomerSegment.LOYAL
            segment_reason = f"مشتری وفادار با {order_count} سفارش موفق و خرید در ۶۰ روز گذشته"
        elif order_count == 1 and recency <= 30:
            segment = CustomerSegment.NEW
            segment_reason = "مشتری جدید با یک سفارش در ۳۰ روز اخیر"
        elif order_count >= 2 and recency > 75:
            segment = CustomerSegment.AT_RISK
            segment_reason = f"مشتری با سابقه {order_count} سفارش که بیش از ۷۵ روز خریدی ثبت نکرده است"
        elif recency > 120:
            segment = CustomerSegment.HIBERNATING
            segment_reason = f"عدم خرید برای بیش از ۱۲۰ روز ({recency} روز)"
        else:
            segment = CustomerSegment.POTENTIAL_LOYALIST
            segment_reason = f"رفتار خرید با پتانسیل وفادارسازی ({order_count} سفارش، روز {recency})"

    profile, _ = CustomerProfile.objects.get_or_create(
        store=customer.store,
        customer=customer
    )
    profile.frequency_orders_count = order_count
    profile.monetary_total_spent = net_spent
    profile.average_order_value = aov
    profile.recency_days = recency
    profile.segment = segment
    profile.refunds_deducted = refunds_total
    profile.segment_reason = segment_reason
    profile.last_calculated_at = timezone.now()
    profile.save()
    return profile

def recalculate_all_store_customers(store):
    customers = Customer.objects.filter(store=store)
    updated = []
    for c in customers:
        updated.append(recalculate_customer_rfm(c))
    return len(updated)

