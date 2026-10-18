import logging
from celery import shared_task
from django.utils import timezone
from .models import SocialContent, ContentStatus, PublishingMode
from .services import SocialService

logger = logging.getLogger(__name__)


@shared_task(name='social.publish_due_scheduled_social_content')
def publish_due_scheduled_social_content():
    """
    Cron task: Scans for scheduled social contents that reached their scheduled_at time
    and executes direct API dispatch.
    """
    now = timezone.now()
    due_contents = SocialContent.objects.filter(
        status=ContentStatus.SCHEDULED,
        scheduled_at__lte=now
    ).select_related('store', 'account')

    published = 0
    failed = 0

    for content in due_contents:
        if content.publishing_mode == PublishingMode.DIRECT_API:
            try:
                SocialService.dispatch_direct_api_publish(content=content)
                published += 1
            except Exception as e:
                logger.error(f"Scheduled direct publish failed for content {content.id}: {e}")
                failed += 1
        else:
            # In MANUAL_REMINDER mode, keep SCHEDULED so admin can submit proof
            pass

    return f"Processed {due_contents.count()} scheduled posts: {published} published, {failed} failed."
