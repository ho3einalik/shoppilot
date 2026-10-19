from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import ProductRecommendation, LoyaltyTier, MarketingCampaign, CampaignStatus, CampaignChannel
from apps.orders.models import Customer
from apps.features.adapters import get_integration_adapter

def calculate_loyalty_tier(lifetime_points: int) -> str:
    """Calculates customer loyalty tier based on cumulative lifetime points earned."""
    if lifetime_points >= 5000:
        return LoyaltyTier.PLATINUM
    elif lifetime_points >= 2000:
        return LoyaltyTier.GOLD
    elif lifetime_points >= 500:
        return LoyaltyTier.SILVER
    return LoyaltyTier.BRONZE

def evaluate_product_recommendations(store, source_variant_id):
    qs = ProductRecommendation.objects.filter(
        store=store,
        source_variant_id=source_variant_id
    ).select_related('recommended_variant__product')

    results = []
    for rec in qs:
        results.append({
            'recommendation_id': str(rec.id),
            'recommended_variant_id': str(rec.recommended_variant.id),
            'recommended_product_name': rec.recommended_variant.product.name,
            'recommended_sku': rec.recommended_variant.sku,
            'retail_price': str(rec.recommended_variant.retail_price),
            'recommendation_type': rec.recommendation_type,
            'discount_incentive_percent': rec.discount_incentive_percent
        })
    return results


def dispatch_marketing_campaign(campaign: MarketingCampaign, user=None) -> dict:
    """
    Dispatches marketing campaigns across configured channels (SMS or Email)
    targeting selected customer segments without fake synthetic successes.
    """
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED, CampaignStatus.SENDING):
        raise ValidationError(f"کمپین در وضعیت '{campaign.get_status_display()}' است و امکان ارسال مجدد ندارد.")

    store = campaign.store
    customers_qs = Customer.objects.filter(store=store, marketing_opt_in=True)
    if campaign.target_segment and campaign.target_segment != 'ALL':
        customers_qs = customers_qs.filter(crm_profile__segment=campaign.target_segment)

    customers = list(customers_qs)
    campaign.status = CampaignStatus.SENDING
    campaign.recipient_count = len(customers)
    campaign.save(update_fields=['status', 'recipient_count'])

    sent_count = 0       # Successfully dispatched to provider (SENT state from provider)
    delivered_count = 0  # Provider explicitly confirmed delivery (DELIVERED state)
    failed_count = 0

    if campaign.channel == CampaignChannel.SMS:
        adapter = get_integration_adapter('sms_kavenegar')
        if not adapter:
            campaign.status = CampaignStatus.DRAFT
            campaign.save(update_fields=['status'])
            raise ValidationError("سرویس پیامکی در سیستم پیکربندی نشده است.")

        for cust in customers:
            if not cust.phone_number:
                failed_count += 1
                continue
            text = campaign.message_template.replace('{name}', cust.full_name or 'مشتری گرامی')
            try:
                res = adapter.send_sms(store=store, receptor=cust.phone_number, message=text)
                provider_status = res.get('status', '').upper()
                # SENT and DELIVERED are distinct states — do not conflate them.
                # SENT means the provider accepted the message; DELIVERED means confirmed receipt.
                if provider_status == 'DELIVERED':
                    sent_count += 1
                    delivered_count += 1
                elif provider_status == 'SENT':
                    sent_count += 1
                    # delivered_count is NOT incremented — we don't have delivery confirmation yet
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

    elif campaign.channel == CampaignChannel.EMAIL:
        adapter = get_integration_adapter('email_smtp')
        if not adapter:
            campaign.status = CampaignStatus.DRAFT
            campaign.save(update_fields=['status'])
            raise ValidationError("سرویس ایمیل SMTP در سیستم پیکربندی نشده است.")

        for cust in customers:
            if not cust.email:
                failed_count += 1
                continue
            text = campaign.message_template.replace('{name}', cust.full_name or 'مشتری گرامی')
            try:
                res = adapter.send_email(store=store, to_email=cust.email, subject=campaign.name, body_html=f"<p>{text}</p>")
                provider_status = res.get('status', '').upper()
                if provider_status == 'DELIVERED':
                    sent_count += 1
                    delivered_count += 1
                elif provider_status == 'SENT':
                    sent_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1

    # STATUS FIX: A campaign with all recipients failed must NOT be marked SENT.
    # CampaignStatus has: DRAFT, SCHEDULED, SENDING, SENT, CANCELLED.
    # Use CANCELLED when zero recipients were successfully dispatched.
    # Use SENT when at least one message was dispatched (even if partially failed).
    total = len(customers)
    if total == 0 or sent_count == 0:
        final_status = CampaignStatus.CANCELLED  # No successful sends — do not claim SENT
    else:
        final_status = CampaignStatus.SENT

    campaign.status = final_status
    campaign.sent_count = sent_count
    campaign.delivered_count = delivered_count
    campaign.failed_count = failed_count
    campaign.sent_at = timezone.now()
    campaign.save(update_fields=['status', 'sent_count', 'delivered_count', 'failed_count', 'sent_at'])

    return {
        'status': 'SUCCESS' if sent_count > 0 else 'FAILED',
        'campaign_id': str(campaign.id),
        'recipients': len(customers),
        'sent_count': sent_count,
        'delivered_count': delivered_count,
        'failed_count': failed_count
    }


