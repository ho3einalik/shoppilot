import base64
import hashlib
import hmac
import json
import pytest
from decimal import Decimal
from unittest import mock
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.tenancy.models import Business, Store, StoreMembership, Role, MembershipStatus
from apps.features.models import StoreIntegrationConfig, IntegrationState
from apps.features.adapters import (
    IntegrationRegistry,
    TelegramIntegrationAdapter,
    InstagramIntegrationAdapter,
    WooCommerceIntegrationAdapter,
    IranPostShippingAdapter,
    TipaxShippingAdapter
)
from apps.social.models import (
    SocialAccount,
    SocialContent,
    SocialPlatform,
    ConnectionMode,
    ContentType,
    ContentStatus,
    PublishingMode
)
from apps.social.services import SocialService
from apps.social.tasks import publish_due_scheduled_social_content
from apps.social_inbox.models import ConversationThread, ChatMessage, ThreadChannel, SenderType
from apps.social_inbox.services import send_agent_message, receive_incoming_message

from apps.fulfillment.models import Shipment, ShipmentStatus, Carrier, ShipmentTrackingEvent
from apps.fulfillment.services import create_shipment, get_carrier_adapter, IranPostAdapter, TipaxAdapter
from apps.catalog.models import Product, ProductVariant, ProductStatus
from apps.inventory.models import Warehouse, InventoryBalance
from apps.orders.models import (
    Order, OrderItem, Customer, OrderChannel, OrderStatus,
    PaymentStatus, FulfillmentStatus, WooCommerceSyncLog,
    SyncType, SyncStatus
)
from apps.orders.services_woocommerce import (
    sync_woocommerce_products,
    sync_woocommerce_orders,
    push_inventory_to_woocommerce,
    handle_woocommerce_webhook
)
from apps.returns.models import ReturnRequest, ReturnStatus, RefundStatus
from apps.crm.models import CustomerProfile, CustomerSegment
from apps.crm.services import recalculate_customer_rfm
from apps.marketing.models import MarketingCampaign, CampaignChannel, CampaignStatus
from apps.marketing.services import dispatch_marketing_campaign
from apps.suppliers.models import Supplier, PurchaseOrder, PurchaseOrderItem, PurchaseOrderStatus, GoodsReceiptInspection, RejectionReason
from apps.suppliers.services import create_purchase_order, approve_purchase_order, mark_purchase_order_sent, receive_po_goods


@pytest.mark.django_db
class TestOperationalCapabilitiesCompletion:

    @pytest.fixture(autouse=True)
    def setup_base(self):
        self.owner = User.objects.create_user(
            email="owner_ops@testshop.ir",
            password="StrongPassword123!",
            full_name="Ops Owner"
        )
        self.biz = Business.objects.create(name="Ops Business", owner=self.owner)
        self.store = Store.objects.create(business=self.biz, name="Ops Store", currency="IRT")
        self.membership = StoreMembership.objects.create(
            store=self.store,
            user=self.owner,
            role=Role.OWNER,
            status=MembershipStatus.ACTIVE,
            is_active=True
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)
        self.client.defaults['HTTP_X_STORE_ID'] = str(self.store.id)

        self.warehouse = Warehouse.objects.create(
            store=self.store,
            name="انبار مرکزی",
            is_default=True,
            is_active=True
        )

    # -------------------------------------------------------------------------
    # 1. Telegram Adapter & Webhook Operations
    # -------------------------------------------------------------------------
    def test_telegram_adapter_and_webhook_flow(self):
        tg_adapter = IntegrationRegistry.get_adapter('social_telegram')
        assert tg_adapter is not None

        # Configure Telegram
        tg_adapter.save_config(self.store, {
            'bot_token': '123456789:ABCdefGHIjklMNOpqrSTUvwxYZ',
            'channel_id': '@test_ops_channel',
            'webhook_secret': 'super_secret_webhook_token_123'
        })

        # Test live test probe
        with mock.patch('urllib.request.urlopen') as mock_url:
            mock_resp = mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps({
                'ok': True,
                'result': {'id': 123456789, 'is_bot': True, 'first_name': 'ShopPilotBot', 'username': 'shoppilot_bot'}
            }).encode('utf-8')
            mock_url.return_value.__enter__.return_value = mock_resp

            health = tg_adapter.test_connection(self.store)
            assert health.state == IntegrationState.READY
            assert 'ShopPilotBot' in health.message

        # Test webhook receiving incoming message
        client = APIClient()  # Unauthenticated webhook
        webhook_url = f"/api/v1/social-inbox/webhooks/telegram/{self.store.id}/"
        payload = {
            'update_id': 10001,
            'message': {
                'message_id': 9988,
                'from': {'id': 776655, 'first_name': 'Ali', 'username': 'alireza'},
                'chat': {'id': 776655, 'type': 'private'},
                'text': 'سلام، شرایط خرید عمده چیه؟'
            }
        }

        # Request with valid secret header
        response = client.post(
            webhook_url,
            data=payload,
            format='json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='super_secret_webhook_token_123'
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify thread and message created in inbox
        thread = ConversationThread.objects.filter(store=self.store, channel=ThreadChannel.TELEGRAM).first()
        assert thread is not None
        assert thread.contact_handle == '776655'
        assert thread.messages.count() == 1
        msg = thread.messages.first()
        assert msg.text == 'سلام، شرایط خرید عمده چیه؟'
        assert msg.external_message_id == 'tg_9988'
        assert msg.delivery_status == 'DELIVERED'

    # -------------------------------------------------------------------------
    # 2. Instagram Direct Publishing & Scheduled Tasks
    # -------------------------------------------------------------------------
    def test_instagram_publishing_and_scheduled_task(self):
        ig_adapter = IntegrationRegistry.get_adapter('social_instagram')
        ig_conf = ig_adapter.save_config(self.store, {
            'access_token': 'EAABtest_valid_meta_token',
            'instagram_account_id': '178414000000000',
            'auto_sync_insights': True
        })
        ig_conf.is_active = True
        ig_conf.status = IntegrationState.ACTIVE
        ig_conf.last_test_success = True
        ig_conf.save()

        account = SocialAccount.objects.create(
            store=self.store,
            platform=SocialPlatform.INSTAGRAM,
            handle='@testshop',
            is_connected=True,
            connection_mode=ConnectionMode.DIRECT_API
        )

        content = SocialContent.objects.create(
            store=self.store,
            account=account,
            creator=self.owner,
            content_type=ContentType.POST,
            publishing_mode=PublishingMode.DIRECT_API,
            title="پست جشنواره تابستانه",
            caption="تخفیف ویژه تمامی محصولات فصل",
            hashtags="#حراج #تابستانه",
            media_urls=["https://images.unsplash.com/photo-1523275335684-37898b6baf30"],
            status=ContentStatus.SCHEDULED,
            scheduled_at=timezone.now() - timezone.timedelta(minutes=5)
        )

        with mock.patch('urllib.request.urlopen') as mock_url:
            resp_container = mock.MagicMock()
            resp_container.status = 200
            resp_container.read.return_value = json.dumps({'id': 'container_112233'}).encode('utf-8')

            resp_publish = mock.MagicMock()
            resp_publish.status = 200
            resp_publish.read.return_value = json.dumps({'id': 'real_meta_post_99999'}).encode('utf-8')

            resp_media = mock.MagicMock()
            resp_media.status = 200
            resp_media.read.return_value = json.dumps({'permalink': 'https://www.instagram.com/p/Cxyz123/'}).encode('utf-8')

            mock_url.return_value.__enter__.side_effect = [resp_container, resp_publish, resp_media]

            # Execute periodic scheduled content celery task
            res = publish_due_scheduled_social_content()
            assert "1 published" in res

            content.refresh_from_db()
            assert content.status == ContentStatus.PUBLISHED
            assert content.external_post_id == 'real_meta_post_99999'
            assert content.published_url == 'https://www.instagram.com/p/Cxyz123/'


    # -------------------------------------------------------------------------
    # 3. Fulfillment Carrier Structured Quotes & Live Tracking
    # -------------------------------------------------------------------------
    def test_fulfillment_carrier_quotes_and_tracking(self):
        post_adapter = IranPostAdapter()
        quote = post_adapter.estimate_shipping_cost(weight_grams=2500, origin_city="تهران", dest_city="اصفهان")

        assert isinstance(quote, dict)
        assert quote['is_live_quote'] is False
        assert quote['quote_type'] == 'TARIFF_RULE_ENGINE'
        assert quote['total_cost'] > Decimal('45000')
        assert 'base_fare' in quote['breakdown']
        assert 'distance_surcharge' in quote['breakdown']

        # Create Order and Shipment
        customer = Customer.objects.create(
            store=self.store,
            full_name="مشتری تست حمل",
            phone_number="09121112233",
            city="اصفهان"
        )
        order = Order.objects.create(
            store=self.store,
            order_number="ORD-TRACK-001",
            customer=customer,
            warehouse=self.warehouse,
            grand_total=Decimal('250000')
        )

        shipment = create_shipment(
            store=self.store,
            order=order,
            tracking_number="12345678901234567890",
            carrier=Carrier.IRPOST,
            shipping_cost=Decimal('45000')
        )
        assert shipment.status == ShipmentStatus.SHIPPED
        assert order.fulfillment_status == FulfillmentStatus.FULFILLED

        # Test query live tracking API
        resp = self.client.get(f"/api/v1/fulfillment/{shipment.id}/query-live-tracking/")
        assert resp.status_code == status.HTTP_200_OK

        data = resp.json()
        assert data['tracking_number'] == "12345678901234567890"
        assert "tracking.post.ir" in data['tracking_url']
        assert data['is_live'] is False  # Transparent: no synthetic fake live state
        assert data['mode'] == 'EXTERNAL_PORTAL_FALLBACK'

    # -------------------------------------------------------------------------
    # 4. WooCommerce Two-Way Sync (Products, Orders, Stock Push, Webhooks)
    # -------------------------------------------------------------------------
    def test_woocommerce_two_way_sync(self):
        wc_adapter = IntegrationRegistry.get_adapter('ecommerce_woocommerce')
        wc_adapter.save_config(self.store, {
            'store_url': 'https://example-shop.com',
            'consumer_key': 'ck_test_1234567890abcdef1234567890abcdef',
            'consumer_secret': 'cs_test_0987654321fedcba0987654321fedcba',
            'sync_inventory': True,
            'sync_orders': True,
            'webhook_secret': 'my_webhook_secret_key'
        })

        # A) Product Sync
        mock_wc_products = [
            {
                'id': 501,
                'name': 'کفش رانینگ هوشمند',
                'slug': 'smart-running-shoes',
                'price': '850000',
                'sku': 'SHOE-RUN-501',
                'description': 'کفش بسیار سبک و راحت'
            }
        ]
        with mock.patch('urllib.request.urlopen') as mock_url:
            mock_resp = mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps(mock_wc_products).encode('utf-8')
            mock_url.return_value.__enter__.return_value = mock_resp

            res = sync_woocommerce_products(self.store)
            assert res['status'] == 'SUCCESS'
            assert res['synced_items'] == 1

        variant = ProductVariant.objects.filter(store=self.store, sku='SHOE-RUN-501').first()
        assert variant is not None
        assert variant.retail_price == Decimal('850000')

        # B) Inventory Push to WooCommerce (ShopPilot Single Source of Truth)
        InventoryBalance.objects.create(
            store=self.store,
            warehouse=self.warehouse,
            variant=variant,
            on_hand_quantity=15,
            reserved_quantity=2
        )

        with mock.patch('urllib.request.urlopen') as mock_url:
            # 1. Search product by SKU
            mock_search_resp = mock.MagicMock()
            mock_search_resp.status = 200
            mock_search_resp.read.return_value = json.dumps([{'id': 501}]).encode('utf-8')

            # 2. Update stock PUT
            mock_put_resp = mock.MagicMock()
            mock_put_resp.status = 200
            mock_put_resp.read.return_value = json.dumps({'id': 501, 'stock_quantity': 13}).encode('utf-8')

            mock_url.return_value.__enter__.side_effect = [mock_search_resp, mock_put_resp]

            push_res = push_inventory_to_woocommerce(self.store, variant)
            assert push_res['status'] == 'SUCCESS'
            assert push_res['synced_stock'] == 13  # 15 on hand - 2 reserved

        # C) Order Webhook Receiving & Idempotent Ingestion
        wc_order_payload = {
            'id': 8801,
            'number': '8801',
            'status': 'processing',
            'total': '850000',
            'shipping_total': '45000',
            'discount_total': '0',
            'currency': 'IRT',
            'billing': {
                'first_name': 'رضا',
                'last_name': 'اکبری',
                'phone': '09351234567',
                'city': 'شیراز',
                'state': 'فارس',
                'address_1': 'بلوار ارم، پلاک ۱۰'
            },
            'line_items': [
                {
                    'product_id': 501,
                    'name': 'کفش رانینگ هوشمند',
                    'sku': 'SHOE-RUN-501',
                    'quantity': 1,
                    'price': '850000'
                }
            ]
        }
        raw_body = json.dumps(wc_order_payload).encode('utf-8')
        secret = 'my_webhook_secret_key'
        signature = base64.b64encode(hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).digest()).decode('utf-8')

        client = APIClient()
        resp = client.post(
            f"/api/v1/orders/woocommerce/webhook/{self.store.id}/",
            data=raw_body,
            content_type='application/json',
            HTTP_X_WC_WEBHOOK_TOPIC='order.created',
            HTTP_X_WC_WEBHOOK_SIGNATURE=signature
        )
        assert resp.status_code == status.HTTP_200_OK

        order = Order.objects.filter(store=self.store, order_number="WC-8801").first()
        assert order is not None
        assert order.channel == OrderChannel.WOOCOMMERCE
        assert order.payment_status == PaymentStatus.PAID
        assert order.customer.phone_number == '09351234567'
        assert order.items.count() == 1

        # Idempotency check: sending duplicate webhook does not duplicate order
        resp_dup = client.post(
            f"/api/v1/orders/woocommerce/webhook/{self.store.id}/",
            data=raw_body,
            content_type='application/json',
            HTTP_X_WC_WEBHOOK_TOPIC='order.created',
            HTTP_X_WC_WEBHOOK_SIGNATURE=signature
        )
        assert resp_dup.status_code == status.HTTP_200_OK
        assert Order.objects.filter(store=self.store, order_number="WC-8801").count() == 1

    # -------------------------------------------------------------------------
    # 5. CRM RFM Calculation with Refund Deductions
    # -------------------------------------------------------------------------
    def test_crm_rfm_deducts_refunds_correctly(self):
        customer = Customer.objects.create(
            store=self.store,
            full_name="مشتری طلایی با مرجوعی",
            phone_number="09187654321"
        )
        # Order 1: 500,000 Tomans
        o1 = Order.objects.create(
            store=self.store,
            order_number="ORD-CRM-01",
            customer=customer,
            warehouse=self.warehouse,
            payment_status=PaymentStatus.PAID,
            order_status=OrderStatus.COMPLETED,
            grand_total=Decimal('500000')
        )
        # Order 2: 700,000 Tomans
        o2 = Order.objects.create(
            store=self.store,
            order_number="ORD-CRM-02",
            customer=customer,
            warehouse=self.warehouse,
            payment_status=PaymentStatus.PAID,
            order_status=OrderStatus.COMPLETED,
            grand_total=Decimal('700000')
        )
        # Completed Return Request: 200,000 Tomans refunded
        ReturnRequest.objects.create(
            store=self.store,
            rma_number="RMA-9001",
            order=o1,
            customer=customer,
            status=ReturnStatus.COMPLETED,
            refund_status=RefundStatus.REFUNDED,
            refund_amount=Decimal('200000')
        )

        profile = recalculate_customer_rfm(customer)
        # Gross = 1,200,000. Net after 200,000 refund = 1,000,000
        assert profile.monetary_total_spent == Decimal('1000000')
        assert profile.refunds_deducted == Decimal('200000')
        assert profile.frequency_orders_count == 2
        assert profile.segment in (CustomerSegment.CHAMPION, CustomerSegment.LOYAL)
        assert profile.segment_reason != ""
        assert profile.last_calculated_at is not None

    # -------------------------------------------------------------------------
    # 6. Marketing Campaign Dispatching
    # -------------------------------------------------------------------------
    def test_marketing_campaign_dispatch(self):
        c1 = Customer.objects.create(
            store=self.store,
            full_name="مشتری الف",
            phone_number="09120000001",
            marketing_opt_in=True
        )
        CustomerProfile.objects.create(
            store=self.store,
            customer=c1,
            segment=CustomerSegment.LOYAL
        )

        campaign = MarketingCampaign.objects.create(
            store=self.store,
            name="کمپین قدردانی از مشتریان وفادار",
            channel=CampaignChannel.SMS,
            target_segment=CustomerSegment.LOYAL,
            message_template="سلام {name} عزیز، ۱۰٪ تخفیف وفاداری برای شما فعال شد."
        )

        # Mock Kavenegar SMS dispatch
        with mock.patch('apps.features.adapters.KavenegarSMSAdapter.send_sms') as mock_sms:
            mock_sms.return_value = {'status': 'DELIVERED', 'message_id': '112233'}

            res = dispatch_marketing_campaign(campaign, user=self.owner)
            assert res['status'] == 'SUCCESS'
            assert res['recipients'] == 1
            assert res['sent_count'] == 1
            assert res['delivered_count'] == 1

            campaign.refresh_from_db()
            assert campaign.status == CampaignStatus.SENT
            assert campaign.sent_at is not None

    # -------------------------------------------------------------------------
    # 7. Goods Receipt Quality Inspection (Acceptance vs Quarantined Rejection)
    # -------------------------------------------------------------------------
    def test_goods_receipt_quality_inspection_quarantine(self):
        supplier = Supplier.objects.create(
            store=self.store,
            name="تامین‌کننده پارچه ایرانیان",
            phone_number="02188889999"
        )
        prod = Product.objects.create(store=self.store, name="پیراهن نخی", slug="cotton-shirt")
        variant = ProductVariant.objects.create(
            store=self.store,
            product=prod,
            sku="SHIRT-COTTON-01",
            cost_price=Decimal('150000')
        )

        po = create_purchase_order(
            store=self.store,
            supplier=supplier,
            warehouse=self.warehouse,
            items_data=[{
                'variant': variant,
                'quantity_ordered': 50,
                'unit_cost': Decimal('150000')
            }],
            user=self.owner
        )
        approve_purchase_order(po, user=self.owner)
        mark_purchase_order_sent(po, user=self.owner)

        po_item = po.items.first()

        # Supplier delivers 50 units. QC inspection finds:
        # 40 units accepted into sellable warehouse inventory
        # 10 units defective/damaged (rejected to quarantine)
        receipt_data = [{
            'item_id': str(po_item.id),
            'quantity_received': 50,
            'quantity_accepted': 40,
            'quantity_rejected': 10,
            'rejection_reason': RejectionReason.DEFECTIVE,
            'inspection_notes': '۱۰ عدد دارای لکه و دوخت ناقص در درز آستین بودند.'
        }]

        updated_po = receive_po_goods(po, receipt_data, user=self.owner)
        assert updated_po.status == PurchaseOrderStatus.COMPLETED

        # Check QC Inspection Record
        inspection = GoodsReceiptInspection.objects.filter(purchase_order=po, variant=variant).first()
        assert inspection is not None
        assert inspection.quantity_received == 50
        assert inspection.quantity_accepted == 40
        assert inspection.quantity_rejected == 10
        assert inspection.rejection_reason == RejectionReason.DEFECTIVE
        assert '۱۰ عدد دارای لکه' in inspection.inspection_notes

        # CRITICAL VERIFICATION:
        # Physical sellable inventory in the warehouse MUST only increase by 40 (accepted), NOT 50!
        balance = InventoryBalance.objects.filter(warehouse=self.warehouse, variant=variant).first()
        assert balance is not None
        assert balance.on_hand_quantity == 40  # Reject is NOT in on_hand inventory!
        assert balance.available == 40
