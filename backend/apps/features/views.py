from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.tenancy.permissions import IsStoreMemberPermission, IsStoreAdminOrOwnerPermission, get_request_store
from .models import StoreIntegrationConfig, IntegrationState
from .services import FeatureService
from .adapters import IntegrationRegistry
from .serializers import (
    FeatureItemSerializer,
    FeatureToggleInputSerializer,
    SubscriptionTierUpdateInputSerializer,
    IntegrationConfigInputSerializer,
    SubscriptionInvoiceSerializer,
    CreateInvoiceInputSerializer,
    CheckoutInvoiceInputSerializer,
)


class FeatureCatalogView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission]

    def get(self, request):
        store = get_request_store(request)
        catalog = FeatureService.get_store_feature_catalog(store)
        settings = FeatureService.get_or_create_settings(store)
        return Response({
            'tier': settings.tier,
            'tier_display': settings.get_tier_display(),
            'features': FeatureItemSerializer(catalog, many=True).data
        })


class FeatureToggleView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request):
        store = get_request_store(request)
        serializer = FeatureToggleInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = FeatureService.toggle_feature(
            store=store,
            feature_key=serializer.validated_data['feature'],
            enable=serializer.validated_data['enabled'],
            actor=request.user
        )
        return Response(result, status=status.HTTP_200_OK)


from django.conf import settings as django_settings
from django.utils import timezone
from decimal import Decimal
import uuid
from .models import SubscriptionTier, SubscriptionInvoice, InvoiceStatus, IntegrationState
from .serializers import (
    FeatureItemSerializer,
    FeatureToggleInputSerializer,
    SubscriptionTierUpdateInputSerializer,
    IntegrationConfigInputSerializer,
    SubscriptionInvoiceSerializer,
    CreateInvoiceInputSerializer
)

class SubscriptionTierView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request):
        store = get_request_store(request)
        serializer = SubscriptionTierUpdateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        settings = FeatureService.get_or_create_settings(store)
        old_tier = settings.tier
        new_tier = serializer.validated_data['tier']

        tier_hierarchy = {
            SubscriptionTier.FREE: 1,
            SubscriptionTier.STARTER: 2,
            SubscriptionTier.PRO: 3,
            SubscriptionTier.ENTERPRISE: 4
        }
        current_rank = tier_hierarchy.get(old_tier, 1)
        new_rank = tier_hierarchy.get(new_tier, 1)

        # In production, upgrading to a higher tier requires superuser, platform staff, or verified paid invoice
        payment_reference = serializer.validated_data.get('payment_reference')
        if new_rank > current_rank and not (request.user.is_superuser or request.user.is_staff or django_settings.DEBUG):
            invoice = None
            if payment_reference:
                invoice = SubscriptionInvoice.objects.filter(
                    store=store,
                    tier=new_tier,
                    status=InvoiceStatus.PAID,
                    payment_reference=payment_reference
                ).first()

            if not invoice:
                raise PermissionDenied("ارتقای پلن اشتراک مستلزم تسویه فاکتور اشتراک معتبر (SubscriptionInvoice) یا تأیید مدیر سامانه است.")

        settings.tier = new_tier
        settings.save()

        return Response({
            'message': f"سطح اشتراک فروشگاه از {old_tier} به {settings.tier} تغییر یافت.",
            'tier': settings.tier,
            'tier_display': settings.get_tier_display()
        })


class SubscriptionInvoiceListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def get(self, request):
        store = get_request_store(request)
        invoices = SubscriptionInvoice.objects.filter(store=store)
        serializer = SubscriptionInvoiceSerializer(invoices, many=True)
        return Response(serializer.data)

    def post(self, request):
        store = get_request_store(request)
        serializer = CreateInvoiceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tier = serializer.validated_data['tier']
        billing_cycle = serializer.validated_data.get('billing_cycle', 'MONTHLY')

        from .services import SubscriptionPaymentService
        invoice = SubscriptionPaymentService.create_subscription_invoice(
            store=store,
            tier=tier,
            billing_cycle=billing_cycle
        )
        return Response(SubscriptionInvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)


class SubscriptionInvoiceCheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def _validate_and_build_callback_url(self, request, client_callback: str, invoice) -> str:
        import urllib.parse
        from django.conf import settings as django_settings

        default_callback = request.build_absolute_uri('/api/v1/features/invoices/verify/')
        if not client_callback:
            return default_callback

        parsed = urllib.parse.urlparse(client_callback)

        if parsed.scheme and parsed.scheme not in ['http', 'https']:
            raise ValidationError({'callback_url': 'پروتکل آدرس بازگشت درگاه نامعتبر است.'})

        # Relative path is inherently safe (resolves on the current trusted server)
        if not parsed.netloc:
            return request.build_absolute_uri(client_callback)

        # Allowlist of trusted hostnames
        trusted_hosts = set()
        request_host = request.get_host().split(':')[0].lower()
        trusted_hosts.add(request_host)
        trusted_hosts.add('localhost')
        trusted_hosts.add('127.0.0.1')
        trusted_hosts.add('testserver')

        for h in getattr(django_settings, 'ALLOWED_HOSTS', []):
            if h and h != '*':
                trusted_hosts.add(h.split(':')[0].lower())

        frontend_url = getattr(django_settings, 'FRONTEND_URL', None)
        if frontend_url:
            f_host = urllib.parse.urlparse(frontend_url).netloc.split(':')[0].lower()
            if f_host:
                trusted_hosts.add(f_host)

        target_host = parsed.netloc.split(':')[0].lower()
        if target_host not in trusted_hosts:
            raise ValidationError({
                'callback_url': f"آدرس بازگشت درگاه مجاز نیست. دامنه '{target_host}' در فهرست دامنه‌های مجاز سیستم قرار ندارد."
            })

        return client_callback

    def post(self, request, pk):
        store = get_request_store(request)
        try:
            invoice = SubscriptionInvoice.objects.get(id=pk, store=store)
        except (SubscriptionInvoice.DoesNotExist, ValueError):
            return Response({'error': 'صورتحساب یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = CheckoutInvoiceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        client_callback = serializer.validated_data.get('callback_url', '').strip()
        safe_callback = self._validate_and_build_callback_url(request, client_callback, invoice)
        gateway_name = serializer.validated_data.get('gateway', 'zarinpal')

        from .services import SubscriptionPaymentService
        res = SubscriptionPaymentService.initiate_subscription_payment(
            invoice=invoice,
            store=store,
            callback_url=safe_callback,
            gateway_name=gateway_name
        )

        if not res.get('success'):
            status_code = status.HTTP_400_BAD_REQUEST if res.get('status') in ['REQUIRES_GATEWAY_CONFIG', 'INVALID_AMOUNT'] else status.HTTP_502_BAD_GATEWAY
            return Response(res, status=status_code)

        return Response({
            'success': True,
            'invoice_id': str(invoice.id),
            'authority': res.get('authority'),
            'payment_url': res.get('payment_url'),
            'amount': invoice.amount
        }, status=status.HTTP_200_OK)


class SubscriptionInvoiceVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return self._handle_verify(request)

    def post(self, request):
        return self._handle_verify(request)

    def _handle_verify(self, request):
        authority = (
            request.data.get('authority')
            or request.data.get('Authority')
            or request.query_params.get('Authority')
            or request.query_params.get('authority')
        )
        gateway_name = request.data.get('gateway', 'zarinpal')

        if not authority:
            return Response({'error': 'شناسه Authority درگاه ارسال نشده است.'}, status=status.HTTP_400_BAD_REQUEST)

        from .services import SubscriptionPaymentService
        success, invoice, message = SubscriptionPaymentService.verify_subscription_payment(
            authority=authority,
            gateway_name=gateway_name
        )

        if success:
            return Response({
                'success': True,
                'message': message,
                'tracking_code': invoice.gateway_tracking_code,
                'invoice': SubscriptionInvoiceSerializer(invoice).data
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'success': False,
                'error': message,
                'invoice': SubscriptionInvoiceSerializer(invoice).data if invoice else None
            }, status=status.HTTP_400_BAD_REQUEST)


class SubscriptionInvoiceManualApproveView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied("تنها مدیران ارشد سامانه مجاز به تأیید دستی صورتحساب اشتراک هستند.")

        serializer = ManualApproveInvoiceInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from .services import SubscriptionPaymentService
        try:
            invoice = SubscriptionPaymentService.admin_manual_override_invoice(
                invoice_id=pk,
                actor=request.user,
                reason=serializer.validated_data['reason'],
                tracking_code=serializer.validated_data.get('tracking_code', '')
            )
        except SubscriptionInvoice.DoesNotExist:
            return Response({'error': 'صورتحساب یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'message': f"صورتحساب با موفقیت توسط مدیر سامانه تأیید شد و پلن فروشگاه ارتقا یافت.",
            'invoice': SubscriptionInvoiceSerializer(invoice).data
        }, status=status.HTTP_200_OK)


class SubscriptionInvoicePayView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request, pk):
        store = get_request_store(request)
        try:
            invoice = SubscriptionInvoice.objects.get(id=pk, store=store)
        except (SubscriptionInvoice.DoesNotExist, ValueError):
            return Response({'error': 'صورتحساب یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

        if invoice.status == InvoiceStatus.PAID:
            return Response({'message': 'این صورتحساب قبلاً پرداخت شده است.'}, status=status.HTTP_200_OK)

        # Free tier invoices can be activated directly
        if invoice.amount == Decimal('0') or invoice.tier == SubscriptionTier.FREE:
            from .services import SubscriptionPaymentService
            invoice.status = InvoiceStatus.PAID
            invoice.paid_at = timezone.now()
            invoice.save()
            SubscriptionPaymentService.apply_paid_subscription_invoice(invoice)
            return Response({
                'message': 'پلن رایگان با موفقیت فعال شد.',
                'invoice': SubscriptionInvoiceSerializer(invoice).data
            })

        # Disallow arbitrary client string approvals for paid tiers!
        if request.user.is_staff or request.user.is_superuser:
            reason = request.data.get('reason')
            if not reason:
                return Response(
                    {'error': 'برای تأیید دستی صورتحساب‌های مالی توسط مدیر، ذکر پارامتر reason الزامی است.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            from .services import SubscriptionPaymentService
            invoice = SubscriptionPaymentService.admin_manual_override_invoice(
                invoice_id=pk,
                actor=request.user,
                reason=reason,
                tracking_code=request.data.get('tracking_code', '')
            )
            return Response({
                'message': f"صورتحساب توسط مدیر سامانه با موفقیت تأیید شد.",
                'invoice': SubscriptionInvoiceSerializer(invoice).data
            })

        return Response(
            {
                'error': 'امکان ثبت پرداخت ساختگی بدون استعلام درگاه بانکی وجود ندارد. لطفاً از طریق درگاه پرداخت آنلاین (/checkout/) پرداخت را انجام دهید.'
            },
            status=status.HTTP_400_BAD_REQUEST
        )



class IntegrationListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission]

    def get(self, request):
        store = get_request_store(request)
        is_canonical = request.query_params.get('canonical', '').lower() in ('true', '1')

        if is_canonical:
            adapters = IntegrationRegistry.get_canonical_adapters()
            results = []
            for adapter in adapters:
                record = adapter.get_store_config_record(store)
                status_val = adapter.get_status(store)
                health = adapter.health_check(store)
                results.append({
                    'id': adapter.name,
                    'name': adapter.name,
                    'category': adapter.category,
                    'display_name_fa': adapter.display_name_fa,
                    'description_fa': adapter.description_fa,
                    'guide_fa': adapter.guide_fa,
                    'status': status_val,
                    'is_active': record.is_active if record else (status_val in (IntegrationState.ACTIVE, IntegrationState.CONNECTED)),
                    'is_ready': adapter.is_ready(store),
                    'message': health.message,
                    'last_tested_at': record.last_tested_at.isoformat() if (record and record.last_tested_at) else None,
                    'last_connected_at': record.last_connected_at.isoformat() if (record and record.last_connected_at) else None,
                    'last_test_error': record.last_test_error if record else "",
                    'last_test_success': record.last_test_success if record else None,
                    'schema': adapter.get_schema(),
                    'config': adapter.get_config(store, decrypted=False)
                })
            return Response(results)

        # Standard dictionary format for backward compatibility
        integrations = IntegrationRegistry.get_store_integration_statuses(store)
        return Response(integrations)


class IntegrationDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission]

    def get(self, request, name):
        store = get_request_store(request)
        adapter = IntegrationRegistry.get_adapter(name)
        if not adapter:
            return Response({'error': f"اتصال '{name}' یافت نشد."}, status=status.HTTP_404_NOT_FOUND)

        record = adapter.get_store_config_record(store)
        status_val = adapter.get_status(store)
        health = adapter.health_check(store)

        return Response({
            'id': adapter.name,
            'name': adapter.name,
            'category': adapter.category,
            'display_name_fa': adapter.display_name_fa,
            'description_fa': adapter.description_fa,
            'guide_fa': adapter.guide_fa,
            'status': status_val,
            'is_active': record.is_active if record else (status_val in (IntegrationState.ACTIVE, IntegrationState.CONNECTED)),
            'is_ready': adapter.is_ready(store),
            'message': health.message,
            'last_tested_at': record.last_tested_at.isoformat() if (record and record.last_tested_at) else None,
            'last_connected_at': record.last_connected_at.isoformat() if (record and record.last_connected_at) else None,
            'last_test_error': record.last_test_error if record else "",
            'last_test_success': record.last_test_success if record else None,
            'schema': adapter.get_schema(),
            'config': adapter.get_config(store, decrypted=False)
        })


class IntegrationSaveConfigView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request, name):
        store = get_request_store(request)
        adapter = IntegrationRegistry.get_adapter(name)
        if not adapter:
            return Response({'error': f"اتصال '{name}' یافت نشد."}, status=status.HTTP_404_NOT_FOUND)

        raw_config = request.data.get('config')
        if raw_config is None:
            raw_config = request.data

        if not isinstance(raw_config, dict):
            return Response({'error': 'فرمت پارامتر تنظیمات نامعتبر است.'}, status=status.HTTP_400_BAD_REQUEST)

        record = adapter.save_config(store, raw_config)
        return Response({
            'success': True,
            'message': f"تنظیمات اتصال '{adapter.display_name_fa}' با موفقیت ذخیره شد.",
            'status': record.status,
            'is_active': record.is_active,
            'config': adapter.get_config(store, decrypted=False)
        })


class IntegrationTestView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request, name):
        store = get_request_store(request)
        adapter = IntegrationRegistry.get_adapter(name)
        if not adapter:
            return Response({'error': f"اتصال '{name}' یافت نشد."}, status=status.HTTP_404_NOT_FOUND)

        health_result = adapter.test_connection(store)
        is_healthy = health_result.to_dict()['is_healthy']
        status_code = status.HTTP_200_OK if is_healthy else status.HTTP_400_BAD_REQUEST

        return Response({
            'success': is_healthy,
            'status': health_result.state,
            'message': health_result.message,
            'details': health_result.details
        }, status=status_code)


class IntegrationActivateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request, name):
        store = get_request_store(request)
        adapter = IntegrationRegistry.get_adapter(name)
        if not adapter:
            return Response({'error': f"اتصال '{name}' یافت نشد."}, status=status.HTTP_404_NOT_FOUND)

        success, msg = adapter.activate(store)
        return Response({
            'success': success,
            'message': msg,
            'status': adapter.get_status(store),
            'is_active': True
        })


class IntegrationDeactivateView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request, name):
        store = get_request_store(request)
        adapter = IntegrationRegistry.get_adapter(name)
        if not adapter:
            return Response({'error': f"اتصال '{name}' یافت نشد."}, status=status.HTTP_404_NOT_FOUND)

        success, msg = adapter.deactivate(store)
        return Response({
            'success': success,
            'message': msg,
            'status': adapter.get_status(store),
            'is_active': False
        })


class IntegrationTestSMSView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request, name):
        store = get_request_store(request)
        adapter = IntegrationRegistry.get_adapter(name)
        if not adapter or not hasattr(adapter, 'send_test_sms'):
            return Response({'error': f"سرویس '{name}' از قابلیت ارسال پیامک تستی پشتیبانی نمی‌کند."}, status=status.HTTP_400_BAD_REQUEST)

        to_phone = request.data.get('to', '').strip()
        if not to_phone:
            return Response({'error': 'شماره تلفن مقصد جهت ارسال پیامک تستی الزامی است.'}, status=status.HTTP_400_BAD_REQUEST)

        res = adapter.send_test_sms(to=to_phone, store=store)
        if res.get('status') == 'ACCEPTED':
            return Response({
                'success': True,
                'message': f"پیامک آزمایشی با موفقیت به شماره {to_phone} ارسال شد.",
                'details': res
            })
        return Response({
            'success': False,
            'error': res.get('error') or res.get('message') or 'ارسال پیامک آزمایشی ناموفق بود.',
            'details': res
        }, status=status.HTTP_400_BAD_REQUEST)


class IntegrationTestEmailView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request, name):
        store = get_request_store(request)
        adapter = IntegrationRegistry.get_adapter(name)
        if not adapter or not hasattr(adapter, 'send_email'):
            return Response({'error': f"سرویس '{name}' از قابلیت ارسال ایمیل تستی پشتیبانی نمی‌کند."}, status=status.HTTP_400_BAD_REQUEST)

        to_email = request.data.get('to', '').strip()
        if not to_email or '@' not in to_email:
            return Response({'error': 'آدرس ایمیل معتبر مقصد الزامی است.'}, status=status.HTTP_400_BAD_REQUEST)

        subject = f"ایمیل آزمایشی شاپ‌پایلوت - فروشگاه {store.name}"
        body = f"""
        <div dir="rtl" style="font-family: Tahoma, sans-serif; padding: 20px; border: 1px solid #e2e8f0; border-radius: 12px;">
            <h2 style="color: #2563eb;">اتصال ایمیل با موفقیت تأیید شد</h2>
            <p>این یک ایمیل آزمایشی جهت اطمینان از صحت پیکربندی سرور SMTP در فروشگاه <strong>{store.name}</strong> است.</p>
            <p style="color: #64748b; font-size: 12px;">زمان ارسال: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        """
        ok = adapter.send_email(to=to_email, subject=subject, html_body=body, store=store)
        if ok:
            return Response({
                'success': True,
                'message': f"ایمیل آزمایشی با موفقیت به {to_email} ارسال شد."
            })
        return Response({
            'success': False,
            'error': 'ارسال ایمیل آزمایشی ناموفق بود. لطفاً تنظیمات سرور و احراز هویت را بررسی فرمایید.'
        }, status=status.HTTP_400_BAD_REQUEST)


class IntegrationConfigView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreAdminOrOwnerPermission]

    def post(self, request):
        store = get_request_store(request)
        serializer = IntegrationConfigInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        name = serializer.validated_data['name']
        new_state = serializer.validated_data['state']

        # Prevent users from manually setting status to CONNECTED without a successful live health check
        if new_state == IntegrationState.CONNECTED:
            adapter = IntegrationRegistry.get_adapter(name)
            if not adapter:
                return Response(
                    {'error': f"سرویس '{name}' در سامانه یافت نشد."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            health = adapter.health_check(store)
            if health.state != IntegrationState.CONNECTED:
                return Response(
                    {
                        'error': "امکان تغییر وضعیت به CONNECTED وجود ندارد؛ تست سلامت سرویس موفق نبود.",
                        'health_status': health.state,
                        'message': health.message
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

        settings = FeatureService.get_or_create_settings(store)
        states = dict(settings.integration_states or {})
        states[name] = new_state
        settings.integration_states = states
        settings.save()

        # Also update StoreIntegrationConfig if present
        config_record = StoreIntegrationConfig.objects.filter(store=store, integration_id=name).first()
        if config_record:
            config_record.status = new_state
            if new_state in (IntegrationState.DISABLED, IntegrationState.DISABLED_BY_STORE):
                config_record.is_active = False
            elif new_state in (IntegrationState.ACTIVE, IntegrationState.CONNECTED):
                config_record.is_active = True
            config_record.save()

        return Response({
            'name': name,
            'state': new_state,
            'message': f"وضعیت اتصال سرویس '{name}' بروزرسانی شد."
        })

