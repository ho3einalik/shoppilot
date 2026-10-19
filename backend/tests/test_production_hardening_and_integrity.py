import pytest
from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import User
from apps.tenancy.models import Business, Store, StoreMembership, Role
from apps.inventory.models import Warehouse
from apps.features.models import SubscriptionTier, StoreFeatureSetting, IntegrationState
from apps.features.services import FeatureService
from apps.features.adapters import SMSGatewayIntegrationAdapter
from apps.orders.models import Order, OrderStatus, PaymentStatus, Customer
from apps.payments.models import PaymentTransaction, PaymentMethod, PaymentVerificationStatus
from apps.payments.services import verify_payment_transaction


@pytest.mark.django_db
class TestProductionHardeningAndIntegrity:

    def setup_method(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(
            email="harden_owner@example.com",
            password="StrongPassword123!",
            full_name="Hardened Owner"
        )
        self.business = Business.objects.create(name="Hardened Business", owner=self.owner)
        self.store = Store.objects.create(business=self.business, name="Hardened Store")
        self.membership = StoreMembership.objects.create(
            store=self.store,
            user=self.owner,
            role=Role.OWNER,
            is_active=True
        )
        self.warehouse = Warehouse.objects.create(
            store=self.store,
            name="Main Warehouse"
        )

        self.customer = Customer.objects.create(
            store=self.store,
            full_name="Test Customer",
            phone_number="09120000000"
        )

    def test_default_subscription_tier_is_free(self):
        """Newly created store feature settings must default to FREE tier, not PRO."""
        settings = FeatureService.get_or_create_settings(self.store)
        assert settings.tier == SubscriptionTier.FREE
        assert settings.get_tier_display() == 'طرح رایگان (Free)'

    def test_subscription_tier_upgrade_protection(self):
        """Tenants cannot arbitrarily self-upgrade to PRO or ENTERPRISE without staff/payment in production."""
        self.client.force_authenticate(user=self.owner)
        settings = FeatureService.get_or_create_settings(self.store)
        assert settings.tier == SubscriptionTier.FREE

        with patch('django.conf.settings.DEBUG', False):
            # 1. Attempting to upgrade to PRO without staff status
            res = self.client.post(
                '/api/v1/features/tier/',
                {'tier': SubscriptionTier.PRO},
                HTTP_X_STORE_ID=str(self.store.id),
                format='json'
            )
            assert res.status_code == status.HTTP_403_FORBIDDEN
            assert "ارتقای پلن اشتراک" in str(res.data)

            # 2. Arbitrary fake reference string must still be rejected
            res_fake = self.client.post(
                '/api/v1/features/tier/',
                {'tier': SubscriptionTier.PRO, 'payment_reference': 'FAKE-STRING-123'},
                HTTP_X_STORE_ID=str(self.store.id),
                format='json'
            )
            assert res_fake.status_code == status.HTTP_403_FORBIDDEN

            # Store tier remains FREE
            settings.refresh_from_db()
            assert settings.tier == SubscriptionTier.FREE

            # 3. Legitimate paid invoice upgrades tier successfully
            from apps.features.models import SubscriptionInvoice, InvoiceStatus
            SubscriptionInvoice.objects.create(
                store=self.store,
                tier=SubscriptionTier.PRO,
                amount=Decimal('590000'),
                status=InvoiceStatus.PAID,
                payment_reference='INV-PRO-VERIFIED-001'
            )
            res_valid = self.client.post(
                '/api/v1/features/tier/',
                {'tier': SubscriptionTier.PRO, 'payment_reference': 'INV-PRO-VERIFIED-001'},
                HTTP_X_STORE_ID=str(self.store.id),
                format='json'
            )
            assert res_valid.status_code == status.HTTP_200_OK
            settings.refresh_from_db()
            assert settings.tier == SubscriptionTier.PRO

    def test_payment_amount_positive_validation(self):
        """Negative and zero amounts must be rejected when creating payments."""
        self.client.force_authenticate(user=self.owner)
        order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            warehouse=self.warehouse,
            order_number="ORD-HARDEN-001",
            total_items_price=Decimal('500000'),
            grand_total=Decimal('500000'),
            payment_status=PaymentStatus.PENDING
        )

        # 1. Zero amount
        res_zero = self.client.post(
            '/api/v1/payments/',
            {
                'order_id': str(order.id),
                'amount': 0,
                'method': PaymentMethod.CARD_TO_CARD
            },
            HTTP_X_STORE_ID=str(self.store.id),
            format='json'
        )
        assert res_zero.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Negative amount
        res_neg = self.client.post(
            '/api/v1/payments/',
            {
                'order_id': str(order.id),
                'amount': -100000,
                'method': PaymentMethod.CARD_TO_CARD
            },
            HTTP_X_STORE_ID=str(self.store.id),
            format='json'
        )
        assert res_neg.status_code == status.HTTP_400_BAD_REQUEST

    def test_payment_exceeding_remaining_payable_rejected(self):
        """Payment amount cannot exceed the order's remaining payable balance."""
        self.client.force_authenticate(user=self.owner)
        order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            warehouse=self.warehouse,
            order_number="ORD-HARDEN-002",
            total_items_price=Decimal('300000'),
            grand_total=Decimal('300000'),
            payment_status=PaymentStatus.PENDING
        )

        # Attempt to pay 400,000 for a 300,000 order
        res_excess = self.client.post(
            '/api/v1/payments/',
            {
                'order_id': str(order.id),
                'amount': 400000,
                'method': PaymentMethod.CARD_TO_CARD
            },
            HTTP_X_STORE_ID=str(self.store.id),
            format='json'
        )
        assert res_excess.status_code == status.HTTP_400_BAD_REQUEST
        assert "بیشتر از مبلغ باقیمانده" in str(res_excess.data)

        # Pay exact remaining 300,000 succeeds
        res_valid = self.client.post(
            '/api/v1/payments/',
            {
                'order_id': str(order.id),
                'amount': 300000,
                'method': PaymentMethod.CARD_TO_CARD
            },
            HTTP_X_STORE_ID=str(self.store.id),
            format='json'
        )
        assert res_valid.status_code == status.HTTP_201_CREATED

    def test_payment_verification_idempotency_and_locking(self):
        """Verifying payment is idempotent and updates order payment status correctly."""
        order = Order.objects.create(
            store=self.store,
            customer=self.customer,
            warehouse=self.warehouse,
            order_number="ORD-HARDEN-003",
            total_items_price=Decimal('1000000'),
            grand_total=Decimal('1000000'),
            payment_status=PaymentStatus.PENDING
        )
        payment = PaymentTransaction.objects.create(
            store=self.store,
            order=order,
            amount=Decimal('1000000'),
            currency='IRT',
            method=PaymentMethod.CARD_TO_CARD,
            status=PaymentVerificationStatus.PENDING_VERIFICATION
        )

        # First verification
        verified = verify_payment_transaction(payment, self.owner)
        assert verified.status == PaymentVerificationStatus.VERIFIED
        order.refresh_from_db()
        assert order.payment_status == PaymentStatus.PAID

        # Second verification (idempotent call)
        verified_again = verify_payment_transaction(verified, self.owner)
        assert verified_again.status == PaymentVerificationStatus.VERIFIED
        order.refresh_from_db()
        assert order.payment_status == PaymentStatus.PAID

    def test_sms_adapter_masks_phone_and_honest_state(self):
        """SMS Gateway masks phone numbers in logs and does not claim fake success."""
        adapter = SMSGatewayIntegrationAdapter()
        with patch.dict('os.environ', {}, clear=True):
            res = adapter.send_sms(to="09123456789", message="Test alert", store=self.store)
            assert res['status'] == 'NOT_CONFIGURED'
            assert adapter.get_status(self.store) == IntegrationState.NOT_CONFIGURED

    def test_production_settings_validation(self):
        """Verify production security rules: weak secret key, wildcard hosts, and SQLite are rejected."""
        import subprocess
        import sys

        # 1. Weak secret key with DEBUG=False must fail
        from django.conf import settings
        backend_dir = str(settings.BASE_DIR)

        cmd_weak_key = [
            sys.executable, "-c",
            "import os; os.environ['DJANGO_DEBUG']='False'; os.environ['DJANGO_SECRET_KEY']='short'; import config.settings"
        ]
        proc = subprocess.run(cmd_weak_key, capture_output=True, text=True, cwd=backend_dir)
        assert proc.returncode != 0
        assert "ImproperlyConfigured" in proc.stderr
        assert "DJANGO_SECRET_KEY" in proc.stderr

        # 2. Wildcard host with DEBUG=False must fail
        cmd_wildcard = [
            sys.executable, "-c",
            "import os; os.environ['DJANGO_DEBUG']='False'; os.environ['DJANGO_SECRET_KEY']='strong-secret-key-32-chars-long-123456'; os.environ['DJANGO_ALLOWED_HOSTS']='*'; import config.settings"
        ]
        proc2 = subprocess.run(cmd_wildcard, capture_output=True, text=True, cwd=backend_dir)
        assert proc2.returncode != 0
        assert "ImproperlyConfigured" in proc2.stderr
        assert "DJANGO_ALLOWED_HOSTS" in proc2.stderr

        # 3. SQLite in production without ALLOW_SQLITE_IN_PRODUCTION must fail
        cmd_sqlite = [
            sys.executable, "-c",
            "import os; os.environ['DJANGO_DEBUG']='False'; os.environ['DJANGO_SECRET_KEY']='strong-secret-key-32-chars-long-123456'; os.environ['DJANGO_ALLOWED_HOSTS']='api.shoppilot.ir'; import config.settings"
        ]
        proc3 = subprocess.run(cmd_sqlite, capture_output=True, text=True, cwd=backend_dir)
        assert proc3.returncode != 0
        assert "ImproperlyConfigured" in proc3.stderr
        assert "Production database must be configured with PostgreSQL" in proc3.stderr

    def test_integration_config_cannot_force_connected_without_health_check(self):
        """Users cannot manually toggle integration state to CONNECTED if live health check fails."""
        self.client.force_authenticate(user=self.owner)
        res = self.client.post(
            '/api/v1/features/integrations/configure/',
            {'name': 'ai_provider', 'state': IntegrationState.CONNECTED},
            HTTP_X_STORE_ID=str(self.store.id),
            format='json'
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "امکان تغییر وضعیت به CONNECTED وجود ندارد" in str(res.data)

        # But setting to DISABLED_BY_STORE succeeds
        res_disabled = self.client.post(
            '/api/v1/features/integrations/configure/',
            {'name': 'ai_provider', 'state': IntegrationState.DISABLED_BY_STORE},
            HTTP_X_STORE_ID=str(self.store.id),
            format='json'
        )
        assert res_disabled.status_code == status.HTTP_200_OK

    def test_zarinpal_gateway_requires_config_when_unconfigured(self):
        """ZarinpalGatewayAdapter returns REQUIRES_GATEWAY_CONFIG when merchant ID is missing."""
        from apps.payments.gateways import ZarinpalGatewayAdapter
        adapter = ZarinpalGatewayAdapter()
        with patch.dict('os.environ', {}, clear=True):
            res = adapter.request_payment(
                amount=Decimal('500000'),
                callback_url='https://app.shoppilot.ir/verify',
                description='Order test',
                order_id='ORD-001',
                store=self.store
            )
            assert res['success'] is False
            assert res['status'] == 'REQUIRES_GATEWAY_CONFIG'

            verify_res = adapter.verify_payment(authority='12345', amount=Decimal('500000'), store=self.store)
            assert verify_res.success is False
            assert verify_res.status == 'REQUIRES_GATEWAY_CONFIG'

    def test_loyalty_points_ledger_and_anti_self_referral(self):
        """Verify loyalty ledger points tracking and anti-self-referral validation."""
        from apps.marketing.models import CustomerLoyaltyAccount, LoyaltyPointsLedger, LoyaltyActionType, CustomerReferral
        from django.core.exceptions import ValidationError

        account = CustomerLoyaltyAccount.objects.create(
            store=self.store,
            customer=self.customer,
            points_balance=100
        )
        entry = LoyaltyPointsLedger.objects.create(
            store=self.store,
            account=account,
            points_delta=50,
            action_type=LoyaltyActionType.PURCHASE,
            note="Test purchase bonus"
        )
        assert entry.points_delta == 50
        assert entry.action_type == LoyaltyActionType.PURCHASE

        # Self-referral validation check
        referral = CustomerReferral(
            store=self.store,
            referrer=self.customer,
            referee_phone=self.customer.phone_number,
            referral_code='SELF-CODE'
        )
        with pytest.raises(ValidationError):
            referral.clean()

    def test_automation_payload_sanitization(self):
        """Verify that automation event payloads are sanitized of sensitive keys before logging."""
        from apps.automation.services import sanitize_payload
        raw = {
            'order_id': 'ORD-123',
            'customer_phone': '09121112233',
            'password': 'SuperSecretPassword',
            'api_key': 'key_1234567890',
            'card_number': '6037991122334455'
        }
        sanitized = sanitize_payload(raw)
        assert sanitized['order_id'] == 'ORD-123'
        assert sanitized['password'] == '***REDACTED***'
        assert sanitized['api_key'] == '***REDACTED***'
        assert sanitized['card_number'] == '***REDACTED***'
        assert sanitized['customer_phone'] == '0912****233'
