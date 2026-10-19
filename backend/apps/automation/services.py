from django.utils import timezone
from .models import AutomationRule, AutomationExecutionLog, ExecutionStatus
from apps.tasks.models import Task, TaskPriority, TaskStatus
from apps.features.adapters import get_integration_adapter

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
                results.append(f"پیامک به شماره {phone} ارسال شد (وضعیت: {sms_res.get('status')}).")
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
    """Sanitizes sensitive information from event payload before storing in execution logs"""
    if not isinstance(payload, dict):
        return payload

    sanitized = {}
    for k, v in payload.items():
        if any(sens in k.lower() for sens in SENSITIVE_KEYS):
            sanitized[k] = '***REDACTED***'
        elif isinstance(v, dict):
            sanitized[k] = sanitize_payload(v)
        elif isinstance(v, list):
            sanitized[k] = [sanitize_payload(i) if isinstance(i, dict) else i for i in v]
        elif isinstance(v, str) and len(v) == 11 and v.startswith('09'):
            # Mask phone numbers in payload logs
            sanitized[k] = v[:4] + '****' + v[-3:]
        else:
            sanitized[k] = v
    return sanitized


from django.db import transaction, IntegrityError


def trigger_automation(store, trigger_event, payload, dry_run=False):
    """Trigger all active rules matching the event for a store with atomic idempotency claims"""
    rules = AutomationRule.objects.filter(store=store, trigger=trigger_event, is_active=True)
    executed_count = 0
    sanitized_data = sanitize_payload(payload)

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

        # Atomic claim under concurrency
        log_entry = None
        if event_key:
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

    return executed_count

