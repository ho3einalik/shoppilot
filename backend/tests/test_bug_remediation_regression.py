import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.tenancy.models import Business, Store, StoreMembership, Role
from apps.catalog.models import Product, ProductVariant
from apps.inventory.models import Warehouse, InventoryBalance
from apps.inventory.services import adjust_stock
from apps.orders.models import Order, OrderItem, Customer, OrderStatus, PaymentStatus, FulfillmentStatus
from apps.orders.services import create_order, cancel_order, fulfill_order, generate_order_number
from apps.payments.models import PaymentTransaction, PaymentMethod, PaymentVerificationStatus
from apps.payments.gateways import GatewayPaymentResult
from apps.fulfillment.models import Shipment, Carrier, ShipmentStatus
from apps.fulfillment.services import IranPostAdapter, TipaxAdapter
from apps.returns.models import ReturnRequest, ReturnItem, ReturnStatus, RefundStatus, ReturnAction
from apps.returns.services import create_return_request, approve_return_request, inspect_and_process_return, generate_rma_number
from apps.marketing.models import MarketingCampaign, CampaignStatus, CampaignChannel
from apps.marketing.services import dispatch_marketing_campaign
from apps.automation.services import sanitize_payload


@pytest.mark.django_db
class TestPaymentGatewayRemediations:
    @pytest.fixture
    def setup_data(self):
        user = User.objects.create_user(email="pay_remedy@example.com", password="pass", full_name="Pay Owner")
        biz = Business.objects.create(name="Pay Biz", owner=user)
        store = Store.objects.create(business=biz, name="Pay Store", currency="IRT")
        StoreMembership.objects.create(store=store, user=user, role=Role.OWNER, is_active=True)
        warehouse = Warehouse.objects.create(store=store, name="Wh 1", is_default=True)
        customer = Customer.objects.create(
            store=store, full_name="Ali Payer", phone_number="09121112233"
        )
        order = Order.objects.create(
            store=store,
            order_number="ORD-REMEDY-001",
            customer=customer,
            warehouse=warehouse,
            order_status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.PENDING,
            currency="IRT",
            grand_total=Decimal('500000')
        )
        payment = PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=PaymentMethod.ONLINE_GATEWAY,
            amount=Decimal('500000'),
            currency="IRT",
            reference_number="AUTH-ZARIN-123456",
            status=PaymentVerificationStatus.PENDING_VERIFICATION
        )
        return {
            'store': store,
            'order': order,
            'payment': payment,
            'user': user,
            'customer': customer
        }

    def test_anonymous_callback_with_valid_gateway_verify(self, setup_data):
        client = APIClient()  # Unauthenticated anonymous customer returning from gateway
        payment = setup_data['payment']

        mock_result = GatewayPaymentResult(
            success=True,
            status='VERIFIED',
            tracking_code='1009876543',
            message='تراکنش با موفقیت در زرین‌پال تأیید شد.'
        )

        with patch('apps.payments.gateways.ZarinpalGatewayAdapter.verify_payment', return_value=mock_result):
            response = client.post(
                '/api/v1/payments/online-verify/',
                {'authority': 'AUTH-ZARIN-123456', 'Status': 'OK'},
                format='json'
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True
        assert response.data['tracking_code'] == '1009876543'

        payment.refresh_from_db()
        assert payment.status == PaymentVerificationStatus.VERIFIED
        assert payment.tracking_code == '1009876543'

        order = setup_data['order']
        order.refresh_from_db()
        assert order.payment_status == PaymentStatus.PAID

    def test_anonymous_callback_rejected_when_gateway_rejects(self, setup_data):
        client = APIClient()
        payment = setup_data['payment']

        mock_result = GatewayPaymentResult(
            success=False,
            status='REJECTED_BY_GATEWAY',
            message='تراکنش توسط درگاه تأیید نشد (کد وضعیت: -21).'
        )

        with patch('apps.payments.gateways.ZarinpalGatewayAdapter.verify_payment', return_value=mock_result):
            response = client.post(
                '/api/v1/payments/online-verify/',
                {'authority': 'AUTH-ZARIN-123456', 'Status': 'OK'},
                format='json'
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        payment.refresh_from_db()
        assert payment.status == PaymentVerificationStatus.REJECTED

    def test_forged_nok_cannot_mark_payment_rejected_without_gateway(self, setup_data):
        """User-controlled NOK status cannot reject payment if gateway confirms success."""
        client = APIClient()
        payment = setup_data['payment']

        mock_result = GatewayPaymentResult(
            success=True,
            status='VERIFIED',
            tracking_code='REF-FORGED-NOK-CHECK',
            message='تراکنش تأیید شد.'
        )

        with patch('apps.payments.gateways.ZarinpalGatewayAdapter.verify_payment', return_value=mock_result):
            response = client.post(
                '/api/v1/payments/online-verify/',
                {'authority': 'AUTH-ZARIN-123456', 'Status': 'NOK'},
                format='json'
            )

        assert response.status_code == status.HTTP_200_OK
        payment.refresh_from_db()
        assert payment.status == PaymentVerificationStatus.VERIFIED

    def test_communication_error_leaves_pending_not_rejected(self, setup_data):
        """Network timeout/communication error leaves payment in PENDING_VERIFICATION for reconciliation."""
        client = APIClient()
        payment = setup_data['payment']

        mock_result = GatewayPaymentResult(
            success=False,
            status='COMMUNICATION_ERROR',
            message='خطا در برقراری ارتباط با زرین‌پال'
        )

        with patch('apps.payments.gateways.ZarinpalGatewayAdapter.verify_payment', return_value=mock_result):
            response = client.post(
                '/api/v1/payments/online-verify/',
                {'authority': 'AUTH-ZARIN-123456'},
                format='json'
            )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.data.get('retry') is True
        payment.refresh_from_db()
        assert payment.status == PaymentVerificationStatus.PENDING_VERIFICATION

    def test_repeated_callbacks_are_idempotent(self, setup_data):
        """Repeated callbacks on already-verified payment must return 200 without duplicate modifications."""
        client = APIClient()
        payment = setup_data['payment']
        payment.status = PaymentVerificationStatus.VERIFIED
        payment.tracking_code = 'PREVIOUS-TRACKING-123'
        payment.save()

        response = client.post(
            '/api/v1/payments/online-verify/',
            {'authority': 'AUTH-ZARIN-123456'},
            format='json'
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['success'] is True
        assert 'از قبل تأیید شده است' in response.data['message']

    def test_concurrent_checkout_blocked_by_pending_payment(self, setup_data):
        """When a pending payment already covers remaining balance, a subsequent online checkout is blocked."""
        client = APIClient()
        client.force_authenticate(user=setup_data['user'])
        store = setup_data['store']
        order = setup_data['order']

        # Payment already exists with PENDING_VERIFICATION covering grand_total (500000)
        response = client.post(
            '/api/v1/payments/online-checkout/',
            {'order_id': str(order.id), 'gateway': 'zarinpal'},
            format='json',
            HTTP_X_STORE_ID=str(store.id)
        )
        assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
class TestOrderIntegrityRemediations:
    @pytest.fixture
    def setup_data(self):
        user = User.objects.create_user(email="order_rem@example.com", password="pass", full_name="Ord Owner")
        biz = Business.objects.create(name="Ord Biz", owner=user)
        store = Store.objects.create(business=biz, name="Ord Store")
        warehouse = Warehouse.objects.create(store=store, name="Wh 1", is_default=True)
        product = Product.objects.create(store=store, name="Product 1")
        variant = ProductVariant.objects.create(
            store=store, product=product, name="Var 1", sku="SKU-REM-1",
            cost_price=Decimal('10000'), retail_price=Decimal('25000')
        )
        adjust_stock(store=store, warehouse=warehouse, variant=variant, new_on_hand=20, user=user)
        return {
            'store': store,
            'warehouse': warehouse,
            'variant': variant,
            'user': user
        }

    def test_order_requires_phone_number(self, setup_data):
        """Customer phone number cannot be omitted or replaced with shared placeholder."""
        with pytest.raises(ValueError, match="شماره تماس مشتری الزامی است"):
            create_order(
                store=setup_data['store'],
                customer_data={'full_name': "Anonymous"},
                items_data=[{'variant_id': str(setup_data['variant'].id), 'quantity': 1, 'unit_price': Decimal('25000')}],
                warehouse=setup_data['warehouse'],
                user=setup_data['user']
            )

    def test_marketing_opt_in_defaults_false(self, setup_data):
        """Customer marketing_opt_in must default to False unless explicitly provided."""
        order = create_order(
            store=setup_data['store'],
            customer_data={'full_name': "Customer OptIn", 'phone_number': "09123334455"},
            items_data=[{'variant_id': str(setup_data['variant'].id), 'quantity': 1, 'unit_price': Decimal('25000')}],
            warehouse=setup_data['warehouse'],
            user=setup_data['user']
        )
        assert order.customer.marketing_opt_in is False

    def test_generate_order_number_uniqueness(self, setup_data):
        """Order number generation handles collision retries."""
        store = setup_data['store']
        num1 = generate_order_number(store)
        assert num1.startswith("ORD-")

        # Simulate existing order with candidate number to test collision retry
        Order.objects.create(
            store=store,
            order_number=num1,
            customer=Customer.objects.create(store=store, full_name="T1", phone_number="09111111111"),
            warehouse=setup_data['warehouse'],
            grand_total=Decimal('10000')
        )
        num2 = generate_order_number(store)
        assert num2 != num1


@pytest.mark.django_db
class TestFulfillmentTrackingTruthfulness:
    def test_iranpost_tracking_without_api_key(self):
        adapter = IranPostAdapter()
        shipment = MagicMock(spec=Shipment)
        shipment.store = None
        shipment.tracking_number = "123456789012345678901234"
        shipment.status = ShipmentStatus.IN_TRANSIT
        shipment.get_status_display.return_value = "در حال ارسال"

        res = adapter.query_live_tracking(shipment, store=None)
        assert res['is_live'] is False
        assert res['mode'] == 'EXTERNAL_PORTAL_FALLBACK'
        assert "post.ir" in res['tracking_url']

    def test_iranpost_tracking_with_api_key_not_implemented(self):
        adapter = IranPostAdapter()
        shipment = MagicMock(spec=Shipment)
        shipment.store = None
        shipment.tracking_number = "123456789012345678901234"
        shipment.status = ShipmentStatus.IN_TRANSIT
        shipment.get_status_display.return_value = "در حال ارسال"

        with patch('apps.features.adapters.get_integration_adapter') as mock_adapter:
            mock_inst = MagicMock()
            mock_inst.get_config.return_value = {'api_key': 'SECRET-POST-KEY'}
            mock_adapter.return_value = mock_inst

            fake_store = MagicMock()
            res = adapter.query_live_tracking(shipment, store=fake_store)
            assert res['is_live'] is False
            assert res['mode'] == 'API_NOT_IMPLEMENTED'

    def test_tipax_tracking_truthfulness(self):
        adapter = TipaxAdapter()
        shipment = MagicMock(spec=Shipment)
        shipment.store = None
        shipment.tracking_number = "TIPAX123456"
        shipment.status = ShipmentStatus.IN_TRANSIT
        shipment.get_status_display.return_value = "در حال ارسال"

        res = adapter.query_live_tracking(shipment, store=None)
        assert res['is_live'] is False
        assert res['mode'] == 'EXTERNAL_PORTAL_FALLBACK'


@pytest.mark.django_db
class TestReturnsAndFinanceRemediations:
    @pytest.fixture
    def setup_data(self):
        user = User.objects.create_user(email="ret_rem@example.com", password="pass", full_name="Ret Owner")
        biz = Business.objects.create(name="Ret Biz", owner=user)
        store = Store.objects.create(business=biz, name="Ret Store")
        warehouse = Warehouse.objects.create(store=store, name="Wh 1", is_default=True)
        product = Product.objects.create(store=store, name="Product Ret")
        variant = ProductVariant.objects.create(
            store=store, product=product, name="Var 1", sku="SKU-RET-ORIG",
            cost_price=Decimal('100000'), retail_price=Decimal('200000')
        )
        exchange_variant = ProductVariant.objects.create(
            store=store, product=product, name="Var Ex", sku="SKU-RET-EXCH",
            cost_price=Decimal('100000'), retail_price=Decimal('200000')
        )
        adjust_stock(store=store, warehouse=warehouse, variant=variant, new_on_hand=10, user=user)
        adjust_stock(store=store, warehouse=warehouse, variant=exchange_variant, new_on_hand=5, user=user)

        customer = Customer.objects.create(store=store, full_name="Ret Cust", phone_number="09124445566")
        order = Order.objects.create(
            store=store,
            order_number="ORD-RET-REM-1",
            customer=customer,
            warehouse=warehouse,
            order_status=OrderStatus.FULFILLED,
            fulfillment_status=FulfillmentStatus.FULFILLED,
            grand_total=Decimal('400000')
        )
        order_item = OrderItem.objects.create(
            order=order,
            variant=variant,
            variant_sku=variant.sku,
            variant_name=variant.name,
            quantity=2,
            unit_price=Decimal('200000'),
            cost_price_snapshot=Decimal('100000'),
            total_price=Decimal('400000')
        )
        return {
            'store': store,
            'warehouse': warehouse,
            'variant': variant,
            'exchange_variant': exchange_variant,
            'customer': customer,
            'order': order,
            'order_item': order_item,
            'user': user
        }

    def test_exchange_dispatch_checks_and_commits_stock(self, setup_data):
        """Exchange dispatch uses commit_stock_sale; fails if insufficient stock."""
        rma = create_return_request(
            order=setup_data['order'],
            items_data=[{'order_item': setup_data['order_item'], 'quantity': 1, 'reason': 'DEFECT'}],
            is_exchange=True,
            exchange_variant=setup_data['exchange_variant'],
            exchange_quantity=100,  # Only 5 on hand!
            user=setup_data['user']
        )
        approve_return_request(rma, user=setup_data['user'])

        item = rma.items.first()
        from django.core.exceptions import ValidationError
        with pytest.raises(ValidationError, match="کافی نیست"):
            inspect_and_process_return(
                rma=rma,
                inspection_items_data=[{'item_id': item.id, 'action': ReturnAction.RESTOCK, 'condition': 'AS_NEW'}],
                warehouse=setup_data['warehouse'],
                user=setup_data['user']
            )

    def test_finance_sync_failure_rolls_back_return_completion(self, setup_data):
        """Finance synchronization failure rolls back the return completion."""
        rma = create_return_request(
            order=setup_data['order'],
            items_data=[{'order_item': setup_data['order_item'], 'quantity': 1, 'reason': 'CUSTOMER_REMORSE'}],
            user=setup_data['user']
        )
        approve_return_request(rma, user=setup_data['user'])
        item = rma.items.first()

        with patch('apps.finance.models.RefundRecord.objects.get_or_create', side_effect=RuntimeError("Finance DB connection lost")):
            with pytest.raises(RuntimeError):
                inspect_and_process_return(
                    rma=rma,
                    inspection_items_data=[{'item_id': item.id, 'action': ReturnAction.RESTOCK, 'condition': 'AS_NEW'}],
                    warehouse=setup_data['warehouse'],
                    user=setup_data['user']
                )

        rma.refresh_from_db()
        assert rma.status == ReturnStatus.APPROVED  # Not COMPLETED!

    def test_generate_rma_number_uniqueness(self, setup_data):
        store = setup_data['store']
        rma1 = generate_rma_number(store)
        assert rma1.startswith("RMA-")


@pytest.mark.django_db
class TestMarketingAndAutomationRemediations:
    def test_all_failed_campaign_is_marked_cancelled(self):
        user = User.objects.create_user(email="mkt_rem@example.com", password="pass", full_name="Mkt Owner")
        biz = Business.objects.create(name="Mkt Biz", owner=user)
        store = Store.objects.create(business=biz, name="Mkt Store")
        Customer.objects.create(store=store, full_name="C1", phone_number="09121234567", marketing_opt_in=True)

        campaign = MarketingCampaign.objects.create(
            store=store,
            name="Summer Sale",
            channel=CampaignChannel.SMS,
            status=CampaignStatus.DRAFT,
            message_template="Sale 50%"
        )

        # Mock adapter returns failure for all sends
        mock_adapter = MagicMock()
        mock_adapter.send_sms.return_value = {'status': 'FAILED', 'error': 'Gateway timeout'}

        with patch('apps.marketing.services.get_integration_adapter', return_value=mock_adapter):
            result = dispatch_marketing_campaign(campaign)

        assert result['status'] == 'FAILED'
        campaign.refresh_from_db()
        assert campaign.status == CampaignStatus.CANCELLED

    def test_sanitize_payload_redacts_sensitive_keys_in_nested_lists(self):
        payload = {
            'order_id': '123',
            'customer_phone': '09121234567',
            'payments': [
                {'card_number': '6037991122334455', 'amount': 1000},
                {'token': 'SECRET_TOKEN_XYZ', 'cvv2': '123'}
            ]
        }
        sanitized = sanitize_payload(payload)
        assert sanitized['customer_phone'] == '0912****567'
        assert sanitized['payments'][0]['card_number'] == '***REDACTED***'
        assert sanitized['payments'][1]['token'] == '***REDACTED***'
        assert sanitized['payments'][1]['cvv2'] == '***REDACTED***'
