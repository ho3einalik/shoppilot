import datetime
import logging
from django.db import models
from django.utils import timezone
from .models import AutomationRule, AutomationExecutionLog, ExecutionStatus, OutboxEvent, OutboxStatus
from apps.tasks.models import Task, TaskPriority, TaskStatus
from apps.features.adapters import get_integration_adapter

_logger = logging.getLogger(__name__)

def evaluate_conditions(conditions, payload):
    """Evaluate whether the event payload meets the rule conditions"""
    if not conditions:
        return True

    for key, expected_val in conditions.items():
        actual_val = payload.get(key)
        if actual_val is None:
            return False

        if key.startswith('min_'):
            try:
                if float(actual_val) < float(expected_val):
                    return False
            except (ValueError, TypeError):
                return False
        elif key.startswith('max_'):
            try:
                if float(actual_val) > float(expected_val):
                    return False
            except (ValueError, TypeError):
                return False
        elif str(actual_val).upper() != str(expected_val).upper():
            return False

    return True

def execute_actions(rule, actions, payload, dry_run=False):
    """Execute defined actions for a triggered rule (or simulate if dry_run=True)"""
    results = []
    store = rule.store
    creator = getattr(rule, 'created_by', None) or store.business.owner

    for act in actions:
        act_type = act.get('type')

        if act_type == 'CREATE_TASK':
            title = act.get('title', f"وظیفه خودکار: {rule.name}")
            desc = act.get('description', f"ایجاد شده توسط اتوماسیون بر اساس رویداد {rule.trigger}.\nجزئیات: {payload}")
            priority = act.get('priority', TaskPriority.MEDIUM)
            if dry_run:
                results.append(f"[شبیه‌سازی] وظیفه '{title}' با اولویت {priority} در کارتابل تیم ایجاد خواهد شد.")
            else:
                Task.objects.create(
                    store=store,
                    title=title,
                    description=desc,
                    priority=priority,
                    status=TaskStatus.TODO,
                    creator=creator
                )
                results.append(f"وظیفه '{title}' با موفقیت در کارتابل تیم ثبت شد.")

        elif act_type == 'SEND_SMS':
            phone = payload.get('customer_phone') or payload.get('phone_number')
            template = act.get('template', 'سفارش شما در فروشگاه با موفقیت ثبت شد.')
            if dry_run:
                results.append(f"[شبیه‌سازی] پیامک به شماره {phone or 'نامشخص'} ارسال خواهد شد: {template}")
            elif phone:
                sms_adapter = get_integration_adapter('sms_gateway')
                sms_res = sms_adapter.send_sms(to=phone, message=template, store=store)
                status_code = sms_res.get('status')
                if status_code in ['FAILED', 'ERROR']:
                    err = sms_res.get('error') or sms_res.get('message') or 'خطای درگاه پیامک'
                    raise RuntimeError(f"ارسال پیامک به {phone} با خطا مواجه شد: {err}")
                results.append(f"پیامک به شماره {phone} ارسال شد (وضعیت: {status_code}).")
            else:
                results.append("شماره تلفنی در داده‌های رویداد برای ارسال پیامک یافت نشد.")

        elif act_type == 'NOTIFY_TEAM':
            if dry_run:
                results.append(f"[شبیه‌سازی] اعلان سیستمی برای تیم ثبت خواهد شد: {act.get('message', 'رویداد اتوماسیون')}")
            else:
                results.append(f"اعلان سیستمی برای تیم ثبت شد: {act.get('message', 'رویداد اتوماسیون')}")

    return "\n".join(results)

SENSITIVE_KEYS = {'password', 'token', 'secret', 'api_key', 'authorization', 'card_number', 'cvv2', 'credentials'}

def sanitize_payload(payload):
    """Sanitizes sensitive information (tokens, secrets, credentials, phone numbers) deeply from event payload before storing in execution logs"""
    if isinstance(payload, dict):
        sanitized = {}
        for k, v in payload.items():
            if any(sens in str(k).lower() for sens in SENSITIVE_KEYS):
                sanitized[k] = '***REDACTED***'
            else:
                sanitized[k] = sanitize_payload(v)
        return sanitized
    elif isinstance(payload, (list, tuple)):
        return [sanitize_payload(item) for item in payload]
    elif isinstance(payload, str):
        if len(payload) == 11 and payload.startswith('09') and payload.isdigit():
            return payload[:4] + '****' + payload[-3:]
        return payload
    return payload


from django.db import transaction, IntegrityError


def trigger_automation(store, trigger_event, payload, dry_run=False, raise_on_failure=False):
    """Trigger all active rules matching the event for a store with atomic idempotency claims and retry support"""
    rules = AutomationRule.objects.filter(store=store, trigger=trigger_event, is_active=True)
    executed_count = 0
    sanitized_data = sanitize_payload(payload)
    errors = []

    for rule in rules:
        matches = evaluate_conditions(rule.conditions, payload)
        event_key = payload.get('idempotency_key') or payload.get('event_id')

        if not matches:
            if not dry_run:
                AutomationExecutionLog.objects.create(
                    rule=rule,
                    idempotency_key=f"skipped-{event_key}" if event_key else None,
                    trigger_event=trigger_event,
                    event_payload=sanitized_data,
                    status=ExecutionStatus.SKIPPED,
                    details="شرایط قانون با داده‌های رویداد مطابقت نداشت."
                )
            continue

        if dry_run:
            execute_actions(rule, rule.actions, payload, dry_run=True)
            executed_count += 1
            continue

        # Atomic claim under concurrency with idempotency:
        # If an execution log already exists for this rule and key:
        # - If already SUCCESS: skip (prevent duplicate execution)
        # - If FAILED or RUNNING: allow retry by updating the record
        log_entry = None
        if event_key:
            existing_log = AutomationExecutionLog.objects.filter(rule=rule, idempotency_key=str(event_key)).first()
            if existing_log:
                if existing_log.status == ExecutionStatus.SUCCESS:
                    continue
                log_entry = existing_log
                log_entry.status = ExecutionStatus.RUNNING
                log_entry.details = "در حال تلاش مجدد برای اجرای اقدامات..."
                log_entry.save(update_fields=['status', 'details'])
            else:
                try:
                    with transaction.atomic():
                        log_entry = AutomationExecutionLog.objects.create(
                            rule=rule,
                            idempotency_key=str(event_key),
                            trigger_event=trigger_event,
                            event_payload=sanitized_data,
                            status=ExecutionStatus.RUNNING,
                            details="در حال اجرای اقدامات..."
                        )
                except IntegrityError:
                    # Concurrent worker already claimed or completed this rule for this idempotency key
                    continue
        else:
            log_entry = AutomationExecutionLog.objects.create(
                rule=rule,
                trigger_event=trigger_event,
                event_payload=sanitized_data,
                status=ExecutionStatus.RUNNING,
                details="در حال اجرای اقدامات..."
            )

        try:
            details = execute_actions(rule, rule.actions, payload, dry_run=False)
            rule.execution_count += 1
            rule.last_executed_at = timezone.now()
            rule.save(update_fields=['execution_count', 'last_executed_at'])

            log_entry.status = ExecutionStatus.SUCCESS
            log_entry.details = details
            log_entry.save(update_fields=['status', 'details'])
            executed_count += 1
        except Exception as e:
            log_entry.status = ExecutionStatus.FAILED
            log_entry.details = f"خطا در اجرای اقدامات: {str(e)}"
            log_entry.save(update_fields=['status', 'details'])
            errors.append(f"قانون '{rule.name}' با خطا مواجه شد: {str(e)}")

    if raise_on_failure and errors:
        raise RuntimeError(" | ".join(errors))

    return executed_count


def publish_outbox_event(store, event_type, payload, event_key='', max_retries=5):
    """
    Transactional Outbox Publisher.
    Persists the automation event atomically inside the current database transaction.
    Guarantees at-least-once delivery: even if server restarts or network drops immediately,
    the event is safely recorded in the Outbox and will be processed.
    Also schedules an immediate on_commit trigger for minimal latency.
    """
    event = OutboxEvent.objects.create(
        store=store,
        event_type=event_type,
        event_key=event_key or payload.get('idempotency_key', '') or '',
        payload=payload,
        status=OutboxStatus.PENDING,
        max_retries=max_retries
    )

    event_id = event.id

    def _immediate_dispatch():
        try:
            process_outbox_event(event_id)
        except Exception:
            _logger.warning("Immediate outbox dispatch for event %s failed; worker will retry.", event_id, exc_info=True)

    transaction.on_commit(_immediate_dispatch)
    return event


@transaction.atomic
def process_outbox_event(event_id):
    """
    Processes a single OutboxEvent atomically with idempotency and exponential backoff retry.
    """
    try:
        event = OutboxEvent.objects.select_for_update().get(id=event_id)
    except OutboxEvent.DoesNotExist:
        return None

    if event.status == OutboxStatus.DELIVERED:
        return event

    event.status = OutboxStatus.PROCESSING
    event.save(update_fields=['status', 'updated_at'])

    try:
        trigger_automation(
            store=event.store,
            trigger_event=event.event_type,
            payload=event.payload,
            dry_run=False,
            raise_on_failure=True
        )
        event.status = OutboxStatus.DELIVERED
        event.processed_at = timezone.now()
        event.last_error = ''
        event.save(update_fields=['status', 'processed_at', 'last_error', 'updated_at'])
    except Exception as exc:
        event.retry_count += 1
        event.last_error = str(exc)
        if event.retry_count >= event.max_retries:
            event.status = OutboxStatus.DEAD_LETTER
            event.next_retry_at = None
            _logger.critical(
                "CRITICAL: OutboxEvent %s reached max retries (%d/%d) and moved to DEAD_LETTER queue. "
                "Event type: %s, payload: %s, error: %s",
                event_id, event.retry_count, event.max_retries, event.event_type, event.payload, exc
            )
        else:
            event.status = OutboxStatus.PENDING
            # Exponential backoff: 10s * (2 ** retry_count)
            delay_seconds = 10 * (2 ** (event.retry_count - 1))
            event.next_retry_at = timezone.now() + datetime.timedelta(seconds=delay_seconds)
            _logger.error("OutboxEvent %s failed (attempt %d/%d): %s", event_id, event.retry_count, event.max_retries, exc)
        event.save(update_fields=['status', 'retry_count', 'last_error', 'next_retry_at', 'updated_at'])

    return event


def process_pending_outbox_events(limit=50):
    """
    Scans and processes pending or failed retryable Outbox events.
    Called by background Celery worker or cron task.
    """
    now = timezone.now()
    pending_ids = list(
        OutboxEvent.objects.filter(
            status__in=[OutboxStatus.PENDING, OutboxStatus.FAILED],
            retry_count__lt=models.F('max_retries')
        ).filter(
            models.Q(next_retry_at__isnull=True) | models.Q(next_retry_at__lte=now)
        ).order_by('created_at').values_list('id', flat=True)[:limit]
    )

    processed_count = 0
    for eid in pending_ids:
        process_outbox_event(eid)
        processed_count += 1

    return processed_count


@transaction.atomic
def replay_outbox_event(event_id, reset_retries=True):
    """
    Replays an Outbox event from DEAD_LETTER or FAILED status back into PENDING.
    Resets next_retry_at to now and optionally resets retry_count to allow clean reprocessing.
    """
    event = OutboxEvent.objects.select_for_update().get(id=event_id)
    if reset_retries:
        event.retry_count = 0
    event.status = OutboxStatus.PENDING
    event.next_retry_at = timezone.now()
    if event.last_error:
        event.last_error = f"[Replay Requested] Previous error: {event.last_error}"
    event.save(update_fields=['status', 'retry_count', 'next_retry_at', 'last_error', 'updated_at'])
    _logger.info("OutboxEvent %s was replayed and set to PENDING.", event_id)
    return event


def replay_all_dead_letter_events(store=None):
    """
    Replays all Outbox events currently residing in DEAD_LETTER status for a store (or globally).
    """
    qs = OutboxEvent.objects.filter(status=OutboxStatus.DEAD_LETTER)
    if store:
        qs = qs.filter(store=store)

    ids = list(qs.values_list('id', flat=True))
    replayed_count = 0
    for eid in ids:
        replay_outbox_event(eid)
        replayed_count += 1

    _logger.info("Replayed %d DEAD_LETTER outbox events.", replayed_count)
    return replayed_count


