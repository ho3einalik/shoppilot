from rest_framework import serializers
from .models import ConversationThread, ChatMessage

class ChatMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender_user.full_name', read_only=True)
    sender_type_display = serializers.CharField(source='get_sender_type_display', read_only=True)

    class Meta:
        model = ChatMessage
        fields = [
            'id', 'thread', 'sender_type', 'sender_type_display',
            'sender_name', 'text', 'media_url', 'is_ai_generated',
            'was_edited_by_human', 'delivery_status', 'external_message_id',
            'error_message', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'delivery_status', 'external_message_id', 'error_message']


class ConversationThreadSerializer(serializers.ModelSerializer):
    channel_display = serializers.CharField(source='get_channel_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    assigned_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    messages = ChatMessageSerializer(many=True, read_only=True)

    class Meta:
        model = ConversationThread
        fields = [
            'id', 'channel', 'channel_display', 'external_thread_id',
            'customer', 'customer_name', 'order', 'order_number', 'contact_name', 'contact_handle',
            'status', 'status_display', 'assigned_to', 'assigned_name',
            'last_message_preview', 'unread_count', 'last_message_at',
            'internal_notes', 'auto_reply_enabled', 'tags',
            'messages', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_message_at', 'order_number']
