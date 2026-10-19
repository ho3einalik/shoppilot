import uuid
from decimal import Decimal
from django.utils import timezone
from apps.fulfillment.models import Shipment, ShipmentStatus, Carrier, ShipmentTrackingEvent, TrackingEventSource
from apps.orders.models import OrderStatus, FulfillmentStatus

class CarrierAdapter:
    carrier_code = 'OTHER'

    def estimate_shipping_cost(self, weight_grams: int, origin_city: str, dest_city: str, store=None) -> dict:
        return {
            'total_cost': Decimal('50000'),
            'is_live_quote': False,
            'quote_type': 'DEFAULT_FLAT_RATE',
            'breakdown': {
                'base_fare': Decimal('50000'),
                'weight_surcharge': Decimal('0'),
                'distance_surcharge': Decimal('0'),
            },
            'notes': 'تعرفه ثابت پیش‌فرض حمل‌ونقل.'
        }

    def get_tracking_url(self, tracking_number: str) -> str:
        return ''

    def query_live_tracking(self, shipment: Shipment, store=None) -> dict:
        return {
            'is_live': False,
            'status': shipment.status,
            'status_display': shipment.get_status_display(),
            'tracking_number': shipment.tracking_number,
            'tracking_url': self.get_tracking_url(shipment.tracking_number),
            'mode': 'MANUAL_MODE',
            'message': 'اتصال مستقیم وب‌سرویس برای این حامل در دسترس نیست؛ وضعیت فعلی ثبت‌شده در سیستم نمایش داده می‌شود.'
        }

    def query_live_status(self, tracking_number: str) -> dict:
        return {
            'is_live': False,
            'message': 'اتصال مستقیم وب‌سرویس در دسترس نیست؛ از ثبت رویداد دستی استفاده فرمایید.'
        }


class IranPostAdapter(CarrierAdapter):
    carrier_code = Carrier.IRPOST

    def estimate_shipping_cost(self, weight_grams: int, origin_city: str, dest_city: str, store=None) -> dict:
        base_rate = Decimal('45000')  # 45,000 Tomans base
        weight_surcharge = Decimal('0')
        distance_surcharge = Decimal('0')

        if weight_grams > 1000:
            extra_kg = (weight_grams - 1000) / 1000
            weight_surcharge = Decimal(str(round(extra_kg * 15000)))

        if origin_city and dest_city and origin_city.strip() != dest_city.strip():
            distance_surcharge = Decimal('15000')  # Intercity tariff

        total = base_rate + weight_surcharge + distance_surcharge

        return {
            'total_cost': total,
            'is_live_quote': False,
            'quote_type': 'TARIFF_RULE_ENGINE',
            'breakdown': {
                'base_fare': base_rate,
                'weight_surcharge': weight_surcharge,
                'distance_surcharge': distance_surcharge,
            },
            'notes': 'تعرفه تخمینی بر اساس نرخ مصوب پست پیشتاز (غیرزنده).'
        }

    def get_tracking_url(self, tracking_number: str) -> str:
        return f"https://tracking.post.ir/?id={tracking_number}"

    def query_live_tracking(self, shipment: Shipment, store=None) -> dict:
        from apps.features.adapters import get_integration_adapter
        adapter = get_integration_adapter('shipping_irpost')
        target_store = store or getattr(shipment, 'store', None)
        api_key = ''
        if adapter and target_store:
            conf = adapter.get_config(target_store, decrypted=True)
            api_key = conf.get('api_key', '')

        tracking_url = self.get_tracking_url(shipment.tracking_number)

        if not api_key:
            return {
                'is_live': False,
                'status': shipment.status,
                'status_display': shipment.get_status_display(),
                'tracking_number': shipment.tracking_number,
                'tracking_url': tracking_url,
                'mode': 'EXTERNAL_PORTAL_FALLBACK',
                'carrier': Carrier.IRPOST,
                'carrier_display': 'شرکت ملی پست',
                'message': 'کلید وب‌سرویس پستی در تنظیمات فروشگاه وارد نشده است. رهگیری از طریق درگاه رسمی شرکت ملی پست انجام می‌شود.'
            }

        # TRACKING FIX: An API key alone does NOT mean a live query succeeded.
        # The previous code falsely returned is_live=True without making any actual HTTP request.
        # Until a real Iran Post webservice integration is implemented, explicitly mark as
        # NOT_IMPLEMENTED to avoid fabricating live tracking status.
        # When a real endpoint is available, replace this block with an actual HTTP call,
        # validate the HTTP status, response schema, and provider error codes before setting is_live=True.
        return {
            'is_live': False,
            'status': shipment.status,
            'status_display': shipment.get_status_display(),
            'tracking_number': shipment.tracking_number,
            'tracking_url': tracking_url,
            'mode': 'API_NOT_IMPLEMENTED',
            'carrier': Carrier.IRPOST,
            'carrier_display': 'شرکت ملی پست',
            'message': 'وب‌سرویس رهگیری شرکت ملی پست هنوز پیاده‌سازی نشده است. رهگیری از طریق لینک درگاه عمومی انجام می‌شود.'
        }



class TipaxAdapter(CarrierAdapter):
    carrier_code = Carrier.TIPAX

    def estimate_shipping_cost(self, weight_grams: int, origin_city: str, dest_city: str, store=None) -> dict:
        base_rate = Decimal('65000')  # 65,000 Tomans base for Tipax
        weight_surcharge = Decimal('0')

        if weight_grams > 2000:
            extra_kg = (weight_grams - 2000) / 1000
            weight_surcharge = Decimal(str(round(extra_kg * 20000)))

        total = base_rate + weight_surcharge

        return {
            'total_cost': total,
            'is_live_quote': False,
            'quote_type': 'TARIFF_RULE_ENGINE',
            'breakdown': {
                'base_fare': base_rate,
                'weight_surcharge': weight_surcharge,
                'distance_surcharge': Decimal('0'),
            },
            'notes': 'تعرفه تخمینی بر اساس نرخ پایه تیپاکس اکسپرس (غیرزنده).'
        }

    def get_tracking_url(self, tracking_number: str) -> str:
        return f"https://tipaxco.com/tracking?id={tracking_number}"

    def query_live_tracking(self, shipment: Shipment, store=None) -> dict:
        from apps.features.adapters import get_integration_adapter
        adapter = get_integration_adapter('shipping_tipax')
        target_store = store or getattr(shipment, 'store', None)
        api_key = ''
        if adapter and target_store:
            conf = adapter.get_config(target_store, decrypted=True)
            api_key = conf.get('api_key', '')

        tracking_url = self.get_tracking_url(shipment.tracking_number)

        if not api_key:
            return {
                'is_live': False,
                'status': shipment.status,
                'status_display': shipment.get_status_display(),
                'tracking_number': shipment.tracking_number,
                'tracking_url': tracking_url,
                'mode': 'EXTERNAL_PORTAL_FALLBACK',
                'carrier': Carrier.TIPAX,
                'carrier_display': 'تیپاکس',
                'message': 'کلید وب‌سرویس تیپاکس در تنظیمات فروشگاه تنظیم نشده است. جهت رهگیری مستقیم به پرتال تیپاکس مراجعه کنید.'
            }

        return {
            'is_live': False,
            'status': shipment.status,
            'status_display': shipment.get_status_display(),
            'tracking_number': shipment.tracking_number,
            'tracking_url': tracking_url,
            'mode': 'API_NOT_IMPLEMENTED',
            'carrier': Carrier.TIPAX,
            'carrier_display': 'تیپاکس',
            'message': 'وب‌سرویس رهگیری تیپاکس هنوز پیاده‌سازی نشده است. رهگیری از طریق لینک درگاه عمومی تیپاکس انجام می‌شود.'
        }



class SnappBoxAdapter(CarrierAdapter):
    carrier_code = Carrier.LOCAL_COURIER

    def estimate_shipping_cost(self, weight_grams: int, origin_city: str, dest_city: str, store=None) -> dict:
        base_rate = Decimal('50000')
        return {
            'total_cost': base_rate,
            'is_live_quote': False,
            'quote_type': 'ESTIMATED_FLAT_RATE',
            'breakdown': {
                'base_fare': base_rate,
                'weight_surcharge': Decimal('0'),
                'distance_surcharge': Decimal('0'),
            },
            'notes': 'تعرفه تخمینی پیک موتوری درون‌شهری.'
        }

    def get_tracking_url(self, tracking_number: str) -> str:
        return ''

    def query_live_tracking(self, shipment: Shipment, store=None) -> dict:
        return {
            'is_live': False,
            'status': shipment.status,
            'status_display': shipment.get_status_display(),
            'tracking_number': shipment.tracking_number,
            'tracking_url': '',
            'mode': 'MANUAL_DISPATCH',
            'carrier': Carrier.LOCAL_COURIER,
            'carrier_display': 'پیک شهری',
            'message': 'پیگیری پیک درون‌شهری از طریق تماس مستقیم یا رصد دستی سفیر صورت می‌پذیرد.'
        }


ADAPTERS = {
    Carrier.IRPOST: IranPostAdapter(),
    Carrier.TIPAX: TipaxAdapter(),
    Carrier.LOCAL_COURIER: SnappBoxAdapter(),
}

def get_carrier_adapter(carrier_code: str) -> CarrierAdapter:
    return ADAPTERS.get(carrier_code, CarrierAdapter())



def create_shipment(store, order, tracking_number: str, carrier: str, shipping_cost: Decimal = Decimal('0'), idempotency_key: str = '', notes: str = '') -> Shipment:
    """
    Creates a shipment for an order with idempotency check to prevent duplicate shipments.
    """
    # 1. Check idempotency if key provided
    if idempotency_key:
        existing = Shipment.objects.filter(store=store, idempotency_key=idempotency_key).first()
        if existing:
            return existing

    # 2. Check duplicate tracking number for this order
    existing_tracking = Shipment.objects.filter(order=order, tracking_number=tracking_number).first()
    if existing_tracking:
        return existing_tracking

    # 3. Create shipment
    shipment = Shipment.objects.create(
        store=store,
        order=order,
        tracking_number=tracking_number,
        carrier=carrier,
        status=ShipmentStatus.SHIPPED,
        shipping_cost=shipping_cost or order.shipping_cost,
        idempotency_key=idempotency_key or f"ship_{order.id}_{tracking_number}",
        notes=notes
    )

    # 4. Create initial tracking event
    ShipmentTrackingEvent.objects.create(
        shipment=shipment,
        status=ShipmentStatus.SHIPPED,
        location=order.store.name,
        description=f"مرسوله تحویل {shipment.get_carrier_display()} شد با کد رهگیری {tracking_number}.",
        source=TrackingEventSource.MANUAL,
        occurred_at=timezone.now()
    )

    # 5. Transition order to FULFILLED if not already
    if order.fulfillment_status != FulfillmentStatus.FULFILLED:
        order.order_status = OrderStatus.FULFILLED
        order.fulfillment_status = FulfillmentStatus.FULFILLED
        order.save(update_fields=['order_status', 'fulfillment_status', 'updated_at'])

    return shipment


def update_shipment_status(shipment: Shipment, new_status: str, location: str = '', description: str = '', failed_reason: str = '', source: str = TrackingEventSource.MANUAL) -> Shipment:
    """
    Updates shipment status, logs tracking event, and handles delivery / failure transitions.
    """
    shipment.status = new_status
    if new_status == ShipmentStatus.DELIVERED:
        shipment.delivered_at = timezone.now()
        # Mark order completed
        if shipment.order.order_status != OrderStatus.COMPLETED:
            shipment.order.order_status = OrderStatus.COMPLETED
            shipment.order.save(update_fields=['order_status', 'updated_at'])
    elif new_status == ShipmentStatus.FAILED:
        shipment.failed_reason = failed_reason or description

    shipment.save(update_fields=['status', 'delivered_at', 'failed_reason', 'updated_at'])

    # Log tracking event
    ShipmentTrackingEvent.objects.create(
        shipment=shipment,
        status=new_status,
        location=location or (shipment.order.customer.city or ''),
        description=description or f"وضعیت مرسوله به {shipment.get_status_display()} تغییر یافت.",
        source=source,
        occurred_at=timezone.now()
    )

    return shipment
