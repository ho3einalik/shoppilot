from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Avg, Count, F, Q
from rest_framework.exceptions import ValidationError, PermissionDenied

from .models import (
    SocialContent,
    ContentStatus,
    ApprovalAction,
    ContentApprovalLog,
    ContentMetricSnapshot,
    MetricSource
)


class SocialService:
    @staticmethod
    def submit_for_review(content, user):
        old_status = content.status
        content.status = ContentStatus.READY_FOR_REVIEW
        content.save()

        user_name = getattr(user, 'full_name', '') or getattr(user, 'email', str(user))
        ContentApprovalLog.objects.create(
            content=content,
            reviewer=user,
            action=ApprovalAction.SUBMITTED,
            feedback=f"محتوا جهت بررسی و تأیید توسط {user_name} ارسال شد."
        )
        return content

    @staticmethod
    def review_content(content, reviewer, action, feedback=""):
        if action not in ApprovalAction.values:
            raise ValidationError({"action": f"عملیات بررسی نامعتبر است: {action}"})

        if action == ApprovalAction.APPROVED:
            # If already scheduled, keep SCHEDULED, otherwise APPROVED
            if content.scheduled_at and content.scheduled_at > timezone.now():
                content.status = ContentStatus.SCHEDULED
            else:
                content.status = ContentStatus.APPROVED
        elif action == ApprovalAction.CHANGES_REQUESTED:
            content.status = ContentStatus.IN_PRODUCTION
        elif action == ApprovalAction.REJECTED:
            content.status = ContentStatus.REJECTED

        content.save()

        ContentApprovalLog.objects.create(
            content=content,
            reviewer=reviewer,
            action=action,
            feedback=feedback
        )
        return content

    @staticmethod
    def schedule_content(content, scheduled_at, user):
        if not scheduled_at:
            raise ValidationError({"scheduled_at": "زمان‌بندی انتشار مشخص نشده است."})

        content.scheduled_at = scheduled_at
        # If approved or already verified, set status to SCHEDULED
        if content.status in [ContentStatus.APPROVED, ContentStatus.IDEA, ContentStatus.IN_PRODUCTION]:
            content.status = ContentStatus.SCHEDULED
        content.save()
        return content

    @staticmethod
    def publish_content(content, published_url="", external_post_id="", user=None, direct_api_response=None):
        from .models import PublishingMode
        import uuid

        if content.publishing_mode == PublishingMode.MANUAL_REMINDER:
            raise ValidationError({
                "publishing_mode": "برای محتوای با شیوه انتشار دستی، فرآیند ثبت مدرک (submit-proof) و بررسی و تأیید مستقل توسط مدیر (verify-proof) الزامی است و امکان انتشار مستقیم بدون تأیید وجود ندارد."
            })

        # DIRECT_API mode: external_post_id must originate from a verified server-side response
        if content.publishing_mode == PublishingMode.DIRECT_API:
            if not direct_api_response or not direct_api_response.get('external_post_id'):
                raise ValidationError({
                    "external_post_id": "برای انتشار مستقیم از طریق API، شناسه پست در پلتفرم خارجی باید مستقیماً از پاسخ معتبر سرور و آداپتور اختصاصی دریافت شود."
                })
            external_post_id = str(direct_api_response.get('external_post_id')).strip()
            published_url = str(direct_api_response.get('published_url', '')).strip()

        content.status = ContentStatus.PUBLISHED
        content.published_at = timezone.now()
        if user:
            content.approved_by = user
        if published_url:
            content.published_url = published_url
        if external_post_id:
            content.external_post_id = external_post_id
        content.save()

        if user:
            user_name = getattr(user, 'full_name', '') or getattr(user, 'phone_number', str(user))
            ContentApprovalLog.objects.create(
                content=content,
                reviewer=user,
                action=ApprovalAction.APPROVED,
                feedback=f"انتشار مستقیم محتوا توسط {user_name} با تأیید پاسخ معتبر API سرور ثبت شد."
            )
        return content

    @staticmethod
    def dispatch_direct_api_publish(content, user=None):
        from .models import PublishingMode, SocialPlatform
        from apps.features.adapters import get_integration_adapter

        if content.publishing_mode != PublishingMode.DIRECT_API:
            raise ValidationError("این محتوا برای انتشار مستقیم API تنظیم نشده است.")

        if not content.account or not content.account.is_connected:
            raise ValidationError("اکانت شبکه اجتماعی مربوطه متصل نیست یا کلید دسترسی معتبر ندارد.")

        platform = content.account.platform
        if platform == SocialPlatform.INSTAGRAM:
            adapter = get_integration_adapter('social_instagram')
            if not adapter:
                raise ValidationError("آداپتور اینستاگرام در سیستم یافت نشد.")
            api_response = adapter.publish_content_to_instagram(store=content.store, content=content)
        elif platform == SocialPlatform.TELEGRAM:
            adapter = get_integration_adapter('social_telegram')
            if not adapter:
                raise ValidationError("آداپتور تلگرام در سیستم یافت نشد.")
            api_response = adapter.publish_content_to_telegram(store=content.store, content=content)
        else:
            raise ValidationError(f"انتشار مستقیم API برای پلتفرم {platform} در حال حاضر پشتیبانی نمی‌شود.")

        return SocialService.publish_content(
            content=content,
            user=user,
            direct_api_response=api_response
        )

    @staticmethod
    def sync_live_metrics(content, user=None):
        from .models import SocialPlatform, MetricSource
        from apps.features.adapters import get_integration_adapter

        if not content.external_post_id:
            raise ValidationError("این پست فاقد شناسه رسمی پلتفرم خارجی جهت استعلام آمار است.")

        if not content.account:
            raise ValidationError("اکانت متصل به این محتوا مشخص نشده است.")

        if content.account.platform == SocialPlatform.INSTAGRAM:
            adapter = get_integration_adapter('social_instagram')
            res = adapter.fetch_live_metrics(store=content.store, external_post_id=content.external_post_id)
            if not res.get('is_live'):
                return {'is_live': False, 'message': res.get('message', 'آمار زنده در دسترس نیست.')}

            snapshot = ContentMetricSnapshot.objects.create(
                content=content,
                source=MetricSource.API_SYNC,
                recorded_by=user,
                reach=res.get('reach', 0),
                impressions=res.get('impressions', res.get('reach', 0)),
                saves=res.get('saves', 0),
                likes=res.get('likes', 0),
                comments=res.get('comments', 0),
                shares=res.get('shares', 0)
            )
            return {
                'is_live': True,
                'snapshot_id': str(snapshot.id),
                'reach': snapshot.reach,
                'impressions': snapshot.impressions,
                'saves': snapshot.saves,
                'engagement': res.get('engagement', 0)
            }
        else:
            return {'is_live': False, 'message': 'استعلام آمار زنده برای این پلتفرم پشتیبانی نمی‌شود.'}

    @staticmethod
    def submit_proof(content, proof_url='', proof_image_url='', user=None):
        proof_url = (proof_url or '').strip()
        proof_image_url = (proof_image_url or '').strip()
        if not proof_url and not proof_image_url:
            raise ValidationError("ارسال حداقل یکی از موارد آدرس لینک یا تصویر مدرک انتشار الزامی است.")

        content.proof_url = proof_url
        content.proof_image_url = proof_image_url
        content.status = ContentStatus.PENDING_PROOF_VERIFICATION
        content.save(update_fields=['proof_url', 'proof_image_url', 'status', 'updated_at'])

        reviewer = user or getattr(content, 'creator', None)
        if reviewer:
            user_name = getattr(reviewer, 'full_name', '') or getattr(reviewer, 'phone_number', str(reviewer))
            ContentApprovalLog.objects.create(
                content=content,
                reviewer=reviewer,
                action=ApprovalAction.SUBMITTED,
                feedback=f"مدرک انتشار توسط {user_name} ثبت شد و در انتظار تأیید مدیر قرار گرفت."
            )
        return content

    @staticmethod
    def verify_proof(content, manager_user, approved=True, notes=''):
        if content.status != ContentStatus.PENDING_PROOF_VERIFICATION:
            raise ValidationError(f"تنها محتواهایی با وضعیت 'در انتظار بررسی مدرک' قابل تأیید هستند. وضعیت فعلی: {content.get_status_display()}")

        if not content.proof_url and not content.proof_image_url:
            raise ValidationError("مدرک انتشار معتبری (لینک یا تصویر) برای این محتوا ثبت نشده است.")

        if approved:
            content.status = ContentStatus.PUBLISHED
            content.published_at = timezone.now()
            content.approved_by = manager_user
            if not content.published_url and content.proof_url:
                content.published_url = content.proof_url
            content.save(update_fields=['status', 'published_at', 'approved_by', 'published_url', 'updated_at'])
            ContentApprovalLog.objects.create(
                content=content,
                reviewer=manager_user,
                action=ApprovalAction.APPROVED,
                feedback=notes or "مدرک انتشار توسط مدیر تأیید شد و پست منتشر شده اعلام گردید."
            )
        else:
            content.status = ContentStatus.REJECTED
            content.save(update_fields=['status', 'updated_at'])
            ContentApprovalLog.objects.create(
                content=content,
                reviewer=manager_user,
                action=ApprovalAction.REJECTED,
                feedback=notes or "مدرک انتشار رد شد."
            )
        return content


    @staticmethod
    def record_metrics(content, metrics_data, source=MetricSource.MANUAL, user=None):
        reach = int(metrics_data.get('reach', 0))
        impressions = int(metrics_data.get('impressions', reach))
        likes = int(metrics_data.get('likes', 0))
        comments = int(metrics_data.get('comments', 0))
        shares = int(metrics_data.get('shares', 0))
        saves = int(metrics_data.get('saves', 0))
        clicks = int(metrics_data.get('clicks', 0))
        attributed_orders_count = int(metrics_data.get('attributed_orders_count', 0))
        attributed_revenue = Decimal(str(metrics_data.get('attributed_revenue', 0)))

        snapshot = ContentMetricSnapshot.objects.create(
            content=content,
            source=source,
            recorded_by=user,
            reach=reach,
            impressions=impressions,
            likes=likes,
            comments=comments,
            shares=shares,
            saves=saves,
            clicks=clicks,
            attributed_orders_count=attributed_orders_count,
            attributed_revenue=attributed_revenue
        )
        return snapshot

    @staticmethod
    def get_social_analytics_summary(store, days=30):
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        contents = SocialContent.objects.filter(store=store)

        snapshots = ContentMetricSnapshot.objects.filter(
            content__store=store,
            recorded_at__gte=cutoff_date
        )

        total_posts = contents.filter(status=ContentStatus.PUBLISHED).count()
        total_reach = snapshots.aggregate(total=Sum('reach'))['total'] or 0
        total_impressions = snapshots.aggregate(total=Sum('impressions'))['total'] or 0
        total_likes = snapshots.aggregate(total=Sum('likes'))['total'] or 0
        total_comments = snapshots.aggregate(total=Sum('comments'))['total'] or 0
        total_saves = snapshots.aggregate(total=Sum('saves'))['total'] or 0
        total_shares = snapshots.aggregate(total=Sum('shares'))['total'] or 0
        total_attributed_revenue = snapshots.aggregate(total=Sum('attributed_revenue'))['total'] or Decimal('0')
        total_attributed_orders = snapshots.aggregate(total=Sum('attributed_orders_count'))['total'] or 0

        total_engagements = total_likes + total_comments + total_saves + total_shares
        avg_engagement_rate = 0.0
        if total_reach > 0:
            avg_engagement_rate = round(float((Decimal(total_engagements) / Decimal(total_reach)) * Decimal(100)), 2)

        # Platform distribution
        by_platform = []
        for account in store.socialaccounts.all():
            account_snapshots = ContentMetricSnapshot.objects.filter(content__account=account)
            acc_reach = account_snapshots.aggregate(total=Sum('reach'))['total'] or 0
            acc_posts = account.contents.filter(status=ContentStatus.PUBLISHED).count()
            by_platform.append({
                'account_id': str(account.id),
                'platform': account.platform,
                'platform_display': account.get_platform_display(),
                'handle': account.handle,
                'follower_count': account.follower_count,
                'published_posts': acc_posts,
                'total_reach': acc_reach
            })

        # Top 5 performing posts by engagement rate
        top_snapshots = snapshots.order_by('-engagement_rate', '-reach')[:5]
        top_posts = []
        for s in top_snapshots:
            top_posts.append({
                'id': str(s.content.id),
                'title': s.content.title,
                'content_type': s.content.get_content_type_display(),
                'thumbnail_url': s.content.thumbnail_url,
                'reach': s.reach,
                'likes': s.likes,
                'comments': s.comments,
                'saves': s.saves,
                'engagement_rate': float(s.engagement_rate),
                'published_url': s.content.published_url
            })

        return {
            'period_days': days,
            'total_published_posts': total_posts,
            'total_reach': total_reach,
            'total_impressions': total_impressions,
            'total_engagements': total_engagements,
            'average_engagement_rate': avg_engagement_rate,
            'total_attributed_revenue': total_attributed_revenue,
            'total_attributed_orders': total_attributed_orders,
            'platforms': by_platform,
            'top_posts': top_posts
        }

    @staticmethod
    def get_team_performance(store, days=30):
        cutoff_date = timezone.now() - timezone.timedelta(days=days)
        members = store.memberships.select_related('user').all()
        team_stats = []

        for m in members:
            assigned_contents = SocialContent.objects.filter(
                store=store,
                assignee=m.user,
                created_at__gte=cutoff_date
            )
            published = assigned_contents.filter(status=ContentStatus.PUBLISHED).count()
            total_reach = ContentMetricSnapshot.objects.filter(
                content__in=assigned_contents
            ).aggregate(total=Sum('reach'))['total'] or 0

            team_stats.append({
                'user_id': str(m.user.id),
                'full_name': m.user.get_full_name() or m.user.email,
                'role': m.role,
                'role_display': m.get_role_display(),
                'total_assigned_contents': assigned_contents.count(),
                'published_contents': published,
                'completion_rate_percent': round((published / assigned_contents.count() * 100) if assigned_contents.count() > 0 else 100.0, 1),
                'generated_reach': total_reach
            })

        return team_stats

