from rest_framework import serializers
from .models import (
    Coupon,
    CustomerLoyaltyAccount,
    ProductBundle,
    ProductBundleItem,
    AbandonedCart,
    CustomerReferral,
    ProductRecommendation,
    CampaignAttribution
)

class CouponSerializer(serializers.ModelSerializer):
    discount_type_display = serializers.CharField(source='get_discount_type_display', read_only=True)

    class Meta:
        model = Coupon
        fields = [
            'id', 'code', 'description', 'discount_type', 'discount_type_display',
            'discount_value', 'min_order_amount', 'max_discount_amount',
            'start_date', 'end_date', 'max_uses', 'uses_count', 'is_stackable', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'uses_count', 'created_at', 'updated_at']


class CustomerLoyaltyAccountSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    tier_display = serializers.CharField(source='get_tier_display', read_only=True)

    class Meta:
        model = CustomerLoyaltyAccount
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone',
            'tier', 'tier_display', 'points_balance', 'lifetime_points',
            'referral_code', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProductBundleItemSerializer(serializers.ModelSerializer):
    variant_sku = serializers.CharField(source='variant.sku', read_only=True)
    variant_name = serializers.CharField(source='variant.product.name', read_only=True)

    class Meta:
        model = ProductBundleItem
        fields = ['id', 'variant', 'variant_sku', 'variant_name', 'quantity']


class ProductBundleSerializer(serializers.ModelSerializer):
    items = ProductBundleItemSerializer(many=True, read_only=True)

    class Meta:
        model = ProductBundle
        fields = ['id', 'name', 'sku', 'bundle_price', 'description', 'is_active', 'items', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class AbandonedCartSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AbandonedCart
        fields = [
            'id', 'customer', 'customer_name', 'phone_or_email', 'cart_items',
            'total_amount', 'status', 'status_display', 'recovery_coupon',
            'recovery_sms_sent_at', 'recovered_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'status_display']


class CustomerReferralSerializer(serializers.ModelSerializer):
    referrer_name = serializers.CharField(source='referrer.full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = CustomerReferral
        fields = [
            'id', 'referrer', 'referrer_name', 'referee_phone',
            'referred_customer', 'referral_code', 'status', 'status_display',
            'points_awarded', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'status_display']


class ProductRecommendationSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source_variant.product.name', read_only=True)
    source_sku = serializers.CharField(source='source_variant.sku', read_only=True)
    recommended_name = serializers.CharField(source='recommended_variant.product.name', read_only=True)
    recommended_sku = serializers.CharField(source='recommended_variant.sku', read_only=True)
    recommended_price = serializers.CharField(source='recommended_variant.retail_price', read_only=True)
    type_display = serializers.CharField(source='get_recommendation_type_display', read_only=True)

    class Meta:
        model = ProductRecommendation
        fields = [
            'id', 'source_variant', 'source_name', 'source_sku',
            'recommended_variant', 'recommended_name', 'recommended_sku', 'recommended_price',
            'recommendation_type', 'type_display', 'discount_incentive_percent'
        ]
        read_only_fields = ['id']


class CampaignAttributionSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source='order.order_number', read_only=True)
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)

    class Meta:
        model = CampaignAttribution
        fields = [
            'id', 'order', 'order_number', 'campaign', 'campaign_name',
            'utm_source', 'utm_medium', 'utm_campaign', 'attributed_revenue',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']


from .models import MarketingCampaign


class MarketingCampaignSerializer(serializers.ModelSerializer):
    channel_display = serializers.CharField(source='get_channel_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = MarketingCampaign
        fields = [
            'id', 'name', 'target_segment', 'channel', 'channel_display',
            'message_template', 'status', 'status_display',
            'recipient_count', 'sent_count', 'delivered_count', 'failed_count',
            'attributed_revenue', 'attributed_orders_count',
            'scheduled_at', 'sent_at', 'created_at'
        ]
        read_only_fields = [
            'id', 'status_display', 'recipient_count', 'sent_count',
            'delivered_count', 'failed_count', 'attributed_revenue',
            'attributed_orders_count', 'sent_at', 'created_at'
        ]

