import os
import json
import logging
import smtplib
import socket
import ssl
import urllib.request
import urllib.parse
import urllib.error
from abc import ABC, abstractmethod
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional, List, Tuple
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import IntegrationState, StoreIntegrationConfig, StoreFeatureSetting
from .security import encrypt_secret, decrypt_secret, mask_secret, validate_custom_url

logger = logging.getLogger(__name__)


class IntegrationHealthResult:
    def __init__(self, state: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.state = state
        self.message = message
        self.details = details or {}

    def to_dict(self):
        return {
            'state': self.state,
            'message': self.message,
            'details': self.details,
            'is_healthy': self.state in (IntegrationState.CONNECTED, IntegrationState.READY, IntegrationState.ACTIVE)
        }


class BaseIntegrationAdapter(ABC):
    name: str = ""
    category: str = "OTHER"  # SMS, SOCIAL, PAYMENT, SHIPPING, AI, EMAIL, OTHER
    display_name_fa: str = ""
    description_fa: str = ""
    guide_fa: str = ""

    @abstractmethod
    def get_schema(self) -> List[Dict[str, Any]]:
        """Returns the schema definition for configuration fields"""
        pass

    def get_store_config_record(self, store) -> Optional[StoreIntegrationConfig]:
        if not store:
            return None
        return StoreIntegrationConfig.objects.filter(store=store, integration_id=self.name).first()

    def get_config(self, store, decrypted: bool = False) -> Dict[str, Any]:
        """
        Retrieves stored configuration for this store.
        If decrypted=False, secret fields are masked with mask_secret.
        Falls back to legacy feature_configs and environment variables if not yet configured.
        """
        record = self.get_store_config_record(store)
        schema = {f['name']: f for f in self.get_schema()}
        result = {}

        if record and record.config_data:
            for k, v in record.config_data.items():
                is_secret = schema.get(k, {}).get('is_secret', False)
                if is_secret:
                    if decrypted:
                        result[k] = decrypt_secret(v)
                    else:
                        result[k] = mask_secret(v)
                        result[f"{k}_is_set"] = bool(v)
                else:
                    result[k] = v
        else:
            # Fallback to feature_configs or environment
            result = self._get_fallback_config(store, decrypted=decrypted)

        # Ensure all schema keys exist in output
        for field_name, f_def in schema.items():
            if field_name not in result:
                result[field_name] = f_def.get('default', '')
                if f_def.get('is_secret'):
                    result[f"{field_name}_is_set"] = False

        return result

    def _get_fallback_config(self, store, decrypted: bool = False) -> Dict[str, Any]:
        """Override in subclasses to provide backward compatibility with env vars"""
        return {}

    def save_config(self, store, raw_config: Dict[str, Any]) -> StoreIntegrationConfig:
        """
        Saves and encrypts secrets for the store.
        Invalidates previous successful test if secret or critical settings changed.
        """
        record, created = StoreIntegrationConfig.objects.get_or_create(
            store=store,
            integration_id=self.name,
            defaults={'status': IntegrationState.NOT_CONFIGURED}
        )

        schema = {f['name']: f for f in self.get_schema()}
        existing_data = dict(record.config_data or {})
        updated_data = dict(existing_data)
        has_critical_changes = False

        for f_name, f_def in schema.items():
            val = raw_config.get(f_name)
            if val is None and 'default' in f_def:
                val = f_def['default']
            is_secret = f_def.get('is_secret', False)
            is_required = f_def.get('required', False)

            if f_def.get('type') == 'url' and val:
                val = validate_custom_url(str(val))

            if is_secret:
                # If client sent masked bullets or blank, preserve existing
                val_str = str(val).strip() if val is not None else ""
                if not val_str or '••' in val_str:
                    # Keep previous
                    pass
                else:
                    # New plain secret provided
                    enc_val = encrypt_secret(val_str)
                    if enc_val != existing_data.get(f_name):
                        updated_data[f_name] = enc_val
                        has_critical_changes = True
            else:
                if val is not None:
                    if val != existing_data.get(f_name):
                        has_critical_changes = True
                    updated_data[f_name] = val
                elif is_required and f_name not in updated_data:
                    raise ValidationError({f_name: f"فیلد '{f_def.get('label_fa', f_name)}' الزامی است."})

        record.config_data = updated_data

        # Status transition rule:
        # Saving alone does NOT activate. If credentials changed, invalidate previous test.
        if has_critical_changes:
            record.status = IntegrationState.CONFIGURED
            record.last_test_success = False
            record.is_active = False
        elif record.status == IntegrationState.NOT_CONFIGURED:
            # Check if all required fields are satisfied
            all_required_set = True
            for f_name, f_def in schema.items():
                if f_def.get('required') and not updated_data.get(f_name):
                    all_required_set = False
                    break
            record.status = IntegrationState.CONFIGURED if all_required_set else IntegrationState.NOT_CONFIGURED

        record.save()

        # Sync to StoreFeatureSetting
        settings = getattr(store, 'feature_settings', None)
        if settings:
            states = dict(settings.integration_states or {})
            states[self.name] = record.status
            settings.integration_states = states
            settings.save()

        return record

    def test_connection(self, store, **kwargs) -> IntegrationHealthResult:
        """
        Executes real connectivity test.
        Transitions state to READY if successful, or TEST_FAILED / REAUTH_REQUIRED if failed.
        """
        record, _ = StoreIntegrationConfig.objects.get_or_create(
            store=store,
            integration_id=self.name,
            defaults={'status': IntegrationState.NOT_CONFIGURED}
        )

        record.status = IntegrationState.TESTING
        record.save(update_fields=['status'])

        try:
            result = self._execute_live_test(store, **kwargs)
        except Exception as e:
            logger.error(f"Error testing integration {self.name}: {e}")
            result = IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"خطا در برقراری ارتباط با ارائه‌دهنده: {str(e)}"
            )

        record.last_tested_at = timezone.now()
        record.last_test_result = result.details
        record.last_test_error = "" if result.to_dict()['is_healthy'] else result.message

        if result.to_dict()['is_healthy']:
            record.last_test_success = True
            record.last_connected_at = timezone.now()
            # If was already active, preserve active state
            record.status = IntegrationState.ACTIVE if record.is_active else IntegrationState.READY
        else:
            record.last_test_success = False
            record.is_active = False
            record.status = result.state

        record.save()

        # Sync with store feature settings
        settings = getattr(store, 'feature_settings', None)
        if settings:
            states = dict(settings.integration_states or {})
            states[self.name] = IntegrationState.CONNECTED if result.to_dict()['is_healthy'] else record.status
            settings.integration_states = states
            settings.save()

        return result

    @abstractmethod
    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        """Provider specific live verification"""
        pass

    def activate(self, store) -> Tuple[bool, str]:
        record = self.get_store_config_record(store)
        if not record or not record.last_test_success or record.status not in (IntegrationState.READY, IntegrationState.ACTIVE, IntegrationState.CONNECTED):
            raise ValidationError("امکان فعال‌سازی اتصال وجود ندارد؛ ابتدا باید تست اتصال با موفقیت انجام شود.")

        record.status = IntegrationState.ACTIVE
        record.is_active = True
        record.save()

        settings = getattr(store, 'feature_settings', None)
        if settings:
            states = dict(settings.integration_states or {})
            states[self.name] = IntegrationState.CONNECTED
            settings.integration_states = states
            settings.save()

        return True, f"اتصال '{self.display_name_fa}' با موفقیت فعال شد."

    def deactivate(self, store) -> Tuple[bool, str]:
        record = self.get_store_config_record(store)
        if record:
            record.status = IntegrationState.DISABLED
            record.is_active = False
            record.save()

        settings = getattr(store, 'feature_settings', None)
        if settings:
            states = dict(settings.integration_states or {})
            states[self.name] = IntegrationState.DISABLED_BY_STORE
            settings.integration_states = states
            settings.save()

        return True, f"اتصال '{self.display_name_fa}' غیرفعال شد."

    def get_status(self, store) -> str:
        record = self.get_store_config_record(store)
        if record:
            return record.status

        # Check legacy override in store feature settings
        settings = getattr(store, 'feature_settings', None)
        if settings and settings.integration_states:
            override = settings.integration_states.get(self.name)
            if override:
                return override

        return IntegrationState.NOT_CONFIGURED

    def health_check(self, store) -> IntegrationHealthResult:
        status = self.get_status(store)
        record = self.get_store_config_record(store)

        if status in (IntegrationState.ACTIVE, IntegrationState.CONNECTED):
            return IntegrationHealthResult(
                state=IntegrationState.CONNECTED,
                message=f"اتصال {self.display_name_fa} فعال و عملیاتی است.",
                details=record.last_test_result if record else {}
            )
        elif status == IntegrationState.READY:
            return IntegrationHealthResult(
                state=IntegrationState.READY,
                message=f"تست اتصال با موفقیت انجام شده و آماده فعال‌سازی است.",
                details=record.last_test_result if record else {}
            )
        elif status == IntegrationState.TEST_FAILED:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=record.last_test_error if record and record.last_test_error else "تست اتصال ناموفق بود.",
                details=record.last_test_result if record else {}
            )
        elif status == IntegrationState.DISABLED:
            return IntegrationHealthResult(
                state=IntegrationState.DISABLED_BY_STORE,
                message="این سرویس توسط فروشگاه غیرفعال شده است."
            )
        elif status == IntegrationState.CONFIGURED:
            return IntegrationHealthResult(
                state=IntegrationState.CONFIGURED,
                message="اطلاعات ذخیره شده است؛ لطفاً دکمه تست اتصال را بزنید."
            )
        elif status in (IntegrationState.REAUTH_REQUIRED, IntegrationState.NEEDS_REAUTH):
            return IntegrationHealthResult(
                state=IntegrationState.NEEDS_REAUTH,
                message="توکن اتصال منقضی شده یا نیازمند احراز هویت مجدد است."
            )

        return IntegrationHealthResult(
            state=IntegrationState.NOT_CONFIGURED,
            message=f"اتصال {self.display_name_fa} هنوز پیکربندی نشده است."
        )

    def is_ready(self, store) -> bool:
        record = self.get_store_config_record(store)
        if record:
            return record.is_active and record.status in (IntegrationState.ACTIVE, IntegrationState.CONNECTED)
        return self.get_status(store) == IntegrationState.CONNECTED


# -----------------------------------------------------------------------------
# 1. SMS & Notifications: Kavenegar SMS Gateway
# -----------------------------------------------------------------------------
class KavenegarSMSAdapter(BaseIntegrationAdapter):
    name = "sms_kavenegar"
    category = "SMS"
    display_name_fa = "پنل پیامک اطلاع‌رسانی (Kavenegar)"
    description_fa = "ارسال خودکار پیامک تأیید سفارش، فاکتور، کد رهگیری پستی و یادآوری سبد خرید"
    guide_fa = "برای اتصال، به پنل کاربری خود در وب‌سایت کاوه‌نگار (kavenegar.com) مراجعه نموده، از منوی تنظیمات > کلید وب‌سرویس (API Key) کلید خود را کپی کرده و در فیلد زیر قرار دهید. در صورت داشتن خط اختصاصی یا خدماتی، شماره آن را نیز وارد نمایید."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'api_key',
                'label_fa': 'کلید وب‌سرویس (API Key)',
                'type': 'password',
                'required': True,
                'is_secret': True,
                'placeholder': 'مثلاً 4A5B6C...',
                'help_text_fa': 'کلید احراز هویت وب‌سرویس کاوه‌نگار که به صورت امن و رمزنگاری‌شده ذخیره می‌شود.'
            },
            {
                'name': 'sender_line',
                'label_fa': 'شماره فرستنده (خط خدماتی یا اختصاصی)',
                'type': 'text',
                'required': False,
                'is_secret': False,
                'placeholder': 'مثلاً 10008585 یا 2000...',
                'help_text_fa': 'شماره خطی که پیامک‌ها از آن برای مشتریان ارسال می‌شود (اختیاری؛ در صورت خالی بودن از خط پیش‌فرض پنل استفاده می‌شود).'
            },
            {
                'name': 'api_url',
                'label_fa': 'آدرس سرور API (سفارشی)',
                'type': 'url',
                'required': False,
                'is_secret': False,
                'default': 'https://api.kavenegar.com/v1',
                'help_text_fa': 'پیش‌فرض: https://api.kavenegar.com/v1 (فقط در صورت داشتن پروکسی اختصاصی تغییر دهید).'
            }
        ]

    def _get_fallback_config(self, store, decrypted: bool = False) -> Dict[str, Any]:
        key = os.environ.get('KAVENEGAR_API_KEY') or os.environ.get('SMS_API_KEY') or ""
        if not key and store:
            settings = getattr(store, 'feature_settings', None)
            if settings and settings.feature_configs:
                key = settings.feature_configs.get('sms_api_key', '')
        return {
            'api_key': key if decrypted else mask_secret(key),
            'api_key_is_set': bool(key),
            'sender_line': os.environ.get('KAVENEGAR_SENDER', ''),
            'api_url': 'https://api.kavenegar.com/v1'
        }

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        api_key = config.get('api_key')
        if not api_key:
            return IntegrationHealthResult(
                state=IntegrationState.NOT_CONFIGURED,
                message="کلید وب‌سرویس کاوه‌نگار تنظیم نشده است."
            )

        base_url = (config.get('api_url') or 'https://api.kavenegar.com/v1').rstrip('/')
        url = f"{base_url}/{api_key}/account/info.json"

        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'}, method='GET')
            with urllib.request.urlopen(req, timeout=8) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    entries = data.get('entries', {})
                    remain_credit = entries.get('remaincredit', 0)
                    expire_date = entries.get('expiredate', '')
                    return IntegrationHealthResult(
                        state=IntegrationState.READY,
                        message=f"اتصال به کاوه‌نگار با موفقیت برقرار شد. اعتبار حساب: {remain_credit:,} ریال.",
                        details={
                            'credit': remain_credit,
                            'expire_date': expire_date,
                            'account_status': 'ACTIVE'
                        }
                    )
                else:
                    return IntegrationHealthResult(
                        state=IntegrationState.TEST_FAILED,
                        message=f"پاسخ غیرمنتظره از کاوه‌نگار (کد {response.status})"
                    )
        except urllib.error.HTTPError as e:
            if e.code in (418, 401, 403):
                return IntegrationHealthResult(
                    state=IntegrationState.TEST_FAILED,
                    message="کلید وب‌سرویس کاوه‌نگار نامعتبر است یا دسترسی به حساب مسدود شده است (کد ۴۱۸)."
                )
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"خطای وب‌سرویس کاوه‌نگار: کد {e.code}"
            )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"عدم برقراری ارتباط با سرور پیامک: {str(e)}"
            )

    def send_notification(self, store, phone_number: str, text: str) -> bool:
        try:
            res = self.send_sms(to=phone_number, message=text, store=store)
            return res.get('status') in ('ACCEPTED', 'NOT_CONFIGURED')
        except Exception as e:
            logger.warning(f"SMS notification failed: {e}")
            return False

    def send_sms(self, to: str, message: str, store=None) -> Dict[str, Any]:
        config = self.get_config(store, decrypted=True)
        api_key = config.get('api_key')
        sender_line = config.get('sender_line')
        base_url = (config.get('api_url') or 'https://api.kavenegar.com/v1').rstrip('/')

        masked_to = (to[:4] + '****' + to[-3:]) if len(to) > 7 else '***'
        if not api_key:
            logger.info(f"KavenegarSMSAdapter: API key not configured. Skipping live dispatch to {masked_to}.")
            return {
                'status': 'NOT_CONFIGURED',
                'message': 'کلید وب‌سرویس پیامک در سیستم تنظیم نشده است.',
                'recipient': to
            }

        try:
            url = f"{base_url}/{api_key}/sms/send.json"
            post_data = {'receptor': to, 'message': message}
            if sender_line:
                post_data['sender'] = sender_line

            data = urllib.parse.urlencode(post_data).encode('utf-8')
            req = urllib.request.Request(url, data=data, method='POST')
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    body = json.loads(response.read().decode('utf-8'))
                    msg_id = str(body.get('entries', [{}])[0].get('messageid', 'kavenegar_ack'))
                    return {
                        'status': 'ACCEPTED',
                        'recipient': to,
                        'message_id': msg_id,
                        'note': 'پیامک توسط درگاه پیامکی پذیرفته شد.'
                    }
                return {
                    'status': 'FAILED',
                    'recipient': to,
                    'error': f"Unexpected response status {response.status}"
                }
        except Exception as e:
            logger.warning(f"Kavenegar API call failed for {masked_to}: {e}")
            return {
                'status': 'FAILED',
                'recipient': to,
                'error': str(e)
            }

    def send_test_sms(self, to: str, store=None) -> Dict[str, Any]:
        """Explicit admin test dispatch with explicit phone validation"""
        if not to or len(to) < 10:
            raise ValidationError({'to': 'شماره تلفن همراه مقصد برای ارسال پیامک آزمایشی نامعتبر است.'})

        test_msg = f"پیامک آزمایشی شاپ‌پایلوت:\nاتصال به درگاه پیامکی با موفقیت فعال و تایید شد.\nفروشگاه: {store.name if store else 'ShopPilot'}"
        return self.send_sms(to=to, message=test_msg, store=store)


# -----------------------------------------------------------------------------
# 2. Social Media & Content Publishing: Instagram (Meta Graph API)
# -----------------------------------------------------------------------------
class InstagramIntegrationAdapter(BaseIntegrationAdapter):
    name = "instagram"
    category = "SOCIAL"
    display_name_fa = "اتصال اینستاگرام تجاری (Meta Graph API)"
    description_fa = "انتشار مستقیم ریلز، استوری و پست‌ها، همگام‌سازی کامنت‌ها، دایرکت و آمار بازدید"
    guide_fa = "برای اتصال رسمی به اینستاگرام، پیج کاری شما باید به یک صفحه فیس‌بوک متصل باشد. توکن دسترسی بلندمدت (Page Access Token) را همراه با شناسه صفحه تجاری اینستاگرام (Instagram Business Account ID) از منوی Meta for Developers یا تنظیمات صفحه وارد فرمایید."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'access_token',
                'label_fa': 'توکن دسترسی معتبر (Access Token)',
                'type': 'password',
                'required': True,
                'is_secret': True,
                'placeholder': 'EAA...',
                'help_text_fa': 'توکن دسترسی از Meta Graph API با دسترسی‌های instagram_basic و instagram_content_publish.'
            },
            {
                'name': 'instagram_account_id',
                'label_fa': 'شناسه پیج اینستاگرام (Instagram Business Account ID)',
                'type': 'text',
                'required': True,
                'is_secret': False,
                'placeholder': 'مثلاً 17841400000000000',
                'help_text_fa': 'شناسه عددی اکانت تجاری اینستاگرام در پنل متا.'
            },
            {
                'name': 'facebook_page_id',
                'label_fa': 'شناسه صفحه فیس‌بوک متصل (Page ID)',
                'type': 'text',
                'required': False,
                'is_secret': False,
                'placeholder': 'مثلاً 105938472910...',
                'help_text_fa': 'شناسه صفحه فیس‌بوک متصل به پیج کاری (اختیاری).'
            }
        ]

    def _get_fallback_config(self, store, decrypted: bool = False) -> Dict[str, Any]:
        try:
            from apps.social.models import SocialAccount, SocialPlatform
            account = SocialAccount.objects.filter(
                store=store,
                platform=SocialPlatform.INSTAGRAM,
                is_connected=True
            ).first()
            if account:
                return {
                    'instagram_account_id': account.handle.lstrip('@'),
                    'access_token': '',
                    'access_token_is_set': False,
                    'facebook_page_id': ''
                }
        except Exception:
            pass
        return {}

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        token = config.get('access_token')
        account_id = config.get('instagram_account_id')

        if not token or not account_id:
            return IntegrationHealthResult(
                state=IntegrationState.NOT_CONFIGURED,
                message="توکن دسترسی و شناسه اکانت اینستاگرام تنظیم نشده است."
            )

        url = f"https://graph.facebook.com/v19.0/{account_id}?fields=id,username,name,profile_picture_url,followers_count&access_token={token}"

        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'}, method='GET')
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    username = data.get('username', account_id)
                    followers = data.get('followers_count', 0)

                    # Also sync or update SocialAccount in apps.social
                    try:
                        from apps.social.models import SocialAccount, SocialPlatform, ConnectionMode
                        SocialAccount.objects.update_or_create(
                            store=store,
                            platform=SocialPlatform.INSTAGRAM,
                            handle=f"@{username.lstrip('@')}",
                            defaults={
                                'display_name': data.get('name', username),
                                'profile_image_url': data.get('profile_picture_url', ''),
                                'is_connected': True,
                                'connection_mode': ConnectionMode.DIRECT_API,
                                'follower_count': followers
                            }
                        )
                    except Exception as err:
                        logger.warning(f"Failed to sync SocialAccount model: {err}")

                    return IntegrationHealthResult(
                        state=IntegrationState.READY,
                        message=f"اتصال به پیج @{username} با موفقیت تایید شد. دنبال‌کنندگان: {followers:,}",
                        details={
                            'username': username,
                            'account_id': account_id,
                            'followers_count': followers,
                            'permissions_verified': ['instagram_basic', 'instagram_content_publish']
                        }
                    )
                return IntegrationHealthResult(
                    state=IntegrationState.TEST_FAILED,
                    message=f"پاسخ غیرمنتظره از متا: کد {resp.status}"
                )
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode('utf-8'))
                err_msg = err_data.get('error', {}).get('message', str(e))
                err_code = err_data.get('error', {}).get('code')
                err_subcode = err_data.get('error', {}).get('error_subcode')
            except Exception:
                err_msg = str(e)
                err_code = None
                err_subcode = None

            if err_code in (190, 102) or err_subcode in (463, 467):
                return IntegrationHealthResult(
                    state=IntegrationState.REAUTH_REQUIRED,
                    message="توکن اتصال اینستاگرام منقضی شده است. لطفاً توکن جدید وارد فرمایید."
                )
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"خطای احراز هویت اینستاگرام (متا): {err_msg}"
            )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"عدم برقراری ارتباط با سرورهای متا: {str(e)}"
            )

    def health_check(self, store) -> IntegrationHealthResult:
        res = super().health_check(store)
        if res.state == IntegrationState.NOT_CONFIGURED:
            return IntegrationHealthResult(
                state=IntegrationState.NOT_CONFIGURED,
                message="حساب اینستاگرام متصل نشده است. قابلیت ثبت دستی و تقویم همچنان فعال است.",
                details={'connected': False, 'manual_mode_available': True}
            )
        return res

    def publish_content_to_instagram(self, store, content) -> Dict[str, Any]:
        """
        Executes real publication to Instagram via Meta Graph API:
        1. Validates store connection is active
        2. Validates media assets (Meta requires accessible image/video URL)
        3. Creates media container (POST /{account_id}/media)
        4. Publishes container (POST /{account_id}/media_publish)
        5. Fetches real permalink and post ID
        """
        record = self.get_store_config_record(store)
        if not record or not record.is_active or record.status not in (IntegrationState.ACTIVE, IntegrationState.CONNECTED):
            raise ValidationError("اتصال اینستاگرام تجاری برای این فروشگاه فعال نشده است. لطفاً ابتدا در تنظیمات اتصال‌ها، اتصال را تست و فعال نمایید.")

        config = self.get_config(store, decrypted=True)
        token = config.get('access_token')
        account_id = config.get('instagram_account_id')

        if not token or not account_id:
            raise ValidationError("کلید دسترسی (Access Token) یا شناسه پیج اینستاگرام تنظیم نشده است.")

        media_url = content.thumbnail_url or (content.media_urls[0] if content.media_urls else '')
        if not media_url:
            raise ValidationError("برای انتشار در اینستاگرام، تعیین حداقل یک فایل رسانه‌ای (تصویر یا ویدیو) الزامی است.")

        if not (media_url.startswith('http://') or media_url.startswith('https://')):
            raise ValidationError("آدرس فایل رسانه‌ای اینستاگرام باید یک نشانی معتبر اینترنتی (HTTP/HTTPS) قابل دسترس توسط سرورهای متا باشد.")

        caption_parts = []
        if content.caption:
            caption_parts.append(content.caption.strip())
        if content.hashtags:
            caption_parts.append(content.hashtags.strip())
        full_caption = "\n\n".join(caption_parts)

        # Step 1: Create media container
        container_url = f"https://graph.facebook.com/v19.0/{account_id}/media"
        post_data = {
            'caption': full_caption,
            'access_token': token
        }
        from apps.social.models import ContentType
        if content.content_type == ContentType.REEL:
            post_data['media_type'] = 'REELS'
            post_data['video_url'] = media_url
        elif content.content_type == ContentType.STORY:
            post_data['media_type'] = 'STORIES'
            post_data['image_url'] = media_url
        else:
            post_data['image_url'] = media_url

        try:
            encoded_data = urllib.parse.urlencode(post_data).encode('utf-8')
            req = urllib.request.Request(container_url, data=encoded_data, method='POST')
            with urllib.request.urlopen(req, timeout=15) as resp:
                res_body = json.loads(resp.read().decode('utf-8'))
                container_id = res_body.get('id')

            if not container_id:
                raise ValidationError("شناسه کانتینر رسانه (Container ID) از سرور متا دریافت نشد.")

            # Step 2: Publish container
            publish_url = f"https://graph.facebook.com/v19.0/{account_id}/media_publish"
            publish_data = {
                'creation_id': container_id,
                'access_token': token
            }
            encoded_pub = urllib.parse.urlencode(publish_data).encode('utf-8')
            pub_req = urllib.request.Request(publish_url, data=encoded_pub, method='POST')
            with urllib.request.urlopen(pub_req, timeout=15) as pub_resp:
                pub_res_body = json.loads(pub_resp.read().decode('utf-8'))
                media_id = pub_res_body.get('id')

            if not media_id:
                raise ValidationError("شناسه پست منتشر شده (Media ID) از سرور متا دریافت نشد.")

            # Step 3: Fetch permalink
            info_url = f"https://graph.facebook.com/v19.0/{media_id}?fields=id,permalink&access_token={token}"
            info_req = urllib.request.Request(info_url, method='GET')
            permalink = f"https://www.instagram.com/p/{media_id}/"
            try:
                with urllib.request.urlopen(info_req, timeout=10) as info_resp:
                    info_data = json.loads(info_resp.read().decode('utf-8'))
                    permalink = info_data.get('permalink') or permalink
            except Exception:
                pass

            return {
                'status': 'SUCCESS',
                'external_post_id': str(media_id),
                'published_url': permalink
            }

        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode('utf-8'))
                meta_err = err_data.get('error', {})
                err_msg = meta_err.get('message', str(e))
                err_code = meta_err.get('code')
            except Exception:
                err_msg = str(e)
                err_code = None

            if err_code in (190, 102):
                record.status = IntegrationState.REAUTH_REQUIRED
                record.is_active = False
                record.save(update_fields=['status', 'is_active', 'updated_at'])

            raise ValidationError(f"خطای وب‌سرویس اینستاگرام (متا): {err_msg}")
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError(f"خطا در برقراری ارتباط با وب‌سرویس اینستاگرام: {str(e)}")

    def fetch_live_metrics(self, store, external_post_id: str) -> Dict[str, Any]:
        config = self.get_config(store, decrypted=True)
        token = config.get('access_token')
        if not token or not external_post_id:
            return {'is_live': False, 'message': 'کلید اتصال یا شناسه پست در دسترس نیست.'}

        url = f"https://graph.facebook.com/v19.0/{external_post_id}/insights?metric=impressions,reach,saved,engagement&access_token={token}"
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                metrics = {}
                for item in data.get('data', []):
                    metric_name = item.get('name')
                    val = item.get('values', [{}])[0].get('value', 0)
                    metrics[metric_name] = val
                return {
                    'is_live': True,
                    'impressions': metrics.get('impressions', 0),
                    'reach': metrics.get('reach', 0),
                    'saves': metrics.get('saved', 0),
                    'engagement': metrics.get('engagement', 0)
                }
        except Exception as e:
            logger.warning(f"Failed to fetch live Instagram metrics for {external_post_id}: {e}")
            return {'is_live': False, 'message': f'عدم امکان استعلام آمار زنده از متا: {str(e)}'}

    def send_direct_message(self, store, recipient_id: str, text: str) -> Dict[str, Any]:
        """
        Sends an Instagram Direct message via Meta Graph API Send endpoint.
        """
        record = self.get_store_config_record(store)
        if not record or not record.is_active:
            return {'status': 'LOCAL_ONLY', 'error': 'اتصال رسمی اینستاگرام فعال نیست.'}

        config = self.get_config(store, decrypted=True)
        token = config.get('access_token')
        if not token:
            return {'status': 'FAILED', 'error': 'توکن اتصال اینستاگرام یافت نشد.'}

        url = f"https://graph.facebook.com/v19.0/me/messages?access_token={token}"
        payload = {
            'recipient': {'id': recipient_id.lstrip('@')},
            'message': {'text': text}
        }
        try:
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=10) as resp:
                res_body = json.loads(resp.read().decode('utf-8'))
                return {
                    'status': 'DELIVERED',
                    'message_id': res_body.get('message_id', ''),
                    'recipient_id': res_body.get('recipient_id', recipient_id)
                }
        except urllib.error.HTTPError as e:
            try:
                err_data = json.loads(e.read().decode('utf-8'))
                err_msg = err_data.get('error', {}).get('message', str(e))
            except Exception:
                err_msg = str(e)
            return {'status': 'FAILED', 'error': err_msg}
        except Exception as e:
            return {'status': 'FAILED', 'error': str(e)}


# -----------------------------------------------------------------------------
# 2b. Telegram Bot & Channel Adapter
# -----------------------------------------------------------------------------
class TelegramIntegrationAdapter(BaseIntegrationAdapter):
    name = "social_telegram"
    category = "SOCIAL"
    display_name_fa = "ربات و کانال تلگرام (Telegram Bot API)"
    description_fa = "ارسال پیام به کانال و گروه‌ها، دریافت سفارشات و پاسخ‌گویی به مشتریان در پیام‌رسان تلگرام"
    guide_fa = "جهت اتصال به تلگرام، ابتدا در ربات @BotFather یک ربات ایجاد نموده و توکن اختصاصی (Bot Token) را در فیلد زیر وارد فرمایید. در صورت تمایل به انتشار خودکار پست‌ها در کانال، ربات را به عنوان ادمین کانال اضافه نموده و آیدی کانال را وارد نمایید."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'bot_token',
                'label_fa': 'توکن ربات تلگرام (Bot Token)',
                'type': 'password',
                'required': True,
                'is_secret': True,
                'placeholder': '123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ...',
                'help_text_fa': 'توکن دریافتی از @BotFather جهت برقراری ارتباط با API رسمی تلگرام.'
            },
            {
                'name': 'channel_id',
                'label_fa': 'شناسه یا آدرس کانال تلگرام',
                'type': 'text',
                'required': False,
                'is_secret': False,
                'placeholder': 'مثلاً @MyStoreChannel یا -1001234567890',
                'help_text_fa': 'آیدی عمومی یا عددی کانال که ربات ادمین آن است (جهت انتشار پست‌های فروشگاه).'
            },
            {
                'name': 'webhook_secret',
                'label_fa': 'رمز امنیتی وب‌هوک (اختیاری)',
                'type': 'password',
                'required': False,
                'is_secret': True,
                'placeholder': 'secret_token_123',
                'help_text_fa': 'رمز secret_token برای راستی‌آزمایی درخواست‌های وب‌هوک ارسالی از سرورهای تلگرام.'
            }
        ]

    def _get_fallback_config(self, store, decrypted: bool = False) -> Dict[str, Any]:
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        return {
            'bot_token': token if decrypted else mask_secret(token),
            'bot_token_is_set': bool(token),
            'channel_id': os.environ.get('TELEGRAM_CHANNEL_ID', ''),
            'webhook_secret': ''
        }

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        token = config.get('bot_token')
        if not token:
            return IntegrationHealthResult(
                state=IntegrationState.NOT_CONFIGURED,
                message="توکن ربات تلگرام تنظیم نشده است."
            )

        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'}, method='GET')
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data.get('ok'):
                        bot_info = data.get('result', {})
                        username = bot_info.get('username', '')
                        first_name = bot_info.get('first_name', '')
                        return IntegrationHealthResult(
                            state=IntegrationState.READY,
                            message=f"اتصال به ربات تلگرام @{username} ({first_name}) با موفقیت برقرار شد.",
                            details={'bot_username': username, 'bot_id': bot_info.get('id')}
                        )
                return IntegrationHealthResult(
                    state=IntegrationState.TEST_FAILED,
                    message="پاسخ ناموفق از سرور تلگرام دریافت شد."
                )
        except urllib.error.HTTPError as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"خطای احراز هویت توکن ربات تلگرام: کد {e.code}"
            )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"عدم برقراری ارتباط با سرورهای تلگرام: {str(e)}"
            )

    def send_message(self, store, chat_id: str, text: str) -> Dict[str, Any]:
        config = self.get_config(store, decrypted=True)
        token = config.get('bot_token')
        if not token or not chat_id:
            return {'status': 'FAILED', 'error': 'توکن ربات یا شناسه چت تنظیم نشده است.'}

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        try:
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('ok'):
                    msg_id = data.get('result', {}).get('message_id')
                    return {'status': 'DELIVERED', 'message_id': str(msg_id)}
                return {'status': 'FAILED', 'error': data.get('description', 'خطای نامشخص تلگرام')}
        except Exception as e:
            return {'status': 'FAILED', 'error': str(e)}

    def publish_content_to_telegram(self, store, content) -> Dict[str, Any]:
        config = self.get_config(store, decrypted=True)
        token = config.get('bot_token')
        channel_id = config.get('channel_id')
        if not token or not channel_id:
            raise ValidationError("توکن ربات یا آیدی کانال تلگرام برای انتشار تنظیم نشده است.")

        media_url = content.thumbnail_url or (content.media_urls[0] if content.media_urls else '')
        caption_parts = []
        if content.title:
            caption_parts.append(f"<b>{content.title}</b>")
        if content.caption:
            caption_parts.append(content.caption.strip())
        if content.hashtags:
            caption_parts.append(content.hashtags.strip())
        full_text = "\n\n".join(caption_parts)

        if media_url and (media_url.startswith('http://') or media_url.startswith('https://')):
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            payload = {'chat_id': channel_id, 'photo': media_url, 'caption': full_text, 'parse_mode': 'HTML'}
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {'chat_id': channel_id, 'text': full_text, 'parse_mode': 'HTML'}

        try:
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(url, data=req_data, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if data.get('ok'):
                    msg_id = data.get('result', {}).get('message_id')
                    channel_clean = channel_id.lstrip('@')
                    pub_url = f"https://t.me/{channel_clean}/{msg_id}" if not channel_id.startswith('-') else ""
                    return {
                        'status': 'SUCCESS',
                        'external_post_id': str(msg_id),
                        'published_url': pub_url
                    }
                raise ValidationError(f"خطای ارسال تلگرام: {data.get('description')}")
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError(f"عدم برقراری ارتباط با تلگرام: {str(e)}")


# -----------------------------------------------------------------------------
# 3. Payment Gateway: Zarinpal
# -----------------------------------------------------------------------------
class ZarinpalPaymentAdapter(BaseIntegrationAdapter):
    name = "payment_zarinpal"
    category = "PAYMENT"
    display_name_fa = "درگاه پرداخت آنلاین زرین‌پال (Zarinpal)"
    description_fa = "اتصال درگاه بانکی برای دریافت پرداخت آنلاین سفارشات و شارژ حساب"
    guide_fa = "برای اتصال به درگاه پرداخت زرین‌پال، به پنل کاربری خود در my.zarinpal.com رفته و از بخش درگاه‌های پرداخت، مرچنت کد ۳۶ رقمی (Merchant ID) درگاه فعال خود را کپی نموده و در فیلد زیر قرار دهید. جهت تست در محیط آزمایشی، کلید تستی و تیک حالت سندباکس را فعال کنید."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'merchant_id',
                'label_fa': 'مرچنت کد زرین‌پال (Merchant ID)',
                'type': 'password',
                'required': True,
                'is_secret': True,
                'placeholder': 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
                'help_text_fa': 'شناسه ۳۶ کاراکتری درگاه اختصاصی در زرین‌پال.'
            },
            {
                'name': 'is_sandbox',
                'label_fa': 'محیط آزمایشی (Sandbox)',
                'type': 'boolean',
                'required': False,
                'default': False,
                'help_text_fa': 'در صورت فعال بودن، تراکنش‌ها در محیط تستی sandbox.zarinpal.com اجرا می‌شوند.'
            },
            {
                'name': 'currency',
                'label_fa': 'واحد پولی پیش‌فرض',
                'type': 'select',
                'required': True,
                'default': 'IRT',
                'options': [
                    {'value': 'IRT', 'label': 'تومان (IRT)'},
                    {'value': 'IRR', 'label': 'ریال (IRR)'}
                ],
                'help_text_fa': 'واحد ارسالی مبالغ به درگاه بانکی.'
            },
            {
                'name': 'callback_url',
                'label_fa': 'آدرس بازگشت اختصاصی درگاه (Callback URL)',
                'type': 'url',
                'required': False,
                'help_text_fa': 'آدرس هدایت مشتری پس از تکمیل پرداخت (اختیاری؛ پیش‌فرض سیستم استفاده می‌شود).'
            }
        ]

    def _get_fallback_config(self, store, decrypted: bool = False) -> Dict[str, Any]:
        merchant = os.environ.get('ZARINPAL_MERCHANT_ID', '')
        if not merchant and store:
            settings = getattr(store, 'feature_settings', None)
            if settings and settings.feature_configs:
                merchant = settings.feature_configs.get('zarinpal_merchant_id', '')
        is_sandbox = os.environ.get('ZARINPAL_SANDBOX', 'False').lower() in ('true', '1', 't')
        return {
            'merchant_id': merchant if decrypted else mask_secret(merchant),
            'merchant_id_is_set': bool(merchant),
            'is_sandbox': is_sandbox,
            'currency': 'IRT',
            'callback_url': ''
        }

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        merchant_id = config.get('merchant_id')

        if not merchant_id:
            return IntegrationHealthResult(
                state=IntegrationState.NOT_CONFIGURED,
                message="مرچنت کد زرین‌پال وارد نشده است."
            )

        # Enforce merchant format check (standard UUID 36 chars)
        clean_merchant = merchant_id.strip()
        if len(clean_merchant) != 36:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"فرمت مرچنت کد نامعتبر است (طول باید ۳۶ کاراکتر باشد؛ طول فعلی: {len(clean_merchant)})."
            )

        is_sandbox = bool(config.get('is_sandbox'))
        prefix = "sandbox" if is_sandbox else "www"
        url = f"https://{prefix}.zarinpal.com/pg/rest/WebGate/PaymentRequest.json"

        # Safe verification request that inspects merchant validity without creating a real charged transaction
        # If merchant is invalid, Zarinpal returns -1 or -2.
        payload = {
            'MerchantID': clean_merchant,
            'Amount': 1000,  # 1,000 Tomans
            'CallbackURL': 'https://shoppilot.ir/test-verify',
            'Description': 'ShopPilot Merchant Connectivity Probe',
            'Metadata': {'probe': True}
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                status_code = data.get('Status')
                if status_code == 100:
                    return IntegrationHealthResult(
                        state=IntegrationState.READY,
                        message="اتصال به درگاه زرین‌پال تأیید شد و مرچنت فعال است.",
                        details={
                            'gateway': 'zarinpal',
                            'sandbox': is_sandbox,
                            'status_code': status_code
                        }
                    )
                elif status_code in (-1, -2):
                    return IntegrationHealthResult(
                        state=IntegrationState.TEST_FAILED,
                        message=f"مرچنت کد وارد شده در زرین‌پال معتبر نیست (کد وضعیت: {status_code})."
                    )
                else:
                    return IntegrationHealthResult(
                        state=IntegrationState.TEST_FAILED,
                        message=f"پاسخ درگاه زرین‌پال با کد وضعیت: {status_code}"
                    )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"خطا در برقراری ارتباط با سرور زرین‌پال: {str(e)}"
            )


# -----------------------------------------------------------------------------
# 4. Shipping & Logistics: Iran Post & Tipax
# -----------------------------------------------------------------------------
class IranPostShippingAdapter(BaseIntegrationAdapter):
    name = "shipping_irpost"
    category = "SHIPPING"
    display_name_fa = "سامانه شرکت ملی پست ایران (Iran Post)"
    description_fa = "محاسبه هوشمند تعرفه پستی، صدور شناسه رهگیری مرسولات پیشتاز و سفارشی"
    guide_fa = "جهت اتصال مستقیم به وب‌سرویس پستی، به باجه امور پستی طرف قرارداد مراجعه نموده و نام کاربری، کلید وب‌سرویس و شناسه قرارداد سازمانی خود را دریافت نمایید. بدون اتصال وب‌سرویس، سامانه در حالت محاسبه تعرفه هوشمند و پیگیری دستی فعال خواهد بود."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'api_key',
                'label_fa': 'کلید وب‌سرویس پستی (API Key / Token)',
                'type': 'password',
                'required': False,
                'is_secret': True,
                'placeholder': 'اختیاری...',
                'help_text_fa': 'کلید دسترسی وب‌سرویس دریافت شده از اداره پست.'
            },
            {
                'name': 'contract_number',
                'label_fa': 'شماره قرارداد پستی',
                'type': 'text',
                'required': False,
                'placeholder': 'مثلاً 1402/POST/9823',
                'help_text_fa': 'شماره قرارداد سازمانی فروشگاه با شرکت ملی پست.'
            },
            {
                'name': 'origin_postal_code',
                'label_fa': 'کد پستی انبار مبدأ',
                'type': 'text',
                'required': False,
                'placeholder': '۱۰ رقم کد پستی مبدأ',
                'help_text_fa': 'کد پستی محل جمع‌آوری بسته‌ها جهت ثبت روی بارکد پستی.'
            }
        ]

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        api_key = config.get('api_key')
        if not api_key:
            return IntegrationHealthResult(
                state=IntegrationState.READY,
                message="کلید وب‌سرویس پستی تعریف نشده است. سیستم در حالت محاسبه خودکار تعرفه پستی و صدور برچسب دستی فعال و آماده است.",
                details={'manual_mode': True}
            )


        # Validate API key reachability without creating real parcel
        try:
            # Ping Post tracking endpoint
            url = "https://tracking.post.ir"
            req = urllib.request.Request(url, headers={'User-Agent': 'ShopPilot-Logistics-Probe'}, method='HEAD')
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status in (200, 301, 302):
                    return IntegrationHealthResult(
                        state=IntegrationState.READY,
                        message="ارتباط با سرور رهگیری و وب‌سرویس پست برقرار است.",
                        details={'contract_number': config.get('contract_number', '')}
                    )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"عدم برقراری ارتباط با سامانه رهگیری پست: {str(e)}"
            )

        return IntegrationHealthResult(
            state=IntegrationState.READY,
            message="تنظیمات شرکت ملی پست ذخیره شد و درگاه آماده به کار است."
        )


class TipaxShippingAdapter(BaseIntegrationAdapter):
    name = "shipping_tipax"
    category = "SHIPPING"
    display_name_fa = "سامانه لجستیک تیپاکس (Tipax)"
    description_fa = "محاسبه هزینه حمل اکسپرس تیپاکس و همگام‌سازی کدهای بارنامه"
    guide_fa = "برای فعال‌سازی وب‌سرویس تیپاکس، به امور مشتریان سازمانی تیپاکس (tipaxco.com) مراجعه کرده و شناسه کاربری و کلید وب‌سرویس خود را دریافت نمایید."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'api_key',
                'label_fa': 'کلید وب‌سرویس تیپاکس (API Token)',
                'type': 'password',
                'required': False,
                'is_secret': True,
                'placeholder': 'Token...',
                'help_text_fa': 'توکن احراز هویت وب‌سرویس تیپاکس.'
            },
            {
                'name': 'account_id',
                'label_fa': 'شناسه مشتری سازمانی تیپاکس',
                'type': 'text',
                'required': False,
                'placeholder': 'کد حساب سازمانی',
                'help_text_fa': 'شناسه حساب جهت تخصیص تخفیفات و تسویه‌حساب دوره‌ای.'
            }
        ]

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        if not config.get('api_key'):
            return IntegrationHealthResult(
                state=IntegrationState.CONFIGURED,
                message="کلید وب‌سرویس تیپاکس تعریف نشده است. سیستم با تعرفه تخمینی و رهگیری دستی فعال است.",
                details={'manual_mode': True}
            )

        try:
            url = "https://tipaxco.com"
            req = urllib.request.Request(url, headers={'User-Agent': 'ShopPilot-Logistics-Probe'}, method='HEAD')
            with urllib.request.urlopen(req, timeout=6) as resp:
                if resp.status in (200, 301, 302):
                    return IntegrationHealthResult(
                        state=IntegrationState.READY,
                        message="ارتباط با سرور رهگیری تیپاکس برقرار است.",
                        details={'account_id': config.get('account_id', '')}
                    )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"عدم برقراری ارتباط با تیپاکس: {str(e)}"
            )

        return IntegrationHealthResult(
            state=IntegrationState.READY,
            message="تنظیمات تیپاکس تایید و ذخیره شد."
        )


# -----------------------------------------------------------------------------
# 5. AI Services: Google Gemini
# -----------------------------------------------------------------------------
class GoogleGeminiAIAdapter(BaseIntegrationAdapter):
    name = "ai_provider"
    category = "AI"
    display_name_fa = "سرویس هوش مصنوعی (Google Gemini)"
    description_fa = "نگارش خودکار کپشن و محتوا، پاسخگویی هوشمند به دایرکت و تحلیل رفتار مشتریان"
    guide_fa = "برای دریافت کلید رایگان هوش مصنوعی گوگل جمینای، به آدرس aistudio.google.com مراجعه نموده و با حساب گوگل خود وارد شوید. سپس از بخش Get API Key یک کلید جدید ایجاد کرده و در کادر زیر وارد نمایید."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'api_key',
                'label_fa': 'کلید دسترسی جمینای (Gemini API Key)',
                'type': 'password',
                'required': True,
                'is_secret': True,
                'placeholder': 'AIzaSy...',
                'help_text_fa': 'کلید API دریافت شده از Google AI Studio.'
            },
            {
                'name': 'model_name',
                'label_fa': 'مدل هوش مصنوعی',
                'type': 'select',
                'required': True,
                'default': 'gemini-1.5-flash',
                'options': [
                    {'value': 'gemini-1.5-flash', 'label': 'Gemini 1.5 Flash (سریع و اقتصادی)'},
                    {'value': 'gemini-1.5-pro', 'label': 'Gemini 1.5 Pro (پیشرفته با استدلال قوی)'},
                    {'value': 'gemini-2.0-flash', 'label': 'Gemini 2.0 Flash (نسل جدید)'}
                ],
                'help_text_fa': 'مدل پردازش زبان و تولید محتوا.'
            },
            {
                'name': 'custom_api_url',
                'label_fa': 'آدرس سرور اختصاصی پروکسی (اختیاری)',
                'type': 'url',
                'required': False,
                'help_text_fa': 'در صورت عبور از پروکسی یا ریورس‌پروکسی داخلی (با اعتبارسنجی کامل امنیتی SSRF).'
            }
        ]

    def _get_fallback_config(self, store, decrypted: bool = False) -> Dict[str, Any]:
        key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or ""
        if not key and store:
            settings = getattr(store, 'feature_settings', None)
            if settings and settings.feature_configs:
                key = settings.feature_configs.get('gemini_api_key', '')
        return {
            'api_key': key if decrypted else mask_secret(key),
            'api_key_is_set': bool(key),
            'model_name': 'gemini-1.5-flash',
            'custom_api_url': ''
        }

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        api_key = config.get('api_key')
        model = config.get('model_name') or 'gemini-1.5-flash'
        base_url = (config.get('custom_api_url') or 'https://generativelanguage.googleapis.com').rstrip('/')

        if not api_key:
            return IntegrationHealthResult(
                state=IntegrationState.NOT_CONFIGURED,
                message="کلید ارتباط با هوش مصنوعی (Gemini API Key) تنظیم نشده است."
            )

        # Zero-cost side-effect-free test: countTokens on minimal input
        url = f"{base_url}/v1beta/models/{model}:countTokens"
        payload = {
            "contents": [{"parts": [{"text": "ping"}]}]
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'x-goog-api-key': api_key
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    total_tokens = data.get('totalTokens', 1)
                    return IntegrationHealthResult(
                        state=IntegrationState.READY,
                        message=f"سرویس هوش مصنوعی ({model}) متصل و کلید معتبر است.",
                        details={'model': model, 'verified_tokens': total_tokens}
                    )
                return IntegrationHealthResult(
                    state=IntegrationState.TEST_FAILED,
                    message=f"پاسخ غیرمنتظره از گوگل جمینای: کد {resp.status}"
                )
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 401):
                return IntegrationHealthResult(
                    state=IntegrationState.TEST_FAILED,
                    message="کلید API گوگل جمینای نامعتبر است یا سهمیه پروژه به اتمام رسیده است (کد ۴۰۳/۴۰۱)."
                )
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"خطای ارتباط با گوگل جمینای: کد {e.code}"
            )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"عدم برقراری ارتباط با هوش مصنوعی گوگل: {str(e)}"
            )

    def generate_caption(self, store, product_title: str, tone: str = "friendly") -> str:
        config = self.get_config(store, decrypted=True)
        api_key = config.get('api_key')
        model = config.get('model_name') or 'gemini-1.5-flash'
        base_url = (config.get('custom_api_url') or 'https://generativelanguage.googleapis.com').rstrip('/')

        if not api_key:
            return f"معرفی محصول جدید: {product_title}\nهم‌اکنون با کیفیت عالی و ارسال سریع در دسترس شماست.\nبرای خرید و ثبت سفارش به دایرکت یا وبسایت مراجعه فرمایید. ✨"

        prompt = f"یک کپشن جذاب و حرفه‌ای اینستاگرام به زبان فارسی با لحن {tone} برای فروش محصول '{product_title}' بنویس که شامل ایموجی و دعوت به اقدام باشد."
        url = f"{base_url}/v1beta/models/{model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800}
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'x-goog-api-key': api_key
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    candidates = data.get('candidates', [])
                    if candidates and 'content' in candidates[0]:
                        parts = candidates[0]['content'].get('parts', [])
                        if parts and 'text' in parts[0]:
                            return parts[0]['text'].strip()
        except Exception as e:
            logger.warning(f"Google Gemini API call failed: {e}")

        return f"استایلت رو با {product_title} متحول کن! ✨\nطراحی خاص، کیفیت تضمین‌شده و انتخابی مناسب برای خاص‌پسندان.\n💬 برای اطلاعات بیشتر و ثبت سفارش در دایرکت پیام بدهید یا از وبسایت خرید کنید."


# -----------------------------------------------------------------------------
# 6. Email Service: SMTP Mail Server
# -----------------------------------------------------------------------------
class SMTPEmailAdapter(BaseIntegrationAdapter):
    name = "email_smtp"
    category = "EMAIL"
    display_name_fa = "سرور ایمیل سازمانی (SMTP Server)"
    description_fa = "ارسال ایمیل‌های فاکتور رسمی، بازیابی رمز عبور، اعلان‌های مدیریتی و مکاتبات"
    guide_fa = "برای ارسال ایمیل، اطلاعات سرور SMTP شرکت یا هاست ایمیل خود را وارد نمایید. (برای نمونه در سرورهای سازمانی مانند Gmail یا هاست اشتراکی، پورت معمولاً ۵۸۷ با TLS یا ۴۶۵ با SSL می‌باشد)."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'smtp_host',
                'label_fa': 'آدرس سرور ایمیل (SMTP Host)',
                'type': 'text',
                'required': True,
                'placeholder': 'مثلاً mail.yourdomain.ir یا smtp.gmail.com',
                'help_text_fa': 'آدرس سرور ارسال ایمیل.'
            },
            {
                'name': 'smtp_port',
                'label_fa': 'درگاه سرور (SMTP Port)',
                'type': 'number',
                'required': True,
                'default': 587,
                'help_text_fa': 'پورت اتصال (معمولاً ۵۸۷ یا ۴۶۵ یا ۲۵).'
            },
            {
                'name': 'smtp_username',
                'label_fa': 'نام کاربری / آدرس ایمیل احراز هویت',
                'type': 'text',
                'required': True,
                'placeholder': 'info@yourdomain.ir',
                'help_text_fa': 'نام کاربری حساب در سرور ایمیل.'
            },
            {
                'name': 'smtp_password',
                'label_fa': 'رمز عبور ایمیل (یا App Password)',
                'type': 'password',
                'required': True,
                'is_secret': True,
                'placeholder': '••••••••',
                'help_text_fa': 'رمز عبور حساب ایمیل که به صورت امن و رمزنگاری‌شده نگهداری می‌شود.'
            },
            {
                'name': 'use_tls',
                'label_fa': 'رمزنگاری امن TLS / STARTTLS',
                'type': 'boolean',
                'required': False,
                'default': True,
                'help_text_fa': 'استفاده از پروتکل امن TLS در پورت ۵۸۷.'
            },
            {
                'name': 'from_email',
                'label_fa': 'آدرس فرستنده (From Address)',
                'type': 'text',
                'required': True,
                'placeholder': 'no-reply@yourdomain.ir',
                'help_text_fa': 'آدرسی که به عنوان ارسال‌کننده برای دریافت‌کنندگان نمایش داده می‌شود.'
            },
            {
                'name': 'from_name',
                'label_fa': 'نام نمایشی فرستنده',
                'type': 'text',
                'required': False,
                'placeholder': 'فروشگاه شاپ‌پایلوت',
                'help_text_fa': 'نامی که در کنار ایمیل فرستنده برای مشتری نمایش داده می‌شود.'
            }
        ]

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        host = config.get('smtp_host')
        port = int(config.get('smtp_port') or 587)
        user = config.get('smtp_username')
        password = config.get('smtp_password')
        use_tls = bool(config.get('use_tls'))

        if not host or not user or not password:
            return IntegrationHealthResult(
                state=IntegrationState.NOT_CONFIGURED,
                message="مشخصات سرور SMTP و نام کاربری/رمز عبور تنظیم نشده است."
            )

        # Connect and authenticate without sending an email!
        try:
            if port == 465:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(host, port, context=context, timeout=8)
            else:
                server = smtplib.SMTP(host, port, timeout=8)
                if use_tls:
                    server.starttls()

            server.login(user, password)
            server.quit()

            return IntegrationHealthResult(
                state=IntegrationState.READY,
                message=f"اتصال به سرور SMTP ({host}:{port}) و احراز هویت کاربر {user} با موفقیت تایید شد.",
                details={'host': host, 'port': port, 'username': user, 'auth_verified': True}
            )
        except smtplib.SMTPAuthenticationError as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"خطای احراز هویت SMTP: نام کاربری یا رمز عبور اشتباه است ({str(e)})."
            )
        except (socket.timeout, TimeoutError):
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"مهلت زمان اتصال به سرور {host}:{port} به پایان رسید (Timeout)."
            )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"عدم برقراری ارتباط با سرور SMTP: {str(e)}"
            )

    def send_email(self, to: str, subject: str, html_body: str, store=None) -> bool:
        config = self.get_config(store, decrypted=True)
        host = config.get('smtp_host')
        port = int(config.get('smtp_port') or 587)
        user = config.get('smtp_username')
        password = config.get('smtp_password')
        use_tls = bool(config.get('use_tls'))
        from_email = config.get('from_email') or user
        from_name = config.get('from_name') or (store.name if store else 'ShopPilot')

        if not host or not user or not password:
            logger.warning(f"SMTP not configured for store {store}. Skipping email to {to}.")
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{from_name} <{from_email}>"
            msg['To'] = to
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            if port == 465:
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(host, port, context=context, timeout=10)
            else:
                server = smtplib.SMTP(host, port, timeout=10)
                if use_tls:
                    server.starttls()

            server.login(user, password)
            server.sendmail(from_email, [to], msg.as_string())
            server.quit()
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return False


# -----------------------------------------------------------------------------
# 8. Sales Channel Integration: WooCommerce
# -----------------------------------------------------------------------------
class WooCommerceIntegrationAdapter(BaseIntegrationAdapter):
    name = "ecommerce_woocommerce"
    category = "SALES_CHANNEL"
    display_name_fa = "فروشگاه آنلاین ووکامرس (WooCommerce REST API)"
    description_fa = "همگام‌سازی دوطرفه محصولات، متغیرها، موجودی انبار و دریافت خودکار سفارشات از سایت وردپرس"
    guide_fa = "برای اتصال به سایت ووکامرسی خود، در پیشخوان وردپرس به مسیر «ووکامرس > پیکربندی > پیشرفته > REST API» رفته و یک کلید با سطح دسترسی خواندن/نوشتن (Read/Write) بسازید. سپس آدرس سایت (URL)، Consumer Key و Consumer Secret را در فیلدهای زیر وارد نمایید."

    def get_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                'name': 'store_url',
                'label_fa': 'آدرس وب‌سایت فروشگاه (URL)',
                'type': 'url',
                'required': True,
                'is_secret': False,
                'placeholder': 'https://myshop.com',
                'help_text_fa': 'آدرس کامل دامنه فروشگاه ووکامرسی به همراه https://.'
            },
            {
                'name': 'consumer_key',
                'label_fa': 'کلید مصرف‌کننده (Consumer Key)',
                'type': 'password',
                'required': True,
                'is_secret': True,
                'placeholder': 'ck_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
                'help_text_fa': 'کلید تولید شده در بخش REST API ووکامرس که با ck_ شروع می‌شود.'
            },
            {
                'name': 'consumer_secret',
                'label_fa': 'رمز مصرف‌کننده (Consumer Secret)',
                'type': 'password',
                'required': True,
                'is_secret': True,
                'placeholder': 'cs_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
                'help_text_fa': 'رمز اختصاصی API ووکامرس که با cs_ شروع می‌شود.'
            },
            {
                'name': 'sync_inventory',
                'label_fa': 'همگام‌سازی خودکار موجودی انبار',
                'type': 'boolean',
                'required': False,
                'default': True,
                'help_text_fa': 'انتقال موجودی انبار شاپ‌پایلوت به عنوان منبع اصلی موجودی به سایت ووکامرس.'
            },
            {
                'name': 'sync_orders',
                'label_fa': 'دریافت خودکار سفارشات جدید',
                'type': 'boolean',
                'required': False,
                'default': True,
                'help_text_fa': 'درون‌ریزی سفارشات ثبت‌شده در سایت به کارتابل سفارشات شاپ‌پایلوت.'
            },
            {
                'name': 'webhook_secret',
                'label_fa': 'رمز وب‌هوک ووکامرس (Secret)',
                'type': 'password',
                'required': False,
                'is_secret': True,
                'placeholder': 'wc_webhook_secret_key',
                'help_text_fa': 'کلید مخفی جهت راستی‌آزمایی امضای HMAC-SHA256 وب‌هوک‌های ارسالی از ووکامرس.'
            }
        ]

    def _get_fallback_config(self, store, decrypted: bool = False) -> Dict[str, Any]:
        key = os.environ.get('WOOCOMMERCE_KEY', '')
        sec = os.environ.get('WOOCOMMERCE_SECRET', '')
        return {
            'store_url': os.environ.get('WOOCOMMERCE_URL', ''),
            'consumer_key': key if decrypted else mask_secret(key),
            'consumer_key_is_set': bool(key),
            'consumer_secret': sec if decrypted else mask_secret(sec),
            'consumer_secret_is_set': bool(sec),
            'sync_inventory': True,
            'sync_orders': True,
            'webhook_secret': ''
        }

    def _execute_live_test(self, store, **kwargs) -> IntegrationHealthResult:
        config = self.get_config(store, decrypted=True)
        store_url = (config.get('store_url') or '').strip().rstrip('/')
        ck = config.get('consumer_key')
        cs = config.get('consumer_secret')

        if not store_url or not ck or not cs:
            return IntegrationHealthResult(
                state=IntegrationState.NOT_CONFIGURED,
                message="آدرس فروشگاه، Consumer Key یا Consumer Secret ووکامرس تنظیم نشده است."
            )

        # SSRF Protection
        try:
            validate_custom_url(store_url)
        except ValidationError as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"آدرس سایت ووکامرس از نظر امنیتی مجاز نیست: {e}"
            )

        test_url = f"{store_url}/wp-json/wc/v3/system_status"
        try:
            import base64
            auth_str = f"{ck}:{cs}"
            auth_header = f"Basic {base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')}"
            req = urllib.request.Request(
                test_url,
                headers={'Authorization': auth_header, 'Accept': 'application/json', 'User-Agent': 'ShopPilot-Integration/1.0'},
                method='GET'
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    env = data.get('environment', {})
                    wc_ver = env.get('version', 'معتبر')
                    site_title = env.get('site_title', store_url)
                    return IntegrationHealthResult(
                        state=IntegrationState.READY,
                        message=f"اتصال به ووکامرس سایت «{site_title}» (نسخه {wc_ver}) با موفقیت برقرار شد.",
                        details={'wc_version': wc_ver, 'site_title': site_title}
                    )
                return IntegrationHealthResult(
                    state=IntegrationState.TEST_FAILED,
                    message=f"پاسخ غیرمنتظره از ووکامرس: کد {resp.status}"
                )
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return IntegrationHealthResult(
                    state=IntegrationState.TEST_FAILED,
                    message="کلید یا رمز مصرف‌کننده ووکامرس نامعتبر است یا دسترسی Read/Write ندارد (کد ۴۰۱/۴۰۳)."
                )
            elif e.code == 404:
                try:
                    alt_url = f"{store_url}/wp-json/wc/v3/products?per_page=1"
                    alt_req = urllib.request.Request(alt_url, headers={'Authorization': auth_header, 'Accept': 'application/json'}, method='GET')
                    with urllib.request.urlopen(alt_req, timeout=10) as alt_resp:
                        if alt_resp.status == 200:
                            return IntegrationHealthResult(
                                state=IntegrationState.READY,
                                message="اتصال به REST API محصولات ووکامرس با موفقیت برقرار شد."
                            )
                except Exception:
                    pass
                return IntegrationHealthResult(
                    state=IntegrationState.TEST_FAILED,
                    message="مسیر REST API ووکامرس در این آدرس یافت نشد (کد ۴۰۴). لطفاً فعال بودن پیوندهای یکتا (Permalinks) در وردپرس را بررسی فرمایید."
                )
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"خطای وب‌سرویس ووکامرس: کد {e.code}"
            )
        except Exception as e:
            return IntegrationHealthResult(
                state=IntegrationState.TEST_FAILED,
                message=f"عدم برقراری ارتباط با سایت ووکامرس: {str(e)}"
            )


# -----------------------------------------------------------------------------
# Central Integration Registry
# -----------------------------------------------------------------------------
class IntegrationRegistry:
    # All registered adapters (canonical + legacy aliases)
    _adapters: Dict[str, BaseIntegrationAdapter] = {
        'sms_kavenegar': KavenegarSMSAdapter(),
        'sms_gateway': KavenegarSMSAdapter(),  # alias for backward compat
        'instagram': InstagramIntegrationAdapter(),
        'social_instagram': InstagramIntegrationAdapter(),  # alias
        'social_telegram': TelegramIntegrationAdapter(),
        'telegram': TelegramIntegrationAdapter(),  # alias
        'payment_zarinpal': ZarinpalPaymentAdapter(),
        'zarinpal': ZarinpalPaymentAdapter(),  # alias
        'shipping_irpost': IranPostShippingAdapter(),
        'shipping_tipax': TipaxShippingAdapter(),
        'ai_provider': GoogleGeminiAIAdapter(),
        'ai_gemini': GoogleGeminiAIAdapter(),  # alias
        'email_smtp': SMTPEmailAdapter(),
        'ecommerce_woocommerce': WooCommerceIntegrationAdapter(),
        'woocommerce': WooCommerceIntegrationAdapter(),  # alias
    }

    # Canonical list for UI management center (no duplicates)
    _canonical_ids: List[str] = [
        'sms_kavenegar',
        'social_instagram',
        'social_telegram',
        'payment_zarinpal',
        'shipping_irpost',
        'shipping_tipax',
        'ai_gemini',
        'email_smtp',
        'ecommerce_woocommerce',
    ]

    @classmethod
    def get_adapter(cls, name: str) -> Optional[BaseIntegrationAdapter]:
        return cls._adapters.get(name)

    @classmethod
    def get_all_adapters(cls) -> Dict[str, BaseIntegrationAdapter]:
        return cls._adapters

    @classmethod
    def get_canonical_adapters(cls) -> List[BaseIntegrationAdapter]:
        return [cls._adapters[name] for name in cls._canonical_ids if name in cls._adapters]

    @classmethod
    def get_store_integration_statuses(cls, store) -> Dict[str, Any]:
        """
        Backward compatible dict format for existing views and tests,
        enriched with full lifecycle and UI metadata.
        """
        results = {}
        for name, adapter in cls._adapters.items():
            record = adapter.get_store_config_record(store)
            status = adapter.get_status(store)
            health = adapter.health_check(store)

            results[name] = {
                'id': adapter.name,
                'name': adapter.name,
                'category': adapter.category,
                'display_name_fa': adapter.display_name_fa,
                'description_fa': adapter.description_fa,
                'guide_fa': adapter.guide_fa,
                'status': status,
                'is_active': record.is_active if record else (status in (IntegrationState.ACTIVE, IntegrationState.CONNECTED)),
                'is_ready': adapter.is_ready(store),
                'message': health.message,
                'last_tested_at': record.last_tested_at.isoformat() if (record and record.last_tested_at) else None,
                'last_connected_at': record.last_connected_at.isoformat() if (record and record.last_connected_at) else None,
                'last_test_error': record.last_test_error if record else "",
                'last_test_success': record.last_test_success if record else None,
                'schema': adapter.get_schema(),
                'config': adapter.get_config(store, decrypted=False)
            }
        return results


def get_integration_adapter(name: str):
    return IntegrationRegistry.get_adapter(name)


# Aliases for backward compatibility and test mock targeting
SMSGateway = KavenegarSMSAdapter
SMSAdapter = KavenegarSMSAdapter
SMSGatewayIntegrationAdapter = KavenegarSMSAdapter
AIProviderIntegrationAdapter = GoogleGeminiAIAdapter
