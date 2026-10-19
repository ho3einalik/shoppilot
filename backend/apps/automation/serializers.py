from rest_framework import serializers
from .models import AutomationRule, AutomationExecutionLog, OutboxEvent

class AutomationExecutionLogSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AutomationExecutionLog
        fields = ['id', 'trigger_event', 'event_payload', 'status', 'status_display', 'details', 'created_at']
        read_only_fields = ['id', 'created_at']


class AutomationRuleSerializer(serializers.ModelSerializer):
    trigger_display = serializers.CharField(source='get_trigger_display', read_only=True)
    logs = AutomationExecutionLogSerializer(many=True, read_only=True)

    class Meta:
        model = AutomationRule
        fields = [
            'id', 'name', 'description', 'trigger', 'trigger_display',
            'conditions', 'actions', 'is_active', 'execution_count',
            'last_executed_at', 'logs', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'execution_count', 'last_executed_at', 'created_at', 'updated_at']


class OutboxEventSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = OutboxEvent
        fields = [
            'id', 'event_type', 'event_key', 'payload', 'status', 'status_display',
            'retry_count', 'max_retries', 'last_error', 'next_retry_at',
            'processed_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
