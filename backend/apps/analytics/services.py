from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Count, F, Q
from apps.orders.models import Order, OrderItem, OrderStatus, OrderChannel
from apps.payments.models import PaymentTransaction, PaymentVerificationStatus
from apps.inventory.models import InventoryBalance
from apps.catalog.models import ProductVariant

def calculate_store_overview_metrics(store, days=30):
    if not store:
        from apps.tenancy.models import Store
        store = Store.objects.filter(is_active=True).first()

    if not store:
        return {
            'currency': 'IRR',
            'period_days': days,
            'gross_sales': 0,
            'discounts': 0,
            'net_sales': 0,
            'shipping_collected': 0,
            'paid_revenue': 0,
            'outstanding_amount': 0,
            'order_count': 0,
            'cancelled_orders_count': 0,
            'average_order_value': 0,
            'gross_profit': 0,
            'refunds_amount': 0,
            'net_operating_profit': 0,
            'gross_profit_margin_pct': 0,
            'inventory_valuation': 0,
            'inventory_units_on_hand': 0,
            'low_stock_count': 0,
            'out_of_stock_count': 0,
            'channels': [],
            'daily_sales': [],
            'top_products': [],
        }

    start_date = timezone.now() - timedelta(days=days)

    active_orders = Order.objects.filter(
        store=store,
        created_at__gte=start_date
    ).exclude(order_status=OrderStatus.CANCELLED)

    total_orders_count = active_orders.count()
    cancelled_orders_count = Order.objects.filter(
        store=store,
        created_at__gte=start_date,
        order_status=OrderStatus.CANCELLED
    ).count()

    # Sales aggregations
    totals = active_orders.aggregate(
        gross_items=Sum('total_items_price'),
        discounts=Sum('discount_amount'),
        shipping=Sum('shipping_cost'),
        grand=Sum('grand_total'),
    )
    gross_sales = totals['gross_items'] or Decimal('0')
    discounts = totals['discounts'] or Decimal('0')
    net_sales = max(Decimal('0'), gross_sales - discounts)
    shipping_collected = totals['shipping'] or Decimal('0')

    # Paid revenue from verified payments
    verified_payments_sum = PaymentTransaction.objects.filter(
        store=store,
        status=PaymentVerificationStatus.VERIFIED,
        created_at__gte=start_date
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    outstanding_amount = max(Decimal('0'), (totals['grand'] or Decimal('0')) - verified_payments_sum)

    # Completed Refunds in the period
    from apps.finance.models import RefundRecord
    refunds_sum = RefundRecord.objects.filter(
        store=store,
        status='COMPLETED',
        created_at__gte=start_date
    ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    net_sales_after_refunds = max(Decimal('0'), net_sales - refunds_sum)

    # AOV
    aov = int(net_sales / total_orders_count) if total_orders_count > 0 else 0

    # COGS and Gross Profit calculation using historical cost snapshots!
    order_items = OrderItem.objects.filter(
        order__in=active_orders
    )
    total_revenue_from_items = sum(item.total_price for item in order_items)
    total_cogs = sum(item.cost_price_snapshot * item.quantity for item in order_items)
    gross_profit = total_revenue_from_items - total_cogs
    net_operating_profit = gross_profit - refunds_sum
    gross_profit_margin_pct = round((float(gross_profit) / float(total_revenue_from_items) * 100), 1) if total_revenue_from_items > 0 else 0.0

    # Inventory Valuation
    inventory_balances = InventoryBalance.objects.filter(store=store).select_related('variant')
    total_inventory_cost_value = sum(
        b.on_hand_quantity * b.variant.cost_price for b in inventory_balances
    )
    total_inventory_units_on_hand = sum(b.on_hand_quantity for b in inventory_balances)
    low_stock_count = sum(1 for b in inventory_balances if b.available <= b.reorder_point)
    out_of_stock_count = sum(1 for b in inventory_balances if b.available == 0)

    # Sales by channel
    channel_data = []
    for ch_code, ch_name in OrderChannel.choices:
        ch_orders = active_orders.filter(channel=ch_code)
        ch_revenue = ch_orders.aggregate(s=Sum('grand_total'))['s'] or Decimal('0')
        ch_count = ch_orders.count()
        if ch_count > 0:
            channel_data.append({
                'channel': ch_code,
                'channel_name': ch_name,
                'order_count': ch_count,
                'revenue': int(ch_revenue),
            })

    # Sales trend by day for chart
    daily_sales = []
    for i in range(days - 1, -1, -1):
        day_date = (timezone.now() - timedelta(days=i)).date()
        day_orders = active_orders.filter(created_at__date=day_date)
        day_rev = day_orders.aggregate(s=Sum('grand_total'))['s'] or Decimal('0')
        day_cnt = day_orders.count()
        daily_sales.append({
            'date': day_date.strftime('%Y-%m-%d'),
            'revenue': int(day_rev),
            'order_count': day_cnt,
        })

    # Top selling variants
    top_items = OrderItem.objects.filter(order__in=active_orders).values(
        'variant_sku', 'variant_name'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_sales=Sum('total_price')
    ).order_by('-total_quantity')[:5]

    return {
        'currency': store.currency,
        'period_days': days,
        'gross_sales': int(gross_sales),
        'discounts': int(discounts),
        'net_sales': int(net_sales),
        'shipping_collected': int(shipping_collected),
        'paid_revenue': int(verified_payments_sum),
        'outstanding_amount': int(outstanding_amount),
        'order_count': total_orders_count,
        'cancelled_orders_count': cancelled_orders_count,
        'average_order_value': aov,
        'gross_profit': int(gross_profit),
        'refunds_amount': int(refunds_sum),
        'net_operating_profit': int(net_operating_profit),
        'gross_profit_margin_pct': gross_profit_margin_pct,
        'inventory_valuation': int(total_inventory_cost_value),
        'inventory_units_on_hand': total_inventory_units_on_hand,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'channels': channel_data,
        'daily_sales': daily_sales,
        'top_products': list(top_items),
    }
