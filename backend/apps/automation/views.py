from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import AutomationRule, AutomationExecutionLog, OutboxEvent, OutboxStatus
from .serializers import AutomationRuleSerializer, AutomationExecutionLogSerializer, OutboxEventSerializer
from .services import execute_actions, evaluate_conditions, replay_outbox_event, replay_all_dead_letter_events
from apps.tenancy.permissions import IsStoreMemberPermission

class AutomationRuleViewSet(viewsets.ModelViewSet):
    serializer_class = AutomationRuleSerializer
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission]

    def get_queryset(self):
        store = getattr(self.request, 'store', None)
        if not store:
            return AutomationRule.objects.none()
        return AutomationRule.objects.filter(store=store).prefetch_related('logs')

    def perform_create(self, serializer):
        serializer.save(store=self.request.store)

    @action(detail=True, methods=['post'], url_path='test-run')
    def test_run(self, request, pk=None):
        rule = self.get_object()
        sample_payload = request.data.get('payload', {})
        dry_run = request.data.get('dry_run', True)
        matches = evaluate_conditions(rule.conditions, sample_payload)
        if not matches:
            return Response({
                'matched': False,
                'message': 'داده‌های تستی ارسالی با شرایط تعیین‌شده در این قانون مطابقت ندارند.'
            })

        output = execute_actions(rule, rule.actions, sample_payload, dry_run=dry_run)
        return Response({
            'matched': True,
            'dry_run': dry_run,
            'message': 'قانون اتوماسیون با موفقیت شبیه‌سازی و تست شد.' if dry_run else 'قانون اتوماسیون با موفقیت تست و اجرا شد.',
            'execution_output': output
        })


class OutboxEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OutboxEventSerializer
    permission_classes = [permissions.IsAuthenticated, IsStoreMemberPermission]

    def get_queryset(self):
        store = getattr(self.request, 'store', None)
        if not store:
            return OutboxEvent.objects.none()
        qs = OutboxEvent.objects.filter(store=store)
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=True, methods=['post'], url_path='replay')
    def replay(self, request, pk=None):
        event = self.get_object()
        replayed = replay_outbox_event(event.id)
        return Response({
            'message': 'رویداد با موفقیت به صف ارسال مجدد (PENDING) بازگردانده شد.',
            'event': OutboxEventSerializer(replayed).data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='replay-dead-letters')
    def replay_dead_letters(self, request):
        store = getattr(self.request, 'store', None)
        count = replay_all_dead_letter_events(store=store)
        return Response({
            'message': f'{count} رویداد متوقف‌شده در صف بن‌بست (Dead Letter) جهت پردازش مجدد فعال شدند.',
            'count': count
        }, status=status.HTTP_200_OK)
