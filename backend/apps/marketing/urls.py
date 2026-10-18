from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CouponViewSet,
    CustomerLoyaltyAccountViewSet,
    ProductBundleViewSet,
    AbandonedCartViewSet,
    CustomerReferralViewSet,
    ProductRecommendationViewSet,
    CampaignAttributionViewSet,
    MarketingCampaignViewSet
)

router = DefaultRouter()
router.register(r'coupons', CouponViewSet, basename='coupon')
router.register(r'loyalty', CustomerLoyaltyAccountViewSet, basename='loyalty-account')
router.register(r'bundles', ProductBundleViewSet, basename='product-bundle')
router.register(r'abandoned-carts', AbandonedCartViewSet, basename='abandoned-cart')
router.register(r'referrals', CustomerReferralViewSet, basename='customer-referral')
router.register(r'recommendations', ProductRecommendationViewSet, basename='product-recommendation')
router.register(r'attributions', CampaignAttributionViewSet, basename='campaign-attribution')
router.register(r'campaigns', MarketingCampaignViewSet, basename='marketing-campaign')

urlpatterns = [
    path('', include(router.urls)),
]

