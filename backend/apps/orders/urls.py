from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, CustomerViewSet, WooCommerceSyncView, WooCommerceWebhookView

router = DefaultRouter()
router.register('customers', CustomerViewSet, basename='customer')
router.register('', OrderViewSet, basename='order')

urlpatterns = [
    path('woocommerce/sync/', WooCommerceSyncView.as_view(), name='woocommerce-sync'),
    path('woocommerce/webhook/<uuid:store_id>/', WooCommerceWebhookView.as_view(), name='woocommerce-webhook'),
    path('', include(router.urls)),
]

