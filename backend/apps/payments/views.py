from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from apps.tenancy.permissions import IsStoreMemberPermission, TenantFilterBackend, Role, user_has_store_permission
from apps.orders.models import Order
from .models import PaymentTransaction, PaymentVerificationStatus
from .serializers import (
    PaymentTransactionSerializer, CreatePaymentInputSerializer, RejectPaymentInputSerializer
)
from .services import verify_payment_transaction, reject_payment_transaction

import uuid
from decimal import Decimal
from django.db import transaction
from .gateways import get_payment_gateway

class PaymentTransactionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStoreMemberPermission]
    filter_backends = [TenantFilterBackend, DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'method', 'order']
    search_fields = ['reference_number', 'tracking_code', 'order__order_number', 'payer_card_mask']
    ordering_fields = ['created_at', 'amount']
    queryset = PaymentTransaction.objects.all().select_related('order', 'order__customer', 'verified_by')

    def get_serializer_class(self):
        if self.action == 'create':
            return CreatePaymentInputSerializer
        return PaymentTransactionSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = CreatePaymentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store = request.store
        data = serializer.validated_data

        try:
            order = Order.objects.select_for_update().get(id=data['order_id'], store=store)
        except Order.DoesNotExist:
            return Response({'error': 'سفارش یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

        # Authoritative server-side remaining payable validation
        verified_sum = sum(
            p.amount for p in order.payments.filter(status=PaymentVerificationStatus.VERIFIED)
        )
        remaining_payable = max(Decimal('0'), order.grand_total - verified_sum)
        if data['amount'] > remaining_payable:
            return Response(
                {'error': f'مبلغ پرداختی ({data["amount"]}) بیشتر از مبلغ باقیمانده سفارش ({remaining_payable}) است.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        payment = PaymentTransaction.objects.create(
            store=store,
            order=order,
            method=data['method'],
            amount=data['amount'],
            currency=order.currency,
            reference_number=data.get('reference_number', ''),
            tracking_code=data.get('tracking_code', ''),
            payer_card_mask=data.get('payer_card_mask', ''),
            receipt_image_url=data.get('receipt_image_url', ''),
            status=PaymentVerificationStatus.PENDING_VERIFICATION
        )
        return Response(PaymentTransactionSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def verify(self, request, pk=None):
        membership = getattr(request, 'membership', None)
        if not (request.user.is_superuser or (membership and (membership.role in [Role.OWNER, Role.ADMIN, Role.BUSINESS_MANAGER] or user_has_store_permission(membership, 'payments.verify')))):
            return Response({'detail': 'شما مجوز تأیید فیش‌های واریزی و تراکنش‌های مالی را ندارید.'}, status=status.HTTP_403_FORBIDDEN)

        payment = self.get_object()
        if payment.status == PaymentVerificationStatus.VERIFIED:
            return Response({'message': 'تراکنش از قبل تأیید شده است.'}, status=status.HTTP_200_OK)

        verified = verify_payment_transaction(payment=payment, user=request.user)
        return Response(PaymentTransactionSerializer(verified).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        membership = getattr(request, 'membership', None)
        if not (request.user.is_superuser or (membership and (membership.role in [Role.OWNER, Role.ADMIN, Role.BUSINESS_MANAGER] or user_has_store_permission(membership, 'payments.verify')))):
            return Response({'detail': 'شما مجوز رد فیش‌های واریزی و تراکنش‌های مالی را ندارید.'}, status=status.HTTP_403_FORBIDDEN)

        payment = self.get_object()
        serializer = RejectPaymentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        rejected = reject_payment_transaction(
            payment=payment,
            reason=serializer.validated_data['reason'],
            user=request.user
        )
        return Response(PaymentTransactionSerializer(rejected).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        membership = getattr(request, 'membership', None)
        if not (request.user.is_superuser or (membership and (membership.role in [Role.OWNER, Role.ADMIN, Role.BUSINESS_MANAGER] or user_has_store_permission(membership, 'payments.verify')))):
            return Response({'detail': 'شما مجوز استرداد تراکنش‌های مالی را ندارید.'}, status=status.HTTP_403_FORBIDDEN)

        payment = self.get_object()
        amount = request.data.get('amount')
        reason = request.data.get('reason', '')
        is_manual = bool(request.data.get('is_manual', False))

        from .services import process_payment_refund
        try:
            refunded = process_payment_refund(
                payment=payment,
                amount=amount,
                reason=reason,
                user=request.user,
                is_manual=is_manual
            )
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PaymentTransactionSerializer(refunded).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='online-checkout')
    def online_checkout(self, request):
        """Initiates online payment gateway checkout (e.g. Zarinpal) atomically without race conditions or orphaned authorities."""
        order_id = request.data.get('order_id')
        callback_url = request.data.get('callback_url', '')
        gateway_name = request.data.get('gateway', 'zarinpal')
        store = request.store

        # 1. Short atomic lock to validate order, deduct pending_sum from remaining payable, and pre-create transaction
        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(id=order_id, store=store)
            except (Order.DoesNotExist, ValueError):
                return Response({'error': 'سفارش یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

            verified_sum = sum(
                p.amount for p in order.payments.filter(status=PaymentVerificationStatus.VERIFIED)
            )
            pending_sum = sum(
                p.amount for p in order.payments.filter(status=PaymentVerificationStatus.PENDING_VERIFICATION)
            )

            if verified_sum >= order.grand_total:
                return Response({'error': 'این سفارش قبلاً به طور کامل تسویه شده است.'}, status=status.HTTP_400_BAD_REQUEST)

            remaining_payable = max(Decimal('0'), order.grand_total - verified_sum - pending_sum)
            if remaining_payable <= 0:
                return Response(
                    {'error': 'یک یا چند تراکنش در حال انجام برای باقیمانده مبلغ این سفارش وجود دارد. لطفاً پس از تکمیل یا انقضای آن دوباره تلاش کنید.'},
                    status=status.HTTP_409_CONFLICT
                )

            req_amount = request.data.get('amount')
            if req_amount is not None:
                try:
                    chosen_amount = Decimal(str(req_amount))
                except Exception:
                    return Response({'error': 'فرمت مبلغ درخواستی نامعتبر است.'}, status=status.HTTP_400_BAD_REQUEST)
                if chosen_amount <= 0 or chosen_amount > remaining_payable:
                    return Response({'error': f'مبلغ درخواستی باید بین ۱ و {remaining_payable} باشد.'}, status=status.HTTP_400_BAD_REQUEST)
                payable_amount = chosen_amount
            else:
                payable_amount = remaining_payable

            order_number = order.order_number
            order_currency = order.currency
            order_pk = str(order.id)

            from .models import PaymentMethod
            init_ref = f"REQ_{uuid.uuid4().hex[:16]}"
            payment = PaymentTransaction.objects.create(
                store=store,
                order=order,
                method=PaymentMethod.ONLINE_GATEWAY,
                amount=payable_amount,
                currency=order_currency,
                reference_number=init_ref,
                status=PaymentVerificationStatus.PENDING_VERIFICATION
            )

        # 2. Callback URL allowlisting & safe resolution
        safe_callback = self._resolve_safe_callback_url(request, callback_url)

        gateway = get_payment_gateway(gateway_name)
        if not gateway:
            with transaction.atomic():
                p = PaymentTransaction.objects.select_for_update().get(id=payment.id)
                p.status = PaymentVerificationStatus.REJECTED
                p.rejection_reason = f'درگاه پرداخت {gateway_name} پشتیبانی نمی‌شود.'
                p.save(update_fields=['status', 'rejection_reason', 'updated_at'])
            return Response({'error': f'درگاه پرداخت {gateway_name} پشتیبانی نمی‌شود.'}, status=status.HTTP_400_BAD_REQUEST)

        # 3. Gateway network call OUTSIDE of database transaction
        desc = f"پرداخت سفارش {order_number} در فروشگاه {store.name}"
        result = gateway.request_payment(
            amount=payable_amount,
            callback_url=safe_callback,
            description=desc,
            order_id=order_pk,
            store=store,
            currency=order_currency
        )

        if not result.get('success'):
            with transaction.atomic():
                p = PaymentTransaction.objects.select_for_update().get(id=payment.id)
                p.status = PaymentVerificationStatus.REJECTED
                p.rejection_reason = result.get('message', 'خطای درگاه در ایجاد تراکنش')
                p.save(update_fields=['status', 'rejection_reason', 'updated_at'])

            status_code = status.HTTP_400_BAD_REQUEST if result.get('status') in ['REQUIRES_GATEWAY_CONFIG', 'INVALID_AMOUNT'] else status.HTTP_502_BAD_GATEWAY
            return Response(result, status=status_code)

        # 4. Attach gateway authority to the pre-created transaction
        with transaction.atomic():
            p = PaymentTransaction.objects.select_for_update().get(id=payment.id)
            p.reference_number = result.get('authority')
            p.save(update_fields=['reference_number', 'updated_at'])

        return Response({
            'payment_id': str(payment.id),
            'authority': result.get('authority'),
            'payment_url': result.get('payment_url'),
            'amount': payable_amount
        }, status=status.HTTP_200_OK)

    def _resolve_safe_callback_url(self, request, callback_url: str) -> str:
        fallback = request.build_absolute_uri('/api/v1/payments/online-verify/')
        if not callback_url:
            return fallback

        from urllib.parse import urlsplit
        from django.conf import settings

        try:
            parsed = urlsplit(callback_url.strip())
        except Exception:
            return fallback

        # 1. Strict scheme check: only https (or http in dev/debug)
        allowed_schemes = ['https', 'http'] if getattr(settings, 'DEBUG', False) else ['https']
        if not parsed.scheme or parsed.scheme.lower() not in allowed_schemes:
            return fallback

        # 2. Block userinfo (username / password in URL e.g. user:pass@host)
        if parsed.username or parsed.password:
            return fallback

        # 3. Check hostname
        hostname = parsed.hostname
        if not hostname:
            return fallback
        hostname = hostname.lower()

        # 4. Check port: must be standard or match current host port
        current_split = urlsplit(request.build_absolute_uri())
        current_port = current_split.port
        if parsed.port is not None:
            if parsed.scheme == 'https' and parsed.port not in [443, current_port]:
                return fallback
            if parsed.scheme == 'http' and parsed.port not in [80, 8000, 3000, current_port]:
                return fallback

        # 5. Allowed hostnames matching
        allowed_hostnames = set()
        if current_split.hostname:
            allowed_hostnames.add(current_split.hostname.lower())

        for h in getattr(settings, 'ALLOWED_HOSTS', []):
            if h and h != '*':
                allowed_hostnames.add(h.lower().lstrip('.'))

        for origin in list(getattr(settings, 'CORS_ALLOWED_ORIGINS', [])) + list(getattr(settings, 'CSRF_TRUSTED_ORIGINS', [])):
            try:
                sp = urlsplit(origin)
                if sp.hostname:
                    allowed_hostnames.add(sp.hostname.lower())
            except Exception:
                pass

        store = getattr(request, 'store', None)
        if store and hasattr(store, 'custom_domain') and store.custom_domain:
            allowed_hostnames.add(store.custom_domain.lower())

        if hostname not in allowed_hostnames:
            return fallback

        return callback_url.strip()

    @action(detail=False, methods=['get', 'post'], url_path='online-verify',
            permission_classes=[AllowAny])
    def online_verify(self, request):
        """Verifies online payment callback with the payment gateway idempotently.

        Permission: AllowAny — anonymous gateway callbacks from payment providers must reach
        this endpoint without a Bearer token. Authenticated users also have access.
        Security is enforced by server-to-server gateway verification, NOT by user identity.
        """
        authority = (
            request.data.get('authority')
            or request.data.get('Authority')
            or request.query_params.get('Authority')
            or request.query_params.get('authority')
        )
        status_param = (
            request.data.get('Status')
            or request.query_params.get('Status')
            or request.data.get('status')
            or request.query_params.get('status')
        )
        # NOTE: caller-supplied 'gateway' param is intentionally ignored — see security note below.

        if not authority:
            return Response({'error': 'پارامتر authority یا شناسه ارجاع الزامی است.'}, status=status.HTTP_400_BAD_REQUEST)

        # Lookup payment strictly by authority / reference_number AND method=ONLINE_GATEWAY
        from .models import PaymentMethod
        payment = PaymentTransaction.objects.filter(
            reference_number=authority,
            method=PaymentMethod.ONLINE_GATEWAY
        ).select_related('store', 'order').first()

        if not payment:
            return Response({'error': 'تراکنش آنلاین معتبری برای این شناسه ارجاع یافت نشد.'}, status=status.HTTP_404_NOT_FOUND)

        store = payment.store
        req_store = getattr(request, 'store', None)
        if req_store and req_store.id != store.id and not (request.user and request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff)):
            return Response({'error': 'عدم تطابق فروشگاه تراکنش با درخواست.'}, status=status.HTTP_403_FORBIDDEN)

        if payment.status == PaymentVerificationStatus.VERIFIED:
            return Response({
                'success': True,
                'message': 'تراکنش از قبل تأیید شده است.',
                'tracking_code': payment.tracking_code,
                'payment': PaymentTransactionSerializer(payment).data
            }, status=status.HTTP_200_OK)

        # Terminal state protection: reject re-verifying REFUNDED or REJECTED transactions
        if payment.status == PaymentVerificationStatus.REFUNDED:
            return Response({
                'success': False,
                'error': 'این تراکنش قبلاً استرداد شده است و امکان تایید مجدد آن وجود ندارد.',
                'status': 'ALREADY_REFUNDED'
            }, status=status.HTTP_400_BAD_REQUEST)

        if payment.status == PaymentVerificationStatus.REJECTED:
            return Response({
                'success': False,
                'error': f'این تراکنش قبلاً رد شده است: {payment.rejection_reason}',
                'status': 'ALREADY_REJECTED'
            }, status=status.HTTP_400_BAD_REQUEST)

        if payment.status != PaymentVerificationStatus.PENDING_VERIFICATION:
            return Response({
                'success': False,
                'error': f'وضعیت فعلی تراکنش ({payment.status}) جهت تایید معتبر نیست.',
                'status': 'INVALID_STATUS'
            }, status=status.HTTP_400_BAD_REQUEST)

        # SECURITY: Never use a caller-supplied gateway name. A malicious caller could name
        # a different provider to route verification through an unrelated or non-existent provider.
        # The gateway is always 'zarinpal' for online ONLINE_GATEWAY transactions.
        gateway = get_payment_gateway('zarinpal')
        if not gateway:
            return Response({'error': 'درگاه پرداخت آنلاین پیکربندی نشده است.'}, status=status.HTTP_400_BAD_REQUEST)

        # SECURITY: Do NOT trust user-controlled NOK/CANCELLED status parameter alone.
        # A forged cancellation cannot alter the final state without gateway-confirmed rejection.
        # Always call gateway server-to-server verify first — it is the sole authoritative source.
        user_claimed_cancelled = status_param and str(status_param).upper() in ['NOK', 'CANCELLED', 'CANCELED']

        # Call gateway verify OUTSIDE DB lock (network I/O must not hold a DB lock)
        res = gateway.verify_payment(
            authority=authority,
            amount=payment.amount,
            store=store,
            currency=payment.currency
        )

        if res.success:
            with transaction.atomic():
                p = PaymentTransaction.objects.select_for_update().get(id=payment.id)
                if p.status == PaymentVerificationStatus.PENDING_VERIFICATION:
                    p.tracking_code = res.tracking_code
                    p.save(update_fields=['tracking_code'])
                    verified = verify_payment_transaction(payment=p, user=request.user if request.user.is_authenticated else None)
                else:
                    verified = p

            return Response({
                'success': True,
                'message': res.message,
                'tracking_code': res.tracking_code,
                'payment': PaymentTransactionSerializer(verified).data
            }, status=status.HTTP_200_OK)

        elif res.status == 'COMMUNICATION_ERROR':
            # Network failure/timeout: do NOT permanently reject. Leave as PENDING_VERIFICATION so
            # reconciliation can retry. Never falsely report success or failure on uncertain outcomes.
            return Response({
                **res.to_dict(),
                'message': 'خطا در ارتباط با درگاه پرداخت. وضعیت تراکنش برای تطبیق‌پذیری حفظ شد.',
                'retry': True,
            }, status=status.HTTP_502_BAD_GATEWAY)

        else:
            # Gateway definitively rejected. Only now mark REJECTED — never based on user-supplied params alone.
            with transaction.atomic():
                p = PaymentTransaction.objects.select_for_update().get(id=payment.id)
                if p.status == PaymentVerificationStatus.PENDING_VERIFICATION:
                    if user_claimed_cancelled:
                        p.rejection_reason = "تراکنش توسط کاربر لغو شد و درگاه آن را تأیید نکرد."
                    else:
                        p.rejection_reason = res.message
                    p.status = PaymentVerificationStatus.REJECTED
                    p.save(update_fields=['status', 'rejection_reason', 'updated_at'])
            return Response({
                'success': False,
                'status': 'CANCELLED_BY_USER' if user_claimed_cancelled else res.status,
                'message': p.rejection_reason,
                'payment': PaymentTransactionSerializer(p).data
            }, status=status.HTTP_400_BAD_REQUEST)



