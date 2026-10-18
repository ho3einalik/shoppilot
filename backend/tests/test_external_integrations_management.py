import pytest
from decimal import Decimal
from unittest import mock
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import User
from apps.tenancy.models import Business, Store, StoreMembership, Role, MembershipStatus
from apps.features.models import (
    StoreFeatureSetting,
    StoreIntegrationConfig,
    IntegrationState,
    SubscriptionTier
)
from apps.features.adapters import (
    IntegrationRegistry,
    KavenegarSMSAdapter,
    InstagramIntegrationAdapter,
    ZarinpalPaymentAdapter,
    GoogleGeminiAIAdapter,
    SMTPEmailAdapter,
    IranPostShippingAdapter
)
from apps.features.security import encrypt_secret, decrypt_secret, mask_secret


@pytest.mark.django_db
class TestExternalIntegrationsManagement:

    @pytest.fixture(autouse=True)
    def setup_data(self):
        # Store A Setup
        self.owner_a = User.objects.create_user(
            email="owner_a@testshop.ir",
            password="StrongPassword123!",
            full_name="Owner Store A"
        )
        self.biz_a = Business.objects.create(name="Business A", owner=self.owner_a)
        self.store_a = Store.objects.create(business=self.biz_a, name="Store A")
        StoreMembership.objects.create(
            store=self.store_a,
            user=self.owner_a,
            role=Role.OWNER,
            status=MembershipStatus.ACTIVE,
            is_active=True
        )

        # Staff in Store A (Fulfillment staff / Read-only)
        self.staff_a = User.objects.create_user(
            email="staff_a@testshop.ir",
            password="StrongPassword123!",
            full_name="Staff Store A"
        )
        StoreMembership.objects.create(
            store=self.store_a,
            user=self.staff_a,
            role=Role.FULFILLMENT_STAFF,
            status=MembershipStatus.ACTIVE,
            is_active=True
        )

        # Store B Setup (for multi-tenant isolation verification)
        self.owner_b = User.objects.create_user(
            email="owner_b@testshop.ir",
            password="StrongPassword123!",
            full_name="Owner Store B"
        )
        self.biz_b = Business.objects.create(name="Business B", owner=self.owner_b)
        self.store_b = Store.objects.create(business=self.biz_b, name="Store B")
        StoreMembership.objects.create(
            store=self.store_b,
            user=self.owner_b,
            role=Role.OWNER,
            status=MembershipStatus.ACTIVE,
            is_active=True
        )

        # API Clients
        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.owner_a)
        self.client_a.defaults['HTTP_X_STORE_ID'] = str(self.store_a.id)

        self.staff_client_a = APIClient()
        self.staff_client_a.force_authenticate(user=self.staff_a)
        self.staff_client_a.defaults['HTTP_X_STORE_ID'] = str(self.store_a.id)

        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.owner_b)
        self.client_b.defaults['HTTP_X_STORE_ID'] = str(self.store_b.id)

    # 1. Fetch list of integrations and schemas
    def test_get_canonical_integrations_list_and_schemas(self):
        res = self.client_a.get('/api/v1/features/integrations/?canonical=true')
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 6

        categories = {item['category'] for item in data}
        assert {'SMS', 'SOCIAL', 'PAYMENT', 'SHIPPING', 'AI', 'EMAIL'}.issubset(categories)

        # Verify schema structure of SMS
        sms_item = next(item for item in data if item['id'] == 'sms_kavenegar')
        assert sms_item['name'] == 'sms_kavenegar'
        assert any(f['name'] == 'api_key' and f['is_secret'] is True for f in sms_item['schema'])
        assert any(f['name'] == 'sender_line' for f in sms_item['schema'])

    # 2. Save valid config and reject invalid inputs (SSRF)
    def test_save_config_and_ssrf_rejection(self):
        # Valid config save
        res_valid = self.client_a.post(
            '/api/v1/features/integrations/sms_kavenegar/save/',
            {
                'config': {
                    'api_key': 'kavenegar_test_api_key_12345',
                    'sender_line': '10008585'
                }
            },
            format='json'
        )
        assert res_valid.status_code == status.HTTP_200_OK
        assert res_valid.json()['status'] == IntegrationState.CONFIGURED

        # SSRF Attempt: Trying to point AI or webhook to internal AWS/GCP metadata IP or loopback
        res_ssrf = self.client_a.post(
            '/api/v1/features/integrations/ai_gemini/save/',
            {
                'config': {
                    'api_key': 'gemini_test_key_abc',
                    'custom_api_url': 'http://127.0.0.1:8000/internal'
                }
            },
            format='json'
        )
        assert res_ssrf.status_code == status.HTTP_400_BAD_REQUEST
        assert "دسترسی به آدرس داخلی" in str(res_ssrf.data) or "مسدود است" in str(res_ssrf.data)

    # 3. Prevent tenant cross-access: Store A cannot access Store B's integration
    def test_multi_tenant_isolation(self):
        # Store A configures its SMS key
        self.client_a.post(
            '/api/v1/features/integrations/sms_kavenegar/save/',
            {'config': {'api_key': 'STORE_A_EXCLUSIVE_KEY', 'sender_line': '10001111'}},
            format='json'
        )

        # Store B requests SMS integration config
        res_b = self.client_b.get('/api/v1/features/integrations/sms_kavenegar/')
        assert res_b.status_code == status.HTTP_200_OK
        data_b = res_b.json()
        # Store B has not configured SMS yet -> must be NOT_CONFIGURED
        assert data_b['status'] == IntegrationState.NOT_CONFIGURED
        assert data_b['config'].get('sender_line') != '10001111'

    # 4. Secret masking in API responses
    def test_secret_masking_in_api_response(self):
        raw_secret = "my_super_secret_kavenegar_key_9999"
        self.client_a.post(
            '/api/v1/features/integrations/sms_kavenegar/save/',
            {'config': {'api_key': raw_secret, 'sender_line': '20002222'}},
            format='json'
        )

        res = self.client_a.get('/api/v1/features/integrations/sms_kavenegar/')
        assert res.status_code == status.HTTP_200_OK
        config = res.json()['config']
        assert raw_secret not in str(res.json())
        assert '••••••••' in config['api_key']
        assert config['api_key_is_set'] is True

    # 5. Secrets encrypted at rest in database
    def test_secrets_encrypted_at_rest_in_database(self):
        raw_secret = "raw_unencrypted_secret_to_verify"
        self.client_a.post(
            '/api/v1/features/integrations/sms_kavenegar/save/',
            {'config': {'api_key': raw_secret}},
            format='json'
        )

        record = StoreIntegrationConfig.objects.get(store=self.store_a, integration_id='sms_kavenegar')
        db_stored_val = record.config_data['api_key']
        assert raw_secret not in db_stored_val
        assert db_stored_val.startswith('enc:')
        assert decrypt_secret(db_stored_val) == raw_secret

    # 6. Successful and failed connectivity tests
    def test_connection_test_success_and_failure(self):
        adapter = IntegrationRegistry.get_adapter('sms_kavenegar')

        # Test failure scenario (e.g. invalid credentials)
        with mock.patch.object(adapter, '_execute_live_test') as mock_test:
            from apps.features.adapters import IntegrationHealthResult
            mock_test.return_value = IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message="کلید وب‌سرویس نامعتبر است."
            )
            res_fail = self.client_a.post('/api/v1/features/integrations/sms_kavenegar/test/')
            assert res_fail.status_code == status.HTTP_400_BAD_REQUEST
            assert res_fail.json()['status'] == IntegrationState.TEST_FAILED

            record = StoreIntegrationConfig.objects.get(store=self.store_a, integration_id='sms_kavenegar')
            assert record.status == IntegrationState.TEST_FAILED
            assert record.last_test_success is False

        # Test success scenario
        with mock.patch.object(adapter, '_execute_live_test') as mock_test:
            mock_test.return_value = IntegrationHealthResult(
                state=IntegrationState.READY,
                message="اتصال با موفقیت تأیید شد.",
                details={'credit': 500000}
            )
            res_success = self.client_a.post('/api/v1/features/integrations/sms_kavenegar/test/')
            assert res_success.status_code == status.HTTP_200_OK
            assert res_success.json()['status'] == IntegrationState.READY

            record.refresh_from_db()
            assert record.status == IntegrationState.READY
            assert record.last_test_success is True
            assert record.last_tested_at is not None

    # 7. Cannot activate without a passing test
    def test_cannot_activate_without_successful_test(self):
        # Create unverified or failed config
        StoreIntegrationConfig.objects.create(
            store=self.store_a,
            integration_id='sms_kavenegar',
            status=IntegrationState.TEST_FAILED,
            last_test_success=False
        )

        res = self.client_a.post('/api/v1/features/integrations/sms_kavenegar/activate/')
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "امکان فعال" in str(res.data)

        # After successful test, activation succeeds
        record = StoreIntegrationConfig.objects.get(store=self.store_a, integration_id='sms_kavenegar')
        record.status = IntegrationState.READY
        record.last_test_success = True
        record.save()

        res_act = self.client_a.post('/api/v1/features/integrations/sms_kavenegar/activate/')
        assert res_act.status_code == status.HTTP_200_OK
        record.refresh_from_db()
        assert record.is_active is True
        assert record.status == IntegrationState.ACTIVE

    # 8. Changing secret invalidates previous successful test
    def test_changing_secret_invalidates_previous_test(self):
        # First activate
        record = StoreIntegrationConfig.objects.create(
            store=self.store_a,
            integration_id='sms_kavenegar',
            status=IntegrationState.ACTIVE,
            last_test_success=True,
            is_active=True,
            config_data={'api_key': encrypt_secret('INITIAL_KEY_1')}
        )

        # Manager updates the API key
        self.client_a.post(
            '/api/v1/features/integrations/sms_kavenegar/save/',
            {'config': {'api_key': 'NEW_REPLACED_KEY_2'}},
            format='json'
        )

        record.refresh_from_db()
        # Status MUST reset to CONFIGURED and activation revoked!
        assert record.status == IntegrationState.CONFIGURED
        assert record.last_test_success is False
        assert record.is_active is False

        # Attempt to activate without re-testing must fail
        res_act = self.client_a.post('/api/v1/features/integrations/sms_kavenegar/activate/')
        assert res_act.status_code == status.HTTP_400_BAD_REQUEST

    # 9. Token expiry handling (REAUTH_REQUIRED)
    def test_expired_token_handling(self):
        adapter = IntegrationRegistry.get_adapter('instagram')
        with mock.patch.object(adapter, '_execute_live_test') as mock_test:
            from apps.features.adapters import IntegrationHealthResult
            mock_test.return_value = IntegrationHealthResult(
                state=IntegrationState.REAUTH_REQUIRED,
                message="توکن اتصال اینستاگرام منقضی شده است."
            )
            res = self.client_a.post('/api/v1/features/integrations/instagram/test/')
            assert res.status_code == status.HTTP_400_BAD_REQUEST
            assert res.json()['status'] == IntegrationState.REAUTH_REQUIRED

            record = StoreIntegrationConfig.objects.get(store=self.store_a, integration_id='instagram')
            assert record.status == IntegrationState.REAUTH_REQUIRED

    # 10. Shipping graceful status in absence of live API
    def test_shipping_graceful_status_in_absence_of_api(self):
        res = self.client_a.post('/api/v1/features/integrations/shipping_irpost/test/')
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        # Should report manual/tariff mode clearly without generating fake parcel IDs
        assert "دستی" in data['message'] or "پست" in data['message']
        assert data['details'].get('manual_mode') is True or 'contract_number' in data['details']

    # 11. RBAC permissions check
    def test_rbac_permissions_for_integrations(self):
        # Staff (FULFILLMENT_STAFF) can view
        res_view = self.staff_client_a.get('/api/v1/features/integrations/')
        assert res_view.status_code == status.HTTP_200_OK

        # Staff cannot save config
        res_save = self.staff_client_a.post(
            '/api/v1/features/integrations/sms_kavenegar/save/',
            {'config': {'api_key': 'unauthorized_key'}},
            format='json'
        )
        assert res_save.status_code == status.HTTP_403_FORBIDDEN

        # Staff cannot run test
        res_test = self.staff_client_a.post('/api/v1/features/integrations/sms_kavenegar/test/')
        assert res_test.status_code == status.HTTP_403_FORBIDDEN

        # Staff cannot activate
        res_act = self.staff_client_a.post('/api/v1/features/integrations/sms_kavenegar/activate/')
        assert res_act.status_code == status.HTTP_403_FORBIDDEN

    # 12. Consumer operations use active store integration
    def test_consumer_operations_use_store_integration(self):
        # Save store-specific Zarinpal config
        adapter = IntegrationRegistry.get_adapter('payment_zarinpal')
        adapter.save_config(self.store_a, {
            'merchant_id': '11111111-2222-3333-4444-555555555555',
            'is_sandbox': True
        })

        from apps.payments.gateways import ZarinpalGatewayAdapter
        gateway = ZarinpalGatewayAdapter()
        assert gateway._get_merchant_id(self.store_a) == '11111111-2222-3333-4444-555555555555'
        assert gateway._is_sandbox(self.store_a) is True

        # Store B has no config -> defaults to None/env
        assert gateway._get_merchant_id(self.store_b) is None
