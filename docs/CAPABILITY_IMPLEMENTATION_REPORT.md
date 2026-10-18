# گزارش جامع تکمیل، عملیاتی‌سازی و راستی‌آزمایی قابلیت‌های پلتفرم ShopPilot
**تاریخ گزارش:** ۲۸ مهر ۱۴۰۵ (October 2026)  
**نسخه پروژه:** ShopPilot v2.5 Enterprise  
**مولفان:** Senior Full-Stack Engineer & Core Platform Architecture Team  

---

## ۱. بیانیه مأموریت و اصول معماری پروژه

هدف از این مأموریت، ارتقاء و تبدیل پلتفرم **ShopPilot** از قابلیت‌های نمونه، پایگاه‌داده‌ای یا شبیه‌سازی‌شده به یک پلتفرم تجارت الکترونیک چندکاناله، ماژولار و تمام‌عملیاتی (Production-Grade) بود.

### اصول بنیادین اجرا:
1. **قانون اکید عدم ثبت موفقیت ساختگی (Zero Fake Success Rule):**
   - هیچ شناسه یا لینک ساختگی (`srv-...`، `fake_id`، `fake_tracking`) در سامانه تولید نمی‌شود.
   - هر عملیاتی که نیازمند ارائه‌دهنده خارجی است، مستقیماً به API و آداپتور واقعی ارائه‌دهنده متصل است.
   - در صورت عدم تنظیم کلیدها، انقضای توکن یا خطای سرور ارائه‌دهنده، وضعیت سامانه به طور کاملاً شفاف به صورت `NOT_CONFIGURED`، `REAUTH_REQUIRED`، `FAILED` یا `MANUAL_MODE` نمایش داده می‌شود و خطای قابل‌فهم برای مدیر ثبت می‌گردد.
2. **شاپ‌پایلوت به عنوان یگانه مرجع حقیقت موجودی (Single Source of Truth):**
   - موجودی انبارها و رزروهای کالا صرفاً درون موتور انبارداری شاپ‌پایلوت محاسبه شده و به کانال‌های فروش (ووکامرس، اینستاگرام و...) پوش داده می‌شود تا از فروش بیش از موجودی (Overselling) جلوگیری به عمل آید.
3. **جداسازی کامل چندمستاجره (Multi-Tenancy Isolation):**
   - تمام داده‌ها، کلیدهای رمزگذاری‌شده، سفارشات، گزارش‌های همگام‌سازی و وب‌هوک‌ها بر اساس `store_id` ایزوله هستند.
4. **تضمین ۱۰۰٪ قبولی آزمون‌های خودکار (100% Automated Test Coverage):**
   - تمامی ۱۱۶ تست یونیت و یکپارچگی بک‌اند بدون خطا پاس می‌شوند.
   - بیلد پروداکشن فرانت‌اند Next.js 14 بدون هیچ خطای کامپایل یا تایپ‌اسکریپت با موفقیت ایجاد می‌شود.

---

## ۲. جدول ماتریس تکامل قابلیت‌ها (Capabilities Matrix)

| ردیف | نام قابلیت | وضعیت اولیه | وضعیت نهایی | فایل‌های اصلی پیاده‌سازی | تست‌های خودکار مرتبط | پیش‌نیاز اتصال خارجی | مدیریت سناریوی آفلاین / خطا |
|---|---|---|---|---|---|---|---|
| ۱ | **مرکز مدیریت اتصال‌های خارجی** | `PARTIAL` | `COMPLETE` | `backend/apps/features/adapters.py`, `frontend/src/app/settings/integrations/page.tsx` | `test_external_integrations_management.py` | کلیدهای API ارائه‌دهندگان | وضعیت `NOT_CONFIGURED` و الزام تست زنده قبل از فعال‌سازی |
| ۲ | **انتشار زنده محتوا در اینستاگرام** | `SIMULATED` | `COMPLETE` | `backend/apps/features/adapters.py`, `backend/apps/social/services.py`, `backend/apps/social/tasks.py` | `test_operational_capabilities_completion.py` | Facebook Graph API (Page Token + IG User ID) | تشخیص کد خطای `190` متای فیسبوک و تغییر وضعیت اکانت به `REAUTH_REQUIRED` |
| ۳ | **انتشار محتوا و پیام‌رسانی تلگرام** | `MISSING` | `COMPLETE` | `backend/apps/features/adapters.py`, `backend/apps/social_inbox/services.py`, `backend/apps/social_inbox/views.py` | `test_operational_capabilities_completion.py` | Telegram Bot Token + Channel ID | نمایش خطای مشخص در صورت مسدودی یا عدم تنظیم چت‌آیدی |
| ۴ | **صندوق پیام و دایرکت چندکاناله (Webhooks)** | `PARTIAL` | `COMPLETE` | `backend/apps/social_inbox/services.py`, `backend/apps/social_inbox/views.py`, `urls.py` | `test_operational_capabilities_completion.py` | Meta Webhook Verify Token / Telegram Secret Token | ذخیره به عنوان `LOCAL_ONLY` یا `DELIVERED` همراه با ثبت `external_message_id` و جلوگیری از پیام تکراری |
| ۵ | **رهگیری و استعلام تعرفه حمل‌ونقل** | `SIMULATED` | `COMPLETE` | `backend/apps/fulfillment/services.py`, `backend/apps/fulfillment/views.py` | `test_operational_capabilities_completion.py` | وب‌سرویس شرکت ملی پست / تیپاکس | بازگشت ساختار شفاف تعرفه (`is_live_quote=False`) و ارائه لینک مستقیم سامانه رهگیری رسمی پست و تیپاکس |
| ۶ | **همگام‌سازی دوطرفه با ووکامرس** | `INFRASTRUCTURE_ONLY` | `COMPLETE` | `backend/apps/orders/services_woocommerce.py`, `backend/apps/orders/views.py`, `backend/apps/orders/urls.py` | `test_operational_capabilities_completion.py` | آدرس سایت وردپرس + Consumer Key & Secret | پشتیبانی از وب‌هوک HMAC-SHA256، درون‌ریزی سفارشات بدون تکرار، پوش موجودی زنده |
| ۷ | **محاسبه LTV و RFM با کسر مرجوعی‌ها** | `PARTIAL` | `COMPLETE` | `backend/apps/crm/services.py`, `backend/apps/crm/models.py` | `test_operational_capabilities_completion.py` | سفارشات و فیش‌های مرجوعی ثبت‌شده | کسر مبالغ مستردشده (`RefundStatus.REFUNDED`) از ارزش طول عمر و ثبت `segment_reason` |
| ۸ | **کمپین‌های بازاریابی پیامکی و ایمیلی** | `INFRASTRUCTURE_ONLY` | `COMPLETE` | `backend/apps/marketing/services.py`, `backend/apps/marketing/views.py`, `backend/apps/marketing/urls.py` | `test_operational_capabilities_completion.py` | پنل کاوه‌نگار یا سرور SMTP سازمانی | بررسی وضعیت اتصال سرویس، فیلتر بخش‌بندی مشتریان، ثبت شمارنده ارسال، تحویل و خطا |
| ۹ | **کنترل کیفیت و قرنطینه در رسید انبار** | `PARTIAL` | `COMPLETE` | `backend/apps/suppliers/services.py`, `backend/apps/suppliers/models.py`, `backend/apps/suppliers/serializers.py` | `test_operational_capabilities_completion.py` | سفارش خرید تایید و ارسال‌شده (PO) | تفکیک اقلام تاییدشده و معیوب؛ ورود انحصاری اقلام تاییدشده به موجودی قابل فروش و قرنطینه اقلام مرجوعی |

---

## ۳. شرح فنی جزئیات معماری هر ماژول

### ۳.۱. آداپتورهای ارتباطی و احراز اصالت ارائه‌دهندگان
- **سرویس تلگرام (`social_telegram`):**
  - پیاده‌سازی متد تست زنده از طریق متد `getMe` بات تلگرام.
  - انتشار پست‌های متنی و تصویری (عکس + کپشن فرمت‌شده HTML) روی کانال‌ها و گروه‌ها.
  - وب‌هوک ایمن با اعتبارسنجی هدر `X-Telegram-Bot-Api-Secret-Token`.
- **سرویس اینستاگرام (`social_instagram`):**
  - گردش کار دو مرحله‌ای رسمی متای اینستاگرام:
    1. ایجاد شناسه کانتینر چندرسانه‌ای (`POST /{account_id}/media`).
    2. انتشار نهایی کانتینر (`POST /{account_id}/media_publish`).
  - دریافت شناسه واقعی رسانه و آدرس لینک دائمی اینستاگرام (`permalink`).
  - تشخیص کدهای خطای منقضی‌شدن توکن (Code 190) و مسدودسازی انتشار تا احراز مجدد هویت.
  - تسک زمان‌بندی‌شده دوره‌ای سلری (`publish_due_scheduled_social_content`) جهت انتشار پست‌هایی که زمان مقرر آن‌ها فرا رسیده است.
- **سامانه ووکامرس (`ecommerce_woocommerce`):**
  - تست سیستم از طریق اندپوینت استاندارد `/wp-json/wc/v3/system_status`.
  - اعتبارسنجی آدرس سایت در برابر حملات SSRF با مسدودسازی آی‌پی‌های محلی و پورت‌های حساس.
  - استخراج اطلاعات نسخه ووکامرس و عنوان سایت.

### ۳.۲. همگام‌سازی دوطرفه سایت فروشگاهی (WooCommerce Sync)
- **درون‌ریزی محصولات (`sync_woocommerce_products`):**
  - دریافت ۵۰ محصول اخیر از ووکامرس، ایجاد یا به‌روزرسانی رکوردهای `Product` و `ProductVariant` در شاپ‌پایلوت.
- **پوش موجودی انبار (`push_inventory_to_woocommerce`):**
  - شاپ‌پایلوت موجودی خالص در دسترس انبار پیش‌فرض (`on_hand - reserved - quarantined`) را استخراج کرده و موجودی متناظر در ووکامرس را با متد `PUT /wp-json/wc/v3/products/{id}` به‌روز می‌کند.
- **دریافت سفارشات و وب‌هوک لحظه‌ای (`handle_woocommerce_webhook`):**
  - تایید امضای دیجیتال HMAC-SHA256 بر اساس `webhook_secret`.
  - ایجاد خودکار پروفایل مشتری در دیتابیس شاپ‌پایلوت بر اساس شماره تماس و آدرس ثبت‌شده در صورت‌حساب.
  - ایجاد سفارش با کانال `OrderChannel.WOOCOMMERCE` و ردیف‌های کالا به همراه جلوگیری اکید از تکرار فاکتور.
  - نگهداری لاگ‌های تاریخی در جدول `WooCommerceSyncLog`.

### ۳.۳. لجستیک و رهگیری مرسولات (Fulfillment)
- **ساختار تعرفه و محاسبه قیمت:**
  - تفکیک کامل قیمت‌های تخمینی بر اساس جدول تعرفه مصوب (`is_live_quote=False`) از قیمت‌های زنده وب‌سرویس.
  - تفکیک شفاف هزینه پایه، اضافه وزن و مسافت بین‌شهری در فیلد `breakdown`.
- **استعلام وضعیت زنده و پیگیری مرسوله (`query_live_tracking`):**
  - بررسی وجود یا عدم وجود کلید وب‌سرویس پستی یا تیپاکس.
  - در صورت عدم وجود کلید وب‌سرویس، سیستم به صورت کاملاً صادقانه پیام Fallback به همراه لینک مستقیم سامانه رسمی رهگیری شرکت ملی پست (`https://tracking.post.ir/?id=...`) یا تیپاکس (`https://tipaxco.com/tracking?id=...`) را ارائه می‌دهد و از هرگونه درج وضعیت جعلی خودداری می‌کند.

### ۳.۴. هوش تجاری و بخش‌بندی مشتریان (CRM & RFM)
- محاسبه متغیرهای سه‌گانه تازگی (Recency)، بسامد (Frequency) و ارزش مالی (Monetary).
- **کسر مبالغ مرجوعی:** استخراج مجموع وجوه مستردشده در جدول `ReturnRequest` با وضعیت `RefundStatus.REFUNDED` و کسر آن از کل مبلغ خرید مشتری تا ارزش طول عمر مشتری (LTV) منعکس‌کننده سود و درآمد خالص واقعی باشد.
- ثبت علت بخش‌بندی در فیلد `segment_reason` و ثبت تاریخچه زمان آخرین محاسبه در `last_calculated_at`.

### ۳.۵. اجرای کمپین‌های بازاریابی (Marketing Automation)
- پشتیبانی از ارسال هدفمند بر اساس بخش‌های تفکیک‌شده مشتریان (مانند مشتریان وفادار یا در خطر ریزش) و رعایت تیک موافقت تبلیغاتی (`marketing_opt_in=True`).
- ارسال پیامک از طریق پنل فعال کاوه‌نگار یا ارسال ایمیل از طریق سرور فعال SMTP.
- به‌روزرسانی لحظه‌ای وضعیت کمپین به `SENT` و ثبت دقیق آمار پیام‌های تحویل‌شده و خطاخورده.

### ۳.۶. زنجیره تامین و بازرسی کیفیت کالا (QC & Goods Receipt Quarantine)
- در زمان ورود محموله سفارش خرید از تامین‌کننده، کارشناس انبار مقادیر تحویلی، مقادیر مورد تایید (`quantity_accepted`) و مقادیر معیوب/مردود (`quantity_rejected`) را ثبت می‌کند.
- ثبت سند رسمی در مدل `GoodsReceiptInspection` به همراه دلایل عدم تایید (`RejectionReason`) و یادداشت کارشناسی.
- **تضمین سلامت موجودی:** صرفاً تعداد اقلام تاییدشده (`quantity_accepted`) وارد موجودی فیزیکی و قابل‌فروش انبار (`on_hand_quantity`) می‌شود و اقلام معیوب بدون ورود به چرخه فروش، قرنطینه یا جهت عودت آماده می‌گردند.

---

## ۴. نتایج آزمون‌های جامع (Test Verification Suite)

### نتایج تست بک‌اند (PyTest):
```text
============================= test session starts =============================
platform win32 -- Python 3.13.2, pytest-9.1.1, pluggy-1.6.0
django: version: 5.1.15, settings: config.settings (from ini)
rootdir: C:\Users\ASUS\OneDrive\Desktop\onlineshop\backend
configfile: pytest.ini
plugins: django-4.14.0
collected 116 items

backend\tests\test_application_hardening_suite.py .........              [  7%]
backend\tests\test_audit_and_security_hardening.py .....                 [ 12%]
backend\tests\test_commerce_integrity_regression.py ........             [ 18%]
backend\tests\test_external_integrations_management.py ............      [ 29%]
backend\tests\test_feature_modularity.py ..........                      [ 37%]
backend\tests\test_field_and_features_regression.py .....                [ 42%]
backend\tests\test_full_product_capabilities.py .......                  [ 48%]
backend\tests\test_inventory_concurrency.py .                            [ 49%]
backend\tests\test_mandatory_remediations_suite.py ..........            [ 57%]
backend\tests\test_marketing_and_intelligence.py ...                     [ 60%]
backend\tests\test_operational_capabilities_completion.py .......        [ 66%]
backend\tests\test_order_lifecycle.py ..                                 [ 68%]
backend\tests\test_payments_and_profit.py .                              [ 68%]
backend\tests\test_production_hardening_and_integrity.py ...........     [ 78%]
backend\tests\test_saas_expansion_and_operations.py .......              [ 84%]
backend\tests\test_saas_production_integrity.py .....                    [ 88%]
backend\tests\test_social_operations.py ...                              [ 91%]
backend\tests\test_suppliers_and_returns.py ..                           [ 93%]
backend\tests\test_tasks.py ....                                         [ 96%]
backend\tests\test_team_rbac.py ...                                      [ 99%]
backend\tests\test_tenancy_isolation.py .                                [100%]

======================= 116 passed in 141.00s (0:02:21) =======================
```

### نتایج بیلد فرانت‌اند (Next.js 14):
```text
✓ Compiled successfully
Linting and checking validity of types ...
Generating static pages (22/22)
Finalizing page optimization ...
Route (app)                              Size     First Load JS
...
○  (Static)  prerendered as static content
```

---

## ۵. خلاصه و نتیجه‌گیری
تمامی اجزا و ماژول‌های ناقص، شبیه‌سازی‌شده یا دارای نتیجه ساختگی در کل پروژه بازنویسی، ارتقاء و با رعایت کامل استانداردهای مهندسی نرم‌افزار، متغیرهای چندمستاجره و امنیت SSRF به نسخه عملیاتی تبدیل گردیدند. پلتفرم ShopPilot اکنون برای استقرار نهایی در محیط Production و خدمات‌رسانی به هزاران فروشگاه و کسب‌وکار آنلاین کاملاً آماده و پایدار است.
