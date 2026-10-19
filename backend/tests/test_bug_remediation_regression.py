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


@pytest.mark.django_db
class TestComprehensiveCodeRemediations:
    @pytest.fixture
    def store_context(self):
        user = User.objects.create_user(email="comp_remedy@example.com", password="pass", full_name="Comp Owner")
        biz = Business.objects.create(name="Comp Biz", owner=user)
        store = Store.objects.create(business=biz, name="Comp Store", currency="IRT")
        StoreMembership.objects.create(store=store, user=user, role=Role.OWNER, is_active=True)
        warehouse = Warehouse.objects.create(store=store, name="Main Wh", is_default=True)
        product = Product.objects.create(store=store, name="Test Product")
        variant = ProductVariant.objects.create(
            store=store,
            product=product,
            sku="SKU-COMP-001",
            name="Variant 1",
            retail_price=Decimal('100000'),
            cost_price=Decimal('60000')
        )
        adjust_stock(store, warehouse, variant, 50, reference="INIT", user=user)
        customer = Customer.objects.create(
            store=store,
            full_name="Reza Test",
            phone_number="09129998877"
        )
        return {
            'user': user,
            'store': store,
            'warehouse': warehouse,
            'product': product,
            'variant': variant,
            'customer': customer
        }

    def test_customer_model_marketing_opt_in_defaults_to_false(self, store_context):
        """Item 7: Customer.marketing_opt_in must default to False on direct creation."""
        cust = Customer.objects.create(
            store=store_context['store'],
            full_name="Direct Cust",
            phone_number="09187654321"
        )
        assert cust.marketing_opt_in is False

    def test_online_gateway_refund_requires_config_or_manual_flag(self, store_context):
        """Item 1: Online payment refund fails safely if gateway not configured unless manual refund is flagged."""
        from rest_framework.exceptions import ValidationError
        from apps.payments.services import process_payment_refund

        store = store_context['store']
        order = Order.objects.create(
            store=store,
            order_number="ORD-REFUND-001",
            customer=store_context['customer'],
            warehouse=store_context['warehouse'],
            grand_total=Decimal('100000'),
            payment_status=PaymentStatus.PAID
        )
        payment = PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=PaymentMethod.ONLINE_GATEWAY,
            amount=Decimal('100000'),
            reference_number="AUTH-NO-TOKEN",
            status=PaymentVerificationStatus.VERIFIED
        )

        # 1. Automatic refund without token must fail and NOT mark payment REFUNDED
        with pytest.raises(ValidationError) as exc:
            process_payment_refund(payment=payment, amount=Decimal('100000'), reason="Faulty product", is_manual=False)
        assert any(phrase in str(exc.value) for phrase in ["توکن دسترسی درگاه", "پیکربندی نشده"])

        payment.refresh_from_db()
        assert payment.status == PaymentVerificationStatus.VERIFIED
        assert payment.refunded_amount == Decimal('0')

        # 2. Staff manual refund succeeds with explicit audit tag
        refunded = process_payment_refund(payment=payment, amount=Decimal('50000'), reason="Manual bank transfer", is_manual=True)
        payment.refresh_from_db()
        assert payment.refunded_amount == Decimal('50000')
        assert "[استرداد دستی]" in payment.rejection_reason

    def test_online_gateway_refund_with_successful_gateway_call(self, store_context):
        """Item 1: Online refund marks transaction REFUNDED when gateway refund returns success."""
        from apps.payments.services import process_payment_refund

        store = store_context['store']
        order = Order.objects.create(
            store=store,
            order_number="ORD-REFUND-002",
            customer=store_context['customer'],
            warehouse=store_context['warehouse'],
            grand_total=Decimal('100000'),
            payment_status=PaymentStatus.PAID
        )
        payment = PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=PaymentMethod.ONLINE_GATEWAY,
            amount=Decimal('100000'),
            reference_number="AUTH-VALID-REFUND",
            status=PaymentVerificationStatus.VERIFIED
        )

        mock_result = GatewayPaymentResult(
            success=True,
            status='REFUNDED',
            tracking_code='ZARIN-REF-998877',
            message='استرداد وجه با موفقیت انجام شد.'
        )

        with patch('apps.payments.gateways.ZarinpalGatewayAdapter.refund_payment', return_value=mock_result):
            refunded = process_payment_refund(payment=payment, amount=Decimal('100000'), reason="Return", is_manual=False)

        payment.refresh_from_db()
        assert payment.status == PaymentVerificationStatus.REFUNDED
        assert payment.tracking_code == 'ZARIN-REF-998877'
        assert "[استرداد درگاه]" in payment.rejection_reason

    def test_checkout_deducts_pending_sum_and_pre_creates_transaction(self, store_context):
        """Item 2: Checkout accounts for pending transactions and pre-creates transaction before network call."""
        client = APIClient()
        client.force_authenticate(user=store_context['user'])
        store = store_context['store']

        order = Order.objects.create(
            store=store,
            order_number="ORD-RACE-001",
            customer=store_context['customer'],
            warehouse=store_context['warehouse'],
            grand_total=Decimal('100000'),
            payment_status=PaymentStatus.PARTIALLY_PAID
        )
        # 30,000 verified
        PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=PaymentMethod.CARD_TO_CARD,
            amount=Decimal('30000'),
            status=PaymentVerificationStatus.VERIFIED
        )
        # 20,000 pending
        PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=PaymentMethod.ONLINE_GATEWAY,
            amount=Decimal('20000'),
            status=PaymentVerificationStatus.PENDING_VERIFICATION
        )

        # Remaining payable should be 100,000 - 30,000 - 20,000 = 50,000!
        mock_gateway = MagicMock()
        mock_gateway.request_payment.return_value = {
            'success': True,
            'authority': 'ZARIN-NEW-AUTH-50000',
            'payment_url': 'https://sandbox.zarinpal.com/pg/StartPay/ZARIN-NEW-AUTH-50000'
        }

        with patch('apps.payments.views.get_payment_gateway', return_value=mock_gateway):
            resp = client.post(
                '/api/v1/payments/online-checkout/',
                {'order_id': str(order.id)},
                HTTP_X_STORE_ID=str(store.id),
                format='json'
            )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['amount'] == Decimal('50000')
        assert resp.data['authority'] == 'ZARIN-NEW-AUTH-50000'

        # Verify gateway was requested for exactly 50,000
        mock_gateway.request_payment.assert_called_once()
        assert mock_gateway.request_payment.call_args[1]['amount'] == Decimal('50000')

        # Verify transaction is persisted with authority in DB
        tx = PaymentTransaction.objects.get(id=resp.data['payment_id'])
        assert tx.reference_number == 'ZARIN-NEW-AUTH-50000'
        assert tx.status == PaymentVerificationStatus.PENDING_VERIFICATION

    def test_checkout_gateway_failure_marks_transaction_rejected_and_frees_slot(self, store_context):
        """Item 2: If gateway network call fails, transaction is marked REJECTED so balance is not permanently locked."""
        client = APIClient()
        client.force_authenticate(user=store_context['user'])
        store = store_context['store']

        order = Order.objects.create(
            store=store,
            order_number="ORD-FAIL-001",
            customer=store_context['customer'],
            warehouse=store_context['warehouse'],
            grand_total=Decimal('50000'),
            payment_status=PaymentStatus.PENDING
        )

        mock_gateway = MagicMock()
        mock_gateway.request_payment.return_value = {
            'success': False,
            'status': 'COMMUNICATION_ERROR',
            'message': 'درگاه در دسترس نیست.'
        }

        with patch('apps.payments.views.get_payment_gateway', return_value=mock_gateway):
            resp = client.post(
                '/api/v1/payments/online-checkout/',
                {'order_id': str(order.id)},
                HTTP_X_STORE_ID=str(store.id),
                format='json'
            )

        assert resp.status_code == status.HTTP_502_BAD_GATEWAY
        # Pre-created transaction must be marked REJECTED
        failed_tx = PaymentTransaction.objects.filter(order=order).first()
        assert failed_tx is not None
        assert failed_tx.status == PaymentVerificationStatus.REJECTED

    def test_online_verify_rejects_non_gateway_and_terminal_states(self, store_context):
        """Item 3: Callback ignores non-gateway payments and rejects re-verifying refunded/rejected transactions."""
        client = APIClient()
        store = store_context['store']

        order = Order.objects.create(
            store=store,
            order_number="ORD-VERIFY-001",
            customer=store_context['customer'],
            warehouse=store_context['warehouse'],
            grand_total=Decimal('50000'),
            payment_status=PaymentStatus.PENDING
        )

        # 1. Non-gateway method must not be verified by online callback
        PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=PaymentMethod.CARD_TO_CARD,
            amount=Decimal('50000'),
            reference_number="NON-GATEWAY-REF",
            status=PaymentVerificationStatus.PENDING_VERIFICATION
        )
        resp1 = client.get('/api/v1/payments/online-verify/', {'Authority': 'NON-GATEWAY-REF'})
        assert resp1.status_code == status.HTTP_404_NOT_FOUND

        # 2. Refunded transaction must reject re-verification
        refunded_tx = PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=PaymentMethod.ONLINE_GATEWAY,
            amount=Decimal('50000'),
            reference_number="REFUNDED-AUTH-001",
            status=PaymentVerificationStatus.REFUNDED
        )
        resp2 = client.get('/api/v1/payments/online-verify/', {'Authority': 'REFUNDED-AUTH-001'})
        assert resp2.status_code == status.HTTP_400_BAD_REQUEST
        assert resp2.data['status'] == 'ALREADY_REFUNDED'

        # 3. Rejected transaction must reject re-verification
        rejected_tx = PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=PaymentMethod.ONLINE_GATEWAY,
            amount=Decimal('50000'),
            reference_number="REJECTED-AUTH-001",
            status=PaymentVerificationStatus.REJECTED,
            rejection_reason="Card expired"
        )
        resp3 = client.get('/api/v1/payments/online-verify/', {'Authority': 'REJECTED-AUTH-001'})
        assert resp3.status_code == status.HTTP_400_BAD_REQUEST
        assert resp3.data['status'] == 'ALREADY_REJECTED'

    def test_commit_stock_sale_unreserved_protects_active_reservations(self, store_context):
        """Item 4: commit_stock_sale with is_reservation=False checks available stock and does not deduct reserved stock."""
        from apps.inventory.services import commit_stock_sale, reserve_stock, InsufficientStockError
        from apps.inventory.models import InventoryBalance

        store = store_context['store']
        warehouse = store_context['warehouse']
        variant = store_context['variant']

        # Stock state: 10 on hand, 8 reserved for Order A (2 available)
        bal = InventoryBalance.objects.get(store=store, warehouse=warehouse, variant=variant)
        bal.on_hand_quantity = 10
        bal.reserved_quantity = 8
        bal.save()

        assert bal.available == 2

        # Direct sale of 2 units without reservation should succeed
        commit_stock_sale(store, warehouse, variant, quantity=2, is_reservation=False)
        bal.refresh_from_db()
        assert bal.on_hand_quantity == 8
        assert bal.reserved_quantity == 8  # Order A's reservation remains completely protected!
        assert bal.available == 0

        # Attempting another direct sale when available is 0 must raise InsufficientStockError
        with pytest.raises(InsufficientStockError) as exc:
            commit_stock_sale(store, warehouse, variant, quantity=1, is_reservation=False)
        assert "موجودی آزاد" in str(exc.value)

    def test_create_order_item_and_discount_validations(self, store_context):
        """Item 5: create_order validates item discounts and total discount upfront without reserving stock."""
        store = store_context['store']
        warehouse = store_context['warehouse']
        variant = store_context['variant']
        bal = InventoryBalance.objects.get(store=store, warehouse=warehouse, variant=variant)
        initial_reserved = bal.reserved_quantity

        # 1. Unit discount > unit price must fail upfront
        with pytest.raises(ValueError) as exc1:
            create_order(
                store=store,
                customer_data={'phone': '09123334455', 'name': 'Disc Cust'},
                items_data=[{
                    'variant_id': str(variant.id),
                    'quantity': 2,
                    'unit_price': 100000,
                    'unit_discount': 150000  # Invalid! Greater than unit_price
                }],
                warehouse=warehouse
            )
        assert "تخفیف ردیف کالا" in str(exc1.value)

        # Inventory must NOT have been reserved
        bal.refresh_from_db()
        assert bal.reserved_quantity == initial_reserved

        # 2. Total order discount > items + shipping must fail upfront
        with pytest.raises(ValueError) as exc2:
            create_order(
                store=store,
                customer_data={'phone': '09123334455', 'name': 'Disc Cust'},
                items_data=[{
                    'variant_id': str(variant.id),
                    'quantity': 1,
                    'unit_price': 100000,
                    'unit_discount': 0
                }],
                warehouse=warehouse,
                shipping_cost=Decimal('20000'),
                discount_amount=Decimal('150000')  # 150,000 > 100,000 + 20,000
            )
        assert "مبلغ تخفیف سفارش" in str(exc2.value)

        bal.refresh_from_db()
        assert bal.reserved_quantity == initial_reserved

    def test_create_order_retries_on_order_number_collision(self, store_context):
        """Item 6: create_order retries with savepoint on IntegrityError collision without crashing."""
        from django.db import IntegrityError
        store = store_context['store']
        warehouse = store_context['warehouse']
        variant = store_context['variant']

        # Pre-create an order
        existing_order = Order.objects.create(
            store=store,
            order_number="ORD-COLLIDE-TEST",
            customer=store_context['customer'],
            warehouse=warehouse,
            grand_total=Decimal('50000')
        )

        attempts = [0]
        original_gen = generate_order_number

        def colliding_generator(st):
            attempts[0] += 1
            if attempts[0] == 1:
                return "ORD-COLLIDE-TEST"  # Force collision on 1st attempt
            return original_gen(st)

        with patch('apps.orders.services.generate_order_number', side_effect=colliding_generator):
            order = create_order(
                store=store,
                customer_data={'phone': '09128887766', 'name': 'Collision User'},
                items_data=[{
                    'variant_id': str(variant.id),
                    'quantity': 1,
                    'unit_price': 100000
                }],
                warehouse=warehouse
            )

        assert order is not None
        assert order.order_number != "ORD-COLLIDE-TEST"
        assert attempts[0] >= 2

    def test_deeply_nested_payload_sanitization(self):
        """Item 8: sanitize_payload handles deeply nested lists, tuples, and dicts."""
        payload = {
            'action': 'DISPATCH',
            'nested_lists': [
                ['09121112233', 'public_text'],
                [{'api_key': 'SECRET_123', 'phone': '09351234567'}],
                ('tuple_item', '09198765432')
            ],
            'meta': {
                'auth': {'credentials': {'token': 'SECRET_TOKEN'}},
                'deep_phones': [{'contact': '09101234567'}]
            }
        }

        sanitized = sanitize_payload(payload)
        # Lists and tuples
        assert sanitized['nested_lists'][0][0] == '0912****233'
        assert sanitized['nested_lists'][0][1] == 'public_text'
        assert sanitized['nested_lists'][1][0]['api_key'] == '***REDACTED***'
        assert sanitized['nested_lists'][1][0]['phone'] == '0935****567'
        assert sanitized['nested_lists'][2][1] == '0919****432'
        # Nested dicts
        assert sanitized['meta']['auth']['credentials'] == '***REDACTED***'
        assert sanitized['meta']['deep_phones'][0]['contact'] == '0910****567'
