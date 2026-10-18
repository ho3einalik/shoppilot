from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.tenancy.models import Role
from apps.tenancy.permissions import (
    IsStoreMemberPermission,
    TenantFilterBackend,
    get_request_store,
    user_has_store_permission
)
from apps.features.permissions import RequiresFeature
from .models import (
    SocialAccount,
    SocialCampaign,
    SocialContent,
    ContentStatus,
    ContentMetricSnapshot
)
from .serializers import (
    SocialAccountSerializer,
    SocialCampaignSerializer,
    SocialContentListSerializer,
    SocialContentDetailSerializer,
    SocialContentCreateUpdateSerializer,
    ContentReviewInputSerializer,
    ContentScheduleInputSerializer,
    ContentPublishInputSerializer,
    RecordMetricsInputSerializer,
    ContentMetricSnapshotSerializer
)
from .services import SocialService


class SocialAccountViewSet(viewsets.ModelViewSet):
    serializer_class = SocialAccountSerializer
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission]
    filter_backends = [TenantFilterBackend]
    queryset = SocialAccount.objects.all()

    def perform_create(self, serializer):
        membership = getattr(self.request, 'membership', None)
        if not user_has_store_permission(membership, 'integrations.manage'):
            raise PermissionDenied("دسترسی مدیریت حساب‌های شبکه‌های اجتماعی را ندارید.")
        store = get_request_store(self.request)
        serializer.save(store=store)


class SocialCampaignViewSet(viewsets.ModelViewSet):
    serializer_class = SocialCampaignSerializer
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission]
    filter_backends = [TenantFilterBackend]
    queryset = SocialCampaign.objects.all()

    def perform_create(self, serializer):
        store = get_request_store(self.request)
        serializer.save(store=store)


class SocialContentViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission, RequiresFeature('social.content_calendar')]
    filter_backends = [TenantFilterBackend]
    queryset = SocialContent.objects.select_related(
        'store', 'account', 'campaign', 'creator', 'assignee', 'related_product'
    ).prefetch_related('approval_logs', 'metric_snapshots').all()

    def get_serializer_class(self):
        if self.action == 'list':
            return SocialContentListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return SocialContentCreateUpdateSerializer
        return SocialContentDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        membership = getattr(self.request, 'membership', None)
        if not user_has_store_permission(membership, 'content.view'):
            return qs.none()

        # Filters
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        content_type = self.request.query_params.get('content_type')
        if content_type:
            qs = qs.filter(content_type=content_type)

        account_id = self.request.query_params.get('account')
        if account_id:
            qs = qs.filter(account_id=account_id)

        campaign_id = self.request.query_params.get('campaign')
        if campaign_id:
            qs = qs.filter(campaign_id=campaign_id)

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date and end_date:
            qs = qs.filter(scheduled_at__date__gte=start_date, scheduled_at__date__lte=end_date)
        elif start_date:
            qs = qs.filter(scheduled_at__date__gte=start_date)

        return qs

    def perform_create(self, serializer):
        membership = getattr(self.request, 'membership', None)
        if not user_has_store_permission(membership, 'content.create'):
            raise PermissionDenied("دسترسی ایجاد محتوا را ندارید.")

        store = get_request_store(self.request)
        serializer.save(store=store, creator=self.request.user)

    @action(detail=True, methods=['post'], url_path='submit-review')
    def submit_review(self, request, pk=None):
        content = self.get_object()
        membership = getattr(request, 'membership', None)
        if not (user_has_store_permission(membership, 'content.submit') or content.creator_id == request.user.id):
            raise PermissionDenied("دسترسی ارسال برای بازبینی را ندارید.")

        updated = SocialService.submit_for_review(content, request.user)
        return Response(SocialContentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'], url_path='review')
    def review(self, request, pk=None):
        content = self.get_object()
        membership = getattr(request, 'membership', None)
        
        input_serializer = ContentReviewInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        action_val = input_serializer.validated_data['action']
        feedback = input_serializer.validated_data.get('feedback', '')

        if action_val == 'APPROVED' and not user_has_store_permission(membership, 'content.approve'):
            raise PermissionDenied("دسترسی تأیید محتوا را ندارید.")
        elif action_val in ['REJECTED', 'CHANGES_REQUESTED'] and not user_has_store_permission(membership, 'content.reject'):
            raise PermissionDenied("دسترسی رد یا درخواست اصلاح محتوا را ندارید.")

        is_owner_or_admin = request.user.is_superuser or (membership and membership.role in [Role.OWNER, Role.ADMIN])
        if action_val == 'APPROVED' and content.creator_id == request.user.id and not is_owner_or_admin:
            raise PermissionDenied("تولیدکننده محتوا مجاز به تأیید محتوای خود نیست و بررسی مستقل توسط مدیر الزامی است.")

        updated = SocialService.review_content(
            content=content,
            reviewer=request.user,
            action=action_val,
            feedback=feedback
        )
        return Response(SocialContentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'], url_path='schedule')
    def schedule(self, request, pk=None):
        content = self.get_object()
        membership = getattr(request, 'membership', None)
        if not user_has_store_permission(membership, 'content.edit'):
            raise PermissionDenied("دسترسی زمان‌بندی محتوا را ندارید.")

        input_serializer = ContentScheduleInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        updated = SocialService.schedule_content(
            content=content,
            scheduled_at=input_serializer.validated_data['scheduled_at'],
            user=request.user
        )
        return Response(SocialContentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'], url_path='publish')
    def publish(self, request, pk=None):
        content = self.get_object()
        membership = getattr(request, 'membership', None)
        if not user_has_store_permission(membership, 'content.publish'):
            raise PermissionDenied("دسترسی انتشار محتوا را ندارید.")

        is_owner_or_admin = request.user.is_superuser or (membership and membership.role in [Role.OWNER, Role.ADMIN])
        if content.creator_id == request.user.id and not is_owner_or_admin:
            raise PermissionDenied("تولیدکننده محتوا مجاز به تأیید و انتشار محتوای خود بدون بررسی مستقل توسط مدیر نیست.")

        from .models import PublishingMode
        if content.publishing_mode == PublishingMode.MANUAL_REMINDER:
            published_url = request.data.get('published_url', '').strip()
            proof_image_url = request.data.get('proof_image_url', '').strip()
            if not published_url and not proof_image_url and not content.proof_url and not content.proof_image_url:
                raise ValidationError("ثبت مدرک انتشار (آدرس پست یا تصویر) الزامی است.")

            # Record proof and verify it by the manager
            SocialService.submit_proof(
                content=content,
                proof_url=published_url or content.proof_url,
                proof_image_url=proof_image_url or content.proof_image_url,
                user=request.user
            )
            updated = SocialService.verify_proof(
                content=content,
                manager_user=request.user,
                approved=True,
                notes="تأیید و انتشار با مدرک توسط مدیر"
            )
            return Response(SocialContentDetailSerializer(updated).data)

        # In DIRECT_API mode, publish is performed via server-side dispatch
        updated = SocialService.dispatch_direct_api_publish(content=content, user=request.user)
        return Response(SocialContentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'], url_path='metrics')
    def record_metrics(self, request, pk=None):
        content = self.get_object()
        membership = getattr(request, 'membership', None)
        if not (user_has_store_permission(membership, 'analytics.view') or user_has_store_permission(membership, 'content.edit')):
            raise PermissionDenied("دسترسی ثبت آمار محتوا را ندارید.")

        input_serializer = RecordMetricsInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        snapshot = SocialService.record_metrics(
            content=content,
            metrics_data=input_serializer.validated_data,
            source=input_serializer.validated_data.get('source', 'MANUAL'),
            user=request.user
        )
        return Response(ContentMetricSnapshotSerializer(snapshot).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='sync-live-metrics')
    def sync_live_metrics(self, request, pk=None):
        content = self.get_object()
        membership = getattr(request, 'membership', None)
        if not user_has_store_permission(membership, 'analytics.view'):
            raise PermissionDenied("دسترسی مشاهده و دریافت آمار شبکه‌های اجتماعی را ندارید.")

        result = SocialService.sync_live_metrics(content=content, user=request.user)
        return Response(result)

    @action(detail=True, methods=['post'], url_path='submit-proof')
    def submit_proof(self, request, pk=None):
        content = self.get_object()
        proof_url = request.data.get('proof_url', '')
        proof_image_url = request.data.get('proof_image_url', '')
        updated = SocialService.submit_proof(
            content=content,
            proof_url=proof_url,
            proof_image_url=proof_image_url,
            user=request.user
        )
        return Response(SocialContentDetailSerializer(updated).data)

    @action(detail=True, methods=['post'], url_path='verify-proof')
    def verify_proof(self, request, pk=None):
        content = self.get_object()
        membership = getattr(request, 'membership', None)
        if not user_has_store_permission(membership, 'content.publish'):
            raise PermissionDenied("فقط مدیر یا ادمین ارشد مجاز به تأیید نهایی مدارک انتشار محتوا است.")

        is_owner_or_admin = request.user.is_superuser or (membership and membership.role in [Role.OWNER, Role.ADMIN])
        if content.creator_id == request.user.id and not is_owner_or_admin:
            raise PermissionDenied("تولیدکننده محتوا مجاز به تأیید مدرک انتشار خود نیست و بررسی مستقل توسط مدیر الزامی است.")

        approved = request.data.get('approved', True)
        if isinstance(approved, str):
            approved = approved.lower() in ['true', '1', 'yes']
        notes = request.data.get('notes', '')
        updated = SocialService.verify_proof(
            content=content,
            manager_user=request.user,
            approved=approved,
            notes=notes
        )
        return Response(SocialContentDetailSerializer(updated).data)


    @action(detail=False, methods=['get'], url_path='calendar')
    def calendar(self, request):
        """Returns contents grouped or filtered for calendar view"""
        qs = self.get_queryset()
        serializer = SocialContentListSerializer(qs, many=True)
        return Response(serializer.data)


class SocialAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission, RequiresFeature('social.analytics')]

    def get(self, request):
        store = get_request_store(request)
        membership = getattr(request, 'membership', None)
        if not user_has_store_permission(membership, 'analytics.view'):
            raise PermissionDenied("دسترسی به گزارشات تحلیلی را ندارید.")

        days = int(request.query_params.get('days', 30))
        data = SocialService.get_social_analytics_summary(store=store, days=days)
        return Response(data)


class TeamSocialPerformanceView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission]

    def get(self, request):
        store = get_request_store(request)
        days = int(request.query_params.get('days', 30))
        stats = SocialService.get_team_performance(store=store, days=days)
        return Response(stats)
