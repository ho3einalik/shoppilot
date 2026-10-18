from decimal import Decimal
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.tenancy.permissions import IsStoreMemberPermission, TenantFilterBackend
from .models import Shipment, ShipmentStatus, Carrier
from .serializers import ShipmentSerializer
from .services import create_shipment, update_shipment_status, get_carrier_adapter

class ShipmentViewSet(viewsets.ModelViewSet):
    serializer_class = ShipmentSerializer
    permission_classes = [IsStoreMemberPermission]
    filter_backends = [TenantFilterBackend, DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'carrier']
    search_fields = ['tracking_number', 'order__order_number', 'order__customer__full_name', 'order__customer__phone_number']
    ordering_fields = ['shipped_at']
    queryset = Shipment.objects.all().select_related('order', 'order__customer').prefetch_related('tracking_events')

    def create(self, request, *args, **kwargs):
        order_id = request.data.get('order')
        tracking_number = request.data.get('tracking_number')
        carrier = request.data.get('carrier', Carrier.IRPOST)
        shipping_cost = Decimal(str(request.data.get('shipping_cost', '0')))
        idempotency_key = request.data.get('idempotency_key', '')
        notes = request.data.get('notes', '')

        if not order_id or not tracking_number:
            return Response({'error': 'شناسه سفارش و کد رهگیری الزامی است.'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.orders.models import Order
        order = Order.objects.filter(store=request.store, id=order_id).first()
        if not order:
            return Response({'error': 'سفارش یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

        shipment = create_shipment(
            store=request.store,
            order=order,
            tracking_number=tracking_number,
            carrier=carrier,
            shipping_cost=shipping_cost,
            idempotency_key=idempotency_key,
            notes=notes
        )
        serializer = self.get_serializer(shipment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='update-status')
    def update_status(self, request, pk=None):
        shipment = self.get_object()
        new_status = request.data.get('status')
        location = request.data.get('location', '')
        description = request.data.get('description', '')
        failed_reason = request.data.get('failed_reason', '')

        if not new_status or new_status not in ShipmentStatus.values:
            return Response({'error': 'وضعیت مرسوله نامعتبر است.'}, status=status.HTTP_400_BAD_REQUEST)

        updated_shipment = update_shipment_status(
            shipment=shipment,
            new_status=new_status,
            location=location,
            description=description,
            failed_reason=failed_reason
        )
        return Response(self.get_serializer(updated_shipment).data)

    @action(detail=False, methods=['post'], url_path='estimate-quote')
    def estimate_quote(self, request):
        carrier = request.data.get('carrier', Carrier.IRPOST)
        weight_grams = int(request.data.get('weight_grams', 1000))
        origin_city = request.data.get('origin_city', 'تهران')
        dest_city = request.data.get('dest_city', 'تهران')

        adapter = get_carrier_adapter(carrier)
        quote = adapter.estimate_shipping_cost(weight_grams, origin_city, dest_city, store=request.store)
        if isinstance(quote, dict):
            return Response({
                'carrier': carrier,
                'estimated_cost': str(quote.get('total_cost', '0')),
                'total_cost': str(quote.get('total_cost', '0')),
                'is_live_quote': quote.get('is_live_quote', False),
                'quote_type': quote.get('quote_type', 'TARIFF_ESTIMATE'),
                'breakdown': {k: str(v) for k, v in quote.get('breakdown', {}).items()},
                'notes': quote.get('notes', ''),
                'currency': request.store.currency
            })
        return Response({
            'carrier': carrier,
            'estimated_cost': str(quote),
            'currency': request.store.currency
        })

    @action(detail=True, methods=['get', 'post'], url_path='query-live-tracking')
    def query_live_tracking(self, request, pk=None):
        shipment = self.get_object()
        adapter = get_carrier_adapter(shipment.carrier)
        tracking_result = adapter.query_live_tracking(shipment, store=request.store)
        return Response(tracking_result)


    @action(detail=True, methods=['get'], url_path='packing-slip')
    def packing_slip(self, request, pk=None):
        shipment = self.get_object()
        order = shipment.order
        items_data = [
            {
                'sku': item.variant_sku,
                'name': item.variant_name,
                'quantity': item.quantity,
                'unit_price': int(item.unit_price),
                'total_price': int(item.total_price),
            }
            for item in order.items.all()
        ]
        return Response({
            'shipment_id': str(shipment.id),
            'tracking_number': shipment.tracking_number,
            'carrier': shipment.get_carrier_display(),
            'status': shipment.status,
            'status_display': shipment.get_status_display(),
            'order_number': order.order_number,
            'order_date': order.created_at.strftime('%Y/%m/%d %H:%M'),
            'store_name': order.store.name,
            'currency': order.currency,
            'customer': {
                'name': order.customer.full_name,
                'phone': order.customer.phone_number,
                'city': order.customer.city,
                'province': order.customer.province,
                'address': order.customer.address_line,
                'postal_code': order.customer.postal_code,
            },
            'items': items_data,
            'total_items_price': int(order.total_items_price),
            'shipping_cost': int(order.shipping_cost),
            'discount_amount': int(order.discount_amount),
            'grand_total': int(order.grand_total),
            'notes': order.notes,
        })
