from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.tenancy.permissions import IsStoreMemberPermission, TenantFilterBackend, Role, user_has_store_permission
from apps.inventory.models import Warehouse
from .models import Order, Customer
from .serializers import (
    OrderDetailSerializer, OrderCreateSerializer,
    OrderCancelSerializer, OrderFulfillSerializer, CustomerSerializer
)
from .services import create_order, cancel_order, fulfill_order, import_orders_from_csv

class CustomerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = [IsStoreMemberPermission]
    filter_backends = [TenantFilterBackend, filters.SearchFilter]
    search_fields = ['full_name', 'phone_number', 'city']
    queryset = Customer.objects.all()

class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStoreMemberPermission]
    filter_backends = [TenantFilterBackend, DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['order_status', 'payment_status', 'fulfillment_status', 'channel']
    search_fields = ['order_number', 'customer__full_name', 'customer__phone_number', 'items__variant_sku']
    ordering_fields = ['created_at', 'grand_total']
    queryset = Order.objects.all().select_related('customer', 'warehouse').prefetch_related('items')

    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = request.store
        data = serializer.validated_data

        warehouse_id = data.get('warehouse_id')
        if warehouse_id:
            warehouse = Warehouse.objects.filter(id=warehouse_id, store=store).first()
        else:
            warehouse = Warehouse.objects.filter(store=store, is_active=True).first()

        if not warehouse:
            warehouse = Warehouse.objects.create(store=store, name="انبار پیش‌فرض", is_default=True)

        try:
            order = create_order(
                store=store,
                customer_data={
                    'full_name': data['customer_name'],
                    'phone_number': data['customer_phone'],
                    'city': data.get('city', ''),
                    'province': data.get('province', ''),
                    'address_line': data.get('address_line', ''),
                    'email': data.get('customer_email', ''),
                    'marketing_opt_in': data.get('marketing_opt_in', True),
                },
                items_data=data['items'],
                warehouse=warehouse,
                channel=data.get('channel'),
                shipping_cost=data.get('shipping_cost', 0),
                discount_amount=data.get('discount_amount', 0),
                utm_source=data.get('utm_source', ''),
                utm_medium=data.get('utm_medium', ''),
                utm_campaign=data.get('utm_campaign', ''),
                notes=data.get('notes', ''),
                user=request.user
            )
            return Response(OrderDetailSerializer(order).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reorder(self, request, pk=None):
        order = self.get_object()
        store = request.store
        items_data = [
            {
                'variant_id': item.variant_id,
                'quantity': item.quantity,
                'unit_price': item.unit_price,
                'unit_discount': item.unit_discount
            }
            for item in order.items.all()
        ]
        if not items_data:
            return Response({'error': 'سفارش مبدأ فاقد ردیف کالا است.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_order = create_order(
                store=store,
                customer_data={
                    'full_name': order.customer.full_name,
                    'phone_number': order.customer.phone_number,
                    'city': order.customer.city,
                    'province': order.customer.province,
                    'address_line': order.customer.address_line,
                    'postal_code': order.customer.postal_code,
                    'email': order.customer.email,
                },
                items_data=items_data,
                warehouse=order.warehouse,
                channel=order.channel,
                shipping_cost=order.shipping_cost,
                discount_amount=order.discount_amount,
                notes=f"سفارش مجدد پیرو سفارش قبلی {order.order_number}",
                user=request.user
            )
            return Response(OrderDetailSerializer(new_order).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        membership = getattr(request, 'membership', None)
        if not (request.user.is_superuser or request.user.is_staff or (membership and (membership.role in [Role.OWNER, Role.ADMIN, Role.BUSINESS_MANAGER, Role.OPS_MANAGER] or user_has_store_permission(membership, 'orders.cancel')))):
            return Response({'error': 'شما مجوز لغو سفارش را ندارید.'}, status=status.HTTP_403_FORBIDDEN)

        order = self.get_object()
        serializer = OrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cancelled_order = cancel_order(
                order=order,
                reason=serializer.validated_data.get('reason', ''),
                user=request.user
            )
            return Response(OrderDetailSerializer(cancelled_order).data)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def fulfill(self, request, pk=None):
        membership = getattr(request, 'membership', None)
        if not (request.user.is_superuser or request.user.is_staff or (membership and (membership.role in [Role.OWNER, Role.ADMIN, Role.OPS_MANAGER, Role.FULFILLMENT_STAFF] or user_has_store_permission(membership, 'fulfillment.manage') or user_has_store_permission(membership, 'fulfillment.pack')))):
            return Response({'error': 'شما مجوز ارسال و بسته‌بندی سفارش را ندارید.'}, status=status.HTTP_403_FORBIDDEN)

        order = self.get_object()
        serializer = OrderFulfillSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            fulfilled_order, shipment = fulfill_order(
                order=order,
                tracking_number=serializer.validated_data.get('tracking_number', ''),
                shipping_cost=serializer.validated_data.get('shipping_cost'),
                user=request.user
            )
            return Response({
                'order': OrderDetailSerializer(fulfilled_order).data,
                'tracking_number': shipment.tracking_number,
            })
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'], url_path='import-csv')
    def import_csv(self, request):
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({'error': 'فایل CSV الزامی است.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = import_orders_from_csv(
                store=request.store,
                file_content=uploaded_file.read(),
                user=request.user
            )
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from apps.tenancy.models import Store
from .models import WooCommerceSyncLog
from .services_woocommerce import sync_woocommerce_products, sync_woocommerce_orders, handle_woocommerce_webhook
import logging

logger = logging.getLogger(__name__)


class WooCommerceSyncView(APIView):
    permission_classes = [IsStoreMemberPermission]

    def post(self, request, action_name=None):
        action = request.data.get('action') or action_name
        try:
            if action == 'sync-products':
                res = sync_woocommerce_products(request.store)
                return Response(res, status=status.HTTP_200_OK)
            elif action == 'sync-orders':
                res = sync_woocommerce_orders(request.store)
                return Response(res, status=status.HTTP_200_OK)
            return Response({'error': 'عملیات نامعتبر است (گزینه‌های مجاز: sync-products, sync-orders)'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        logs = WooCommerceSyncLog.objects.filter(store=request.store).order_by('-created_at')[:20]
        data = [
            {
                'id': str(log.id),
                'sync_type': log.sync_type,
                'sync_type_display': log.get_sync_type_display(),
                'status': log.status,
                'status_display': log.get_status_display(),
                'items_synced': log.items_synced,
                'error_details': log.error_details,
                'created_at': log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            }
            for log in logs
        ]
        return Response(data)


class WooCommerceWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, store_id):
        store = Store.objects.filter(id=store_id, is_active=True).first()
        if not store:
            return Response({'error': 'فروشگاه یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

        topic = request.headers.get('X-WC-Webhook-Topic') or request.headers.get('X-Wc-Webhook-Topic', '')
        signature = request.headers.get('X-WC-Webhook-Signature') or request.headers.get('X-Wc-Webhook-Signature', '')

        try:
            result = handle_woocommerce_webhook(
                store=store,
                topic=topic,
                raw_body=request.body,
                signature_header=signature
            )
            return Response(result, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"WooCommerce webhook error for store {store.id}: {e}")
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

