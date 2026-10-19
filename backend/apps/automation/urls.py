from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AutomationRuleViewSet, OutboxEventViewSet

router = DefaultRouter()
router.register(r'rules', AutomationRuleViewSet, basename='automation-rule')
router.register(r'outbox', OutboxEventViewSet, basename='automation-outbox')

urlpatterns = [
    path('', include(router.urls)),
]
