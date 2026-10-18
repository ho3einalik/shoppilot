from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ConversationThreadViewSet, InstagramWebhookView, TelegramWebhookView

router = DefaultRouter()
router.register(r'threads', ConversationThreadViewSet, basename='inbox-thread')

urlpatterns = [
    path('webhooks/instagram/', InstagramWebhookView.as_view(), name='inbox-webhook-instagram'),
    path('webhooks/telegram/<uuid:store_id>/', TelegramWebhookView.as_view(), name='inbox-webhook-telegram'),
    path('', include(router.urls)),
]

