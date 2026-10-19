import logging
from celery import shared_task
from .services import reconcile_pending_online_payments

logger = logging.getLogger(__name__)


@shared_task(name='payments.reconcile_pending_online_payments_task')
def reconcile_pending_online_payments_task(store_id=None, max_age_hours=24):
    """
    Background Celery task to reconcile pending or expired online payments with the gateway.
    Ensures any transactions completed by customers at the gateway are verified and settled.
    """
    try:
        from apps.tenancy.models import Store
        store = Store.objects.get(id=store_id) if store_id else None
        res = reconcile_pending_online_payments(store=store, max_age_hours=max_age_hours)
        logger.info(f"Reconciled online payments: {res}")
        return res
    except Exception as e:
        logger.error(f"Error executing payments reconciliation task: {e}")
        raise
