'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import {
  LayoutDashboard,
  LayoutGrid,
  Boxes,
  ShoppingCart,
  Store,
  RotateCcw,
  Truck,
  CreditCard,
  MessageSquare,
  CheckSquare,
  Calendar,
  Tag,
  Sparkles,
  Users,
  Link2,
  Settings,
  Search,
  BookOpen,
  ArrowRight,
  ExternalLink,
  CheckCircle2,
  HelpCircle,
  Lightbulb,
  Compass,
  Zap,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface GuideSection {
  id: string;
  category: string;
  title: string;
  subtitle: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  accentColor: string;
  description: string;
  whyNeeded: string;
  howToUse: string[];
  keyFeatures: string[];
  proTips: string;
}

const GUIDE_ITEMS: GuideSection[] = [
  {
    id: 'dashboard',
    category: 'عملیات و کنترل',
    title: 'داشبورد عملیات روزانه',
    subtitle: 'دیده‌بان زنده وضعیت فروشگاه، هشدارها و سفارشات',
    href: '/',
    icon: LayoutDashboard,
    accentColor: 'from-blue-500 to-cyan-500',
    description: 'صفحه اصلی و کابین خلبان فروشگاه شماست که خلاصه‌ای فوری از فروش روز، سفارشات نیازمند رسیدگی، و هشدارهای مهم زنجیره تامین را نشان می‌دهد.',
    whyNeeded: 'برای اینکه هر روز صبح با یک نگاه متوجه شوید چه سفارش‌هایی باید ارسال شوند، چه کالاهایی رو به اتمام است و کسب‌وکارتان در چه وضعیتی قرار دارد.',
    howToUse: [
      'بررسی آمار فروش، تعداد سفارشات و نرخ پردازش در بالای صفحه.',
      'مشاهده «اقدامات روزانه» شامل کالاهای ناموجود یا هشدارهای تاخیر ارسال.',
      'کلیک روی هر هشدار یا آمار برای انتقال مستقیم به بخش مربوطه و رفع آن.',
    ],
    keyFeatures: [
      'کارت‌های زنده آماری (فروش روز، سود ناخالص، تعداد مشتریان جدید)',
      'سیستم هشدارهای اولویت‌بندی‌شده بر اساس فوریت عملیاتی',
      'نمودار مقایسه‌ای روند فروش روزانه و هفتگی',
    ],
    proTips: 'همیشه ابتدای هر شیفت کاری این صفحه را چک کنید تا هیچ سفارشی معطل نماند.',
  },
  {
    id: 'catalog',
    category: 'هسته انبار و کالا',
    title: 'کاتالوگ و تنوع محصولات',
    subtitle: 'تعریف کالاها، رنگ‌بندی، سایزها، SKU و قیمت‌گذاری',
    href: '/products',
    icon: LayoutGrid,
    accentColor: 'from-sky-500 to-indigo-500',
    description: 'بانک اطلاعاتی متمرکز تمامی اقلامی که می‌فروشید؛ شامل نام، تصاویر، دسته‌بندی، بارکد، تنوع‌ها (رنگ و سایز) و قیمت خرید و فروش.',
    whyNeeded: 'پایه‌ای‌ترین بخش سیستم است؛ تا محصولی تعریف نشود امکان ثبت موجودی، فاکتور خرید و سفارش فروش وجود ندارد.',
    howToUse: [
      'روی دکمه «افزودن محصول جدید» کلیک کنید.',
      'نام کالا، برند و دسته‌بندی را انتخاب کنید.',
      'تنوع‌های کالا (مانند سایز مدیوم / لارج یا رنگ مشکی / سفید) و کد SKU هر کدام را وارد کنید.',
      'قیمت خرید (تمام‌شده) و قیمت فروش عادی را وارد و ذخیره کنید.',
    ],
    keyFeatures: [
      'پشتیبانی از چندتنوعی (Variants) با SKU و بارکد مستقل برای هر تنوع',
      'محاسبه خودکار حاشیه سود هر محصول بر اساس قیمت خرید و فروش',
      'فیلتر پیشرفته بر اساس دسته‌بندی و جستجوی لحظه‌ای بر اساس بارکد یا نام',
    ],
    proTips: 'کد SKU هر تنوع را منظم و یکدست انتخاب کنید (مثلاً SHIRT-BLK-M) تا در بارکدخوان و جستجو سریع پیدا شود.',
  },
  {
    id: 'inventory',
    category: 'هسته انبار و کالا',
    title: 'موجودی و انبارداری چندگانه',
    subtitle: 'مدیریت چند انبار، رزرو خودکار، شمارش و حواله انتقال',
    href: '/inventory',
    icon: Boxes,
    accentColor: 'from-amber-500 to-orange-500',
    description: 'سیستم ثبت و رهگیری دقیق موجودی فیزیکی و قابل فروش در انبارهای مختلف (مرکزی، انبار مغازه، انبار آنلاین).',
    whyNeeded: 'جلوگیری از Overselling (فروختن بیش از موجودی واقعی) در زمان حراجی و کمپین‌های اینستاگرامی و تلگرامی.',
    howToUse: [
      'مشاهده موجودی کل، تعداد رزروشده (در سبد خرید یا منتظر تایید پرداخت) و مقدار آزاد قابل فروش.',
      'ثبت ورود اولیه کالا به انبار از طریق فرم ورود موجودی.',
      'ثبت حواله انتقال کالا بین انبارها (مثلاً از انبار مرکزی به فروشگاه حضوری).',
      'انجام انبارگردانی دوره‌ای و ثبت کسری یا مازاد انبار با درج علت.',
    ],
    keyFeatures: [
      'تفکیک هوشمند «موجودی فیزیکی» از «موجودی قابل فروش» با قفل اتمیک موجودی',
      'دفترکل دوطرفه ثبت وقایع انبار (Double-Entry Inventory Ledger)',
      'هشدار خودکار نقطه سفارش (Reorder Point) برای کالاهای رو به پایان',
    ],
    proTips: 'اگر مشتری در حال پرداخت آنلاین باشد، موجودی کالا برای او رزرو می‌شود و پس از تکمیل خرید به طور قطعی کسر می‌گردد.',
  },
  {
    id: 'orders',
    category: 'فروش و ثبت فاکتور',
    title: 'مدیریت سفارشات چندکاناله',
    subtitle: 'یکپارچه‌سازی سفارش‌های اینستاگرام، سایت، تلگرام و تلفنی',
    href: '/orders',
    icon: ShoppingCart,
    accentColor: 'from-emerald-500 to-teal-500',
    description: 'مرکز متمرکز دریافت و پردازش سفارش‌های مشتریان از تمام درگاه‌ها، از لحظه ثبت تا پرداخت، بسته‌بندی، ارسال و تحویل.',
    whyNeeded: 'برای اینکه سفارش‌های دایرکت اینستاگرام و سایت در یک جا جمع شوند و نیازی به یادداشت دستی در دفتر یا اکسل نباشد.',
    howToUse: [
      'برای ثبت سفارش جدید، دکمه «ثبت سفارش» را بزنید و مشتری و کالاهای درخواستی را انتخاب کنید.',
      'کانال ورودی سفارش (اینستاگرام، وب‌سایت، حضوری) را تعیین کنید.',
      'وضعیت سفارش (در انتظار پرداخت، تایید شده، در حال بسته‌بندی، ارسال شده) را با پیشرفت کار تغییر دهید.',
      'پس از آماده‌سازی مرسوله، گزینه «تحویل به پست/پیک» را بزنید تا فاکتور صادر شود.',
    ],
    keyFeatures: [
      'چاپ فاکتور استاندارد و برچسب پستی (Shipping Label) با یک کلیک',
      'کسر آنی موجودی انبار به محض تایید پرداخت فاکتور',
      'ارسال خودکار پیامک تغییر وضعیت سفارش به شماره موبایل خریدار',
    ],
    proTips: 'با استفاده از فیلتر وضعیت، می‌توانید فقط سفارش‌هایی که نیاز به بسته‌بندی امروز دارند را تفکیک کنید.',
  },
  {
    id: 'pos',
    category: 'فروش و ثبت فاکتور',
    title: 'صندوق حضوری و فروش عمده (POS & B2B)',
    subtitle: 'صدور سریع فاکتور پای صندوق، بارکدخوان و تخفیف همکاری',
    href: '/pos',
    icon: Store,
    accentColor: 'from-purple-500 to-pink-500',
    description: 'محیط طراحی‌شده برای فروشندگان داخل مغازه یا فروشگاه فیزیکی جهت اسکن بارکد، ثبت فیش خرید سریع و تسویه کارتخوان.',
    whyNeeded: 'اگر مغازه فیزیکی دارید، برای اینکه موجودی انبار مغازه با آنلاین‌شاپ همگام باشد و صندوقدار بتواند در چند ثانیه فاکتور صادر کند.',
    howToUse: [
      'بارکد کالا را با بارکدخوان اسکن کنید یا نام محصول را جستجو کنید.',
      'تعداد و تخفیف پای صندوق را مشخص کنید.',
      'روش پرداخت (کارتخوان مغازه، نقدی یا ترکیبی) را انتخاب کنید و دکمه «تسویه و چاپ فیش» را بزنید.',
      'در صورت فروش به مشتریان عمده/همکار، گزینه فاکتور B2B با قیمت همکار را انتخاب کنید.',
    ],
    keyFeatures: [
      'رابط کاربری تاچ و بهینه‌سازی‌شده برای تبلت و مانیتورهای لمسی صندوق',
      'پشتیبانی کامل از بارکدخوان‌های USB و بی‌سیم',
      'کسر آنی از انبار شعبه فیزیکی بدون کوچک‌ترین تاخیر',
    ],
    proTips: 'حتی اگر چند صندوقدار داشته باشید، همه از یک موجودی مشترک و ایمن استفاده می‌کنند.',
  },
  {
    id: 'returns',
    category: 'خدمات پس از فروش',
    title: 'مرجوعی‌ها و خدمات پس از فروش (RMA)',
    subtitle: 'رسیدگی به کالای عودتی، تعویض سایز و بازگشت وجه',
    href: '/returns',
    icon: RotateCcw,
    accentColor: 'from-rose-500 to-orange-500',
    description: 'مدیریت شفاف کالاهایی که مشتری به دلیل سایز نامناسب، عیب ظاهری یا انصراف قصد عودت یا تعویض آن‌ها را دارد.',
    whyNeeded: 'جلوگیری از گم شدن کالاهای مرجوعی و مشخص بودن اینکه چه پولی باید به مشتری عودت داده شود یا کدام کالا باید دوباره ارسال شود.',
    howToUse: [
      'شماره سفارش یا موبایل مشتری را جستجو کرده و روی «ثبت درخواست مرجوعی» کلیک کنید.',
      'اقلام مورد نظر و علت مرجوعی (اشتباه در سایز، خرابی فیزیکی، عدم تطابق با عکس) را انتخاب کنید.',
      'نوع درخواست (تعویض کالا با سایز دیگر یا عودت وجه) را مشخص کنید.',
      'پس از دریافت فیزیکی کالا در انبار، کارشناس آن را بررسی و تایید یا رد می‌کند.',
    ],
    keyFeatures: [
      'بازگرداندن خودکار کالای سالم به موجودی انبار پس از تایید انباردار',
      'مدیریت اختلاف قیمت در تعویض کالا (کسر یا اضافه دریافت)',
      'ثبت سابقه کامل علت‌های مرجوعی برای اصلاح کیفیت تولید یا تامین',
    ],
    proTips: 'قبل از تایید بازگشت وجه، حتماً از رسیدن فیزیکی کالا به انبار اطمینان حاصل فرمایید.',
  },
  {
    id: 'suppliers',
    category: 'مالی و زنجیره تامین',
    title: 'تامین‌کنندگان و سفارشات خرید',
    subtitle: 'مدیریت کارگاه‌ها، ثبت فاکتور خرید عمده و بدهی‌ها',
    href: '/suppliers',
    icon: Truck,
    accentColor: 'from-amber-600 to-yellow-500',
    description: 'فهرست کارگاه‌های تولیدی، بنکداران و تامین‌کنندگانی که اجناس خود را از آن‌ها تهیه می‌کنید، به همراه فاکتورهای خرید عمده.',
    whyNeeded: 'برای اینکه بدانید هر کالا را با چه قیمتی از چه کسی خریده‌اید، چقدر به کارگاه‌ها بدهکارید و چه سفارش خریدی در راه انبار است.',
    howToUse: [
      'مشخصات تامین‌کنندگان جدید (نام، تلفن، آدرس، شماره شبا) را ثبت کنید.',
      'برای تامین جنس، یک «سفارش خرید (Purchase Order)» با تعداد و قیمت خرید ثبت کنید.',
      'با تحویل بار توسط راننده به انبار، سفارش را «تحویل‌شده» کنید تا کالاها به انبار اضافه شوند.',
      'پرداخت‌های اقساطی یا نقدی به تامین‌کننده را در بخش پرداخت ثبت کنید.',
    ],
    keyFeatures: [
      'به‌روزرسانی خودکار میانگین قیمت تمام‌شده کالاها (Weighted Average Cost)',
      'محاسبه دقیق مانده‌حساب بدهی و بستانکاری هر تامین‌کننده',
      'تاریخچه تغییرات قیمت خرید در طول زمان برای رصد تورم و هزینه‌ها',
    ],
    proTips: 'ثبت دقیق قیمت خرید در این بخش، ضامن محاسبه بدون خطای سود خالص در بخش مالی است.',
  },
  {
    id: 'payments',
    category: 'مالی و زنجیره تامین',
    title: 'تأیید فیش‌های واریزی و تسویه‌ها',
    subtitle: 'کارتابل کارت به کارت، تطبیق درگاه و صورت سود و زیان',
    href: '/payments',
    icon: CreditCard,
    accentColor: 'from-emerald-500 to-green-600',
    description: 'مهم‌ترین بخش مالی سیستم برای تایید دستی فیش‌های کارت‌به‌کارت خریداران، استعلام وضعیت درگاه آنلاین و گزارش P&L سود و زیان واقعی.',
    whyNeeded: 'جلوگیری از کلاهبرداری با فیش‌های جعلی فتوشاپی و اطمینان از اینکه قبل از ارسال جنس، پول حتماً در حساب نشسته باشد.',
    howToUse: [
      'در تب «تراکنش‌ها»، فیش‌های منتظر بررسی را با کلیک روی «مشاهده فیش» باز کنید.',
      'کد پیگیری و ۴ رقم آخر کارت را با پیامک بانکی یا همراه بانک خود تطبیق دهید.',
      'در صورت صحت واریز، دکمه سبز «تأیید واریز» را بزنید تا سفارش خودکار آماده ارسال شود.',
      'در تب «سود و زیان (P&L)»، فروش ناخالص، بهای تمام‌شده و سود خالص فروشگاه را ببینید.',
    ],
    keyFeatures: [
      'سیستم ضداضافه‌پرداخت و تطبیق تراکنش‌های آنلاین با زرین‌پال',
      'امکان ثبت هزینه‌های جاری کسب‌وکار (اجاره، بسته‌بندی، تبلیغات، حقوق)',
      'نمایش ارقام مالی و مبالغ با فونت استاندارد فارسی و واحد تومان',
    ],
    proTips: 'فیش‌های کارت‌به‌کارت را حداکثر ظرف چند ساعت بررسی کنید تا رضایت خریداران اینستاگرامی بالا بماند.',
  },
  {
    id: 'crm',
    category: 'مشتریان و ارتباطات',
    title: 'مشتریان و پیام‌ها (CRM & Social Inbox)',
    subtitle: 'پرونده مشتری، سطح وفاداری، تاریخچه خرید و پاسخگویی دایرکت',
    href: '/crm',
    icon: MessageSquare,
    accentColor: 'from-blue-600 to-indigo-600',
    description: 'بانک جامع مشتریان با دسته‌بندی خودکار (VIP، وفادار، کم‌خرید، در معرض ریزش) و تجمیع پیام‌های دایرکت اینستاگرام و چت سایت.',
    whyNeeded: 'برای اینکه مشتریان دائمی و خوش‌حساب خود را بشناسید و با ارسال پیشنهادات ویژه، فروش تکراری خود را افزایش دهید.',
    howToUse: [
      'جستجوی شماره موبایل یا نام مشتری برای دیدن پرونده، آدرس‌ها و مجموع خریدهای گذشته او.',
      'ارسال پیامک اطلاع‌رسانی یا پیگیری سفارش مستقیماً از پرونده مشتری.',
      'مشاهده برچسب‌های هوشمند ارزش مشتری (CLV - Customer Lifetime Value).',
      'در بخش پیام‌ها، پاسخگویی به دایرکت‌های ورودی بدون نیاز به دسترسی مستقیم ادمین به اکانت اصلی اینستاگرام.',
    ],
    keyFeatures: [
      'دسته‌بندی هوشمند مشتریان بر اساس مدل استاندارد RFM (تازگی، تکرار و مبلغ خرید)',
      'ثبت یادداشت خصوصی برای هر مشتری (مثلاً: سایز سفارشی دارد، حساس به بسته‌بندی)',
      'اتصال مستقیم به پنل پیامکی کاوه‌نگار برای اطلاع‌رسانی اختصاصی',
    ],
    proTips: 'به مشتریان برچسب VIP در مناسبت‌های خاص کد تخفیف شخصی بدهید تا وفاداری آن‌ها دوچندان شود.',
  },
  {
    id: 'tasks',
    category: 'عملیات و کنترل',
    title: 'کارتابل و وظایف پرسنل',
    subtitle: 'تقسیم کار، پیگیری وظایف روزانه، ددلاین و یادآوری‌ها',
    href: '/tasks',
    icon: CheckSquare,
    accentColor: 'from-teal-500 to-emerald-600',
    description: 'میز کار اختصاصی پرسنل برای محول کردن کارهای روزانه (عکاسی کالا، بسته‌بندی سفارشات، ثبت فاکتور خرید، انبارگردانی).',
    whyNeeded: 'جلوگیری از فراموشی وظایف تیمی و مشخص بودن اینکه چه کسی مسئول انجام چه کاری بوده و در چه مرحله‌ای است.',
    howToUse: [
      'روی «ایجاد وظیفه جدید» کلیک کنید، عنوان کار و توضیحات لازم را بنویسید.',
      'همکار مسئول، تاریخ مهلت انجام (ددلاین) و سطح اهمیت را تعیین کنید.',
      'با شروع کار، وضعیت وظیفه را به «در حال انجام» و پس از اتمام به «تکمیل‌شده» ببرید.',
    ],
    keyFeatures: [
      'نمایش وضعیت کارها به صورت ستونی (Kanban) و فهرستی',
      'فیلتر سریع کارهای من، کارهای با اولویت بالا و کارهای عقب‌افتاده',
      'امکان اتصال وظیفه به یک سفارش یا مشتری مشخص',
    ],
    proTips: 'برای کارهای پرتکرار مثل بسته‌بندی صبحگاهی یا بررسی فیش‌ها، وظایف روزانه تعریف کنید.',
  },
  {
    id: 'social_calendar',
    category: 'بازاریابی و رسانه',
    title: 'تقویم محتوا و رسانه‌ها',
    subtitle: 'برنامه‌ریزی پست و استوری اینستاگرام و کمپین‌های سوشال',
    href: '/social/calendar',
    icon: Calendar,
    accentColor: 'from-pink-500 to-rose-500',
    description: 'تقویم تصویری شمسی برای زمان‌بندی انتشار محتوا، مسابقات، استوری‌های روزمره و هماهنگی بلاگرها و تبلیغات.',
    whyNeeded: 'برای اینکه محتوای پیج شما پیوسته و منظم باشد و تیم تولید محتوا از قبل بداند چه روزی قرار است چه پستی منتشر شود.',
    howToUse: [
      'روی روز مورد نظر در تقویم کلیک کنید و گزینه «افزودن محتوا» را بزنید.',
      'نوع محتوا (پست اسلایدی، ریلز، استوری، تبلیغ) و ساعت انتشار را تعیین کنید.',
      'کپشن، هشتگ‌ها و کالای مرتبط از کاتالوگ را به آن متصل کنید.',
      'وضعیت محتوا (ایده اولیه، در حال ضبط، آماده انتشار، منتشرشده) را دنبال کنید.',
    ],
    keyFeatures: [
      'نمایش تقویم شمسی با تفکیک رنگی نوع محتوا',
      'اتصال مستقیم به محصولات کاتالوگ برای برآورد موجودی قبل از کمپین تبلیغاتی',
      'همگام‌سازی با اینستاگرام تجاری در صورت اتصال فعال',
    ],
    proTips: 'قبل از شروع هر کمپین بلاگری، موجودی انبار را با محتوای تقویم بسنجید تا با ناموجودی غافلگیر نشوید.',
  },
  {
    id: 'marketing',
    category: 'بازاریابی و رسانه',
    title: 'تخفیف‌ها، کوپن و اتوماسیون',
    subtitle: 'ایجاد کدهای تخفیف درصدی/مبلغی و قوانین هوشمند خودکار',
    href: '/marketing',
    icon: Tag,
    accentColor: 'from-amber-500 to-red-500',
    description: 'مرکز ابزارهای افزایش فروش شامل ساخت کوپن تخفیف با شرایط خاص و ساخت قوانین خودکار (Outbox Engine).',
    whyNeeded: 'برای ایجاد هیجان خرید در مشتریان، اجرای جشنواره‌های فصلی و خودکارسازی فرآیندهای تکراری مانند ارسال پیامک پس از اولین خرید.',
    howToUse: [
      'برای کوپن جدید: کد کوپن (مثلاً BAHAR1403)، درصد یا مبلغ تخفیف و حداقل سبد خرید را تعیین کنید.',
      'تاریخ انقضا و حداکثر تعداد استفاده را محدود کنید.',
      'در بخش اتوماسیون، قواعد هوشمند تعریف کنید (مثال: اگر فیش تایید شد -> پیامک لینک رهگیری ارسال شود).',
    ],
    keyFeatures: [
      'محدودسازی کوپن به دسته‌بندی‌های خاص یا مشتریان اولی',
      'موتور اتوماسیون رویدادمحور بر پایه معماری فوق‌امن Outbox Pattern',
      'امکان Replay و تلاش مجدد خودکار در صورت بروز خطای مقطعی شبکه',
    ],
    proTips: 'از کوپن‌های دارای تاریخ انقضای محدود (مثلاً ۴۸ ساعته) برای تبدیل سریع‌تر مشتریان مردد استفاده کنید.',
  },
  {
    id: 'intelligence',
    category: 'هوش تجاری و تصمیم‌گیری',
    title: 'هوش تجاری و پیش‌بینی فروش',
    subtitle: 'تحلیل پرفروش‌ترین‌ها، پیش‌بینی کسری کالا با دستیار هوشمند',
    href: '/intelligence',
    icon: Sparkles,
    accentColor: 'from-violet-500 to-purple-600',
    description: 'مغز متفکر کسب‌وکار شما؛ داده‌های فروش گذشته را تحلیل می‌کند و به شما می‌گوید چه کالایی به‌زودی تمام می‌شود یا کدام دسته بیشترین سود را ساخته است.',
    whyNeeded: 'برای اینکه بر اساس حدس و گمان خرید عمده نکنید و بدانید چه کالاهایی واقعاً پول‌ساز هستند و سرمایه‌تان در چه اجناسی خوابیده است.',
    howToUse: [
      'گزارش اقلام پرفروش و پرسود را بررسی کنید.',
      'توصیه‌های هوش مصنوعی درباره زمان و تعداد سفارش مجدد کالاها را مشاهده کنید.',
      'از دستیار متنی سوالات تجاری بپرسید (مثلاً: حاشیه سود این ماه من با ماه قبل چه فرقی کرده؟).',
    ],
    keyFeatures: [
      'تحلیل چرخه گردش موجودی و شناسایی کالاهای راکد (Dead Stock)',
      'پیش‌بینی اتمام موجودی بر اساس سرعت فروش روزهای اخیر',
      'گزارش‌های شفاف و مصور نموداری',
    ],
    proTips: 'کالاهایی که برچسب «راکد» خورده‌اند را با یک تخفیف یا باندل محصولی سریع‌تر نقد کنید.',
  },
  {
    id: 'team',
    category: 'مدیریت و دسترسی‌ها',
    title: 'تیم و مدیریت دسترسی‌ها',
    subtitle: 'تعریف کارمندان، صندوقدار، انباردار و تعیین اختیارات',
    href: '/team',
    icon: Users,
    accentColor: 'from-blue-500 to-indigo-600',
    description: 'افزودن اعضای تیم فروشگاه و اعطای نقش‌های امنیتی مستقل به هر یک از آن‌ها.',
    whyNeeded: 'برای اینکه صندوقدار یا انباردار نتواند سود خالص فروشگاه یا اطلاعات مالی محرمانه را ببیند و هر کس فقط به بخش خودش دسترسی داشته باشد.',
    howToUse: [
      'روی «افزودن عضو جدید» کلیک کرده و نام، شماره موبایل و نقش او را انتخاب کنید.',
      'نقش‌های پیش‌فرض: مالک (Owner)، مدیر کسب‌وکار (Admin)، انباردار (Warehouse)، صندوقدار (POS)، ادمین پیام‌ها (Support).',
      'در صورت نیاز، دسترسی‌های اختصاصی هر نقش را سفارشی‌سازی کنید.',
    ],
    keyFeatures: [
      'سطوح دسترسی سازمانی (Enterprise RBAC)',
      'ثبت لاگ و ردپای تمام اقدامات پرسنل (Audit Trail)',
      'قطع دسترسی فوری در صورت قطع همکاری با پرسنل',
    ],
    proTips: 'هرگز رمز حساب کاربری مدیریت ارشد را در اختیار پرسنل قرار ندهید؛ برای هر فرد یک اکانت مستقل با نقش مناسب بسازید.',
  },
  {
    id: 'integrations',
    category: 'سیستم و ارتباطات فنی',
    title: 'اتصال‌ها و یکپارچه‌سازی‌ها',
    subtitle: 'راه‌اندازی پیامک کاوه‌نگار، زرین‌پال، پست و اینستاگرام',
    href: '/settings/integrations',
    icon: Link2,
    accentColor: 'from-cyan-500 to-blue-600',
    description: 'مرکز اتصال فروشگاه به ابزارهای بیرونی دنیای واقعی بدون نیاز به دست‌زدن به کدهای سرور یا کمک برنامه‌نویس.',
    whyNeeded: 'برای اینکه پیامک‌ها خودکار بروند، درگاه بانکی مستقیم به حساب شما وصل باشد و بسته‌های پستی رهگیری شوند.',
    howToUse: [
      'کارت سرویس مورد نظر (مثلاً درگاه پرداخت زرین‌پال یا پنل کاوه‌نگار) را پیدا کنید.',
      'کلید API یا مرچنت کد اختصاصی خود را وارد کنید.',
      'دکمه «تست زنده اتصال» را بزنید تا سامانه سلامت ارتباط را بررسی و تایید کند.',
      'پس از تایید سبز شدن وضعیت، سیستم آماده عملیات خودکار است.',
    ],
    keyFeatures: [
      'تست زنده و اعتبارسنجی اتصال قبل از ورود به فاز عملیاتی',
      'حفاظت فوق‌امنیتی رمزنگاری اطلاعات حساس و کلیدها',
      'امکان ارسال پیامک آزمایشی به شماره مدیر برای راستی‌آزمایی خط خدماتی',
    ],
    proTips: 'از فرم ارسال پیامک آزمایشی در این بخش استفاده کنید تا مطمئن شوید خط پیامکی شما بلک‌لیست مخابراتی نیست.',
  },
  {
    id: 'features',
    category: 'مدیریت و دسترسی‌ها',
    title: 'تنظیمات و ماژول‌ها',
    subtitle: 'فعال‌سازی ماژولار امکانات، پلن‌های اشتراک و شخصی‌سازی',
    href: '/settings/features',
    icon: Settings,
    accentColor: 'from-slate-500 to-zinc-600',
    description: 'کنترل‌پنل معماری ماژولار شاپ‌پایلوت؛ هر فروشگاه بسته به اندازه خود می‌تواند ماژول‌های مورد نیازش را روشن یا خاموش کند.',
    whyNeeded: 'اگر به یک قابلیت (مثلاً B2B یا اینستاگرام) فعلاً نیاز ندارید، می‌توانید آن را خاموش نگه دارید تا محیط کاربری خلوت‌تر و ساده‌تر بماند.',
    howToUse: [
      'فهرست ماژول‌های فعال و غیرفعال را در دسته‌بندی‌های مختلف مرور کنید.',
      'کلید روشن/خاموش هر ماژول را برای فعال یا غیرفعال‌سازی آن فشار دهید.',
      'سیستم به طور خودکار وابستگی‌های هر ماژول را بررسی کرده و راهنمایی می‌کند.',
    ],
    keyFeatures: [
      'پایش خودکار وابستگی ماژول‌ها (Dependency Graph Engine)',
      'سوییچ و ارتقای اشتراک پلن با پرداخت الکترونیکی',
      'حفظ کامل داده‌ها حتی در صورت غیرفعال‌سازی موقت یک ماژول',
    ],
    proTips: 'ماژول‌های پایه‌ای مثل کاتالوگ و انبار همواره روشن هستند و ارکان حیاتی سیستم را تشکیل می‌دهند.',
  },
];

const CATEGORIES = [
  'همه دسته‌ها',
  'عملیات و کنترل',
  'هسته انبار و کالا',
  'فروش و ثبت فاکتور',
  'خدمات پس از فروش',
  'مالی و زنجیره تامین',
  'مشتریان و ارتباطات',
  'بازاریابی و رسانه',
  'هوش تجاری و تصمیم‌گیری',
  'مدیریت و دسترسی‌ها',
  'سیستم و ارتباطات فنی',
];

export default function GuidePage() {
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('همه دسته‌ها');

  const filteredItems = GUIDE_ITEMS.filter((item) => {
    const matchesCategory =
      selectedCategory === 'همه دسته‌ها' || item.category === selectedCategory;
    const matchesSearch =
      search.trim() === '' ||
      item.title.toLowerCase().includes(search.toLowerCase()) ||
      item.subtitle.toLowerCase().includes(search.toLowerCase()) ||
      item.description.toLowerCase().includes(search.toLowerCase()) ||
      item.keyFeatures.some((k) => k.toLowerCase().includes(search.toLowerCase())) ||
      item.howToUse.some((h) => h.toLowerCase().includes(search.toLowerCase()));

    return matchesCategory && matchesSearch;
  });

  return (
    <div className="space-y-8 max-w-7xl mx-auto p-4 md:p-6" dir="rtl">
      {/* Hero Banner */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-r from-blue-900/40 via-cyan-900/20 to-slate-900/60 border border-white/[0.08] p-6 md:p-8 backdrop-blur-2xl shadow-2xl">
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-3 max-w-2xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/20 text-cyan-400 text-xs font-bold">
              <BookOpen className="w-3.5 h-3.5" />
              <span>مرکز راهنمایی و آموزش جامع شاپ‌پایلوت</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-black text-white tracking-tight">
              راهنمای گام‌به‌گام کار با پلتفرم شاپ‌پایلوت
            </h1>
            <p className="text-sm text-slate-300 leading-relaxed">
              این پلتفرم برای مدیریت صفر تا صد آنلاین‌شاپ و فروشگاه شما طراحی شده است. در این صفحه می‌توانید با هدف هر بخش، نحوه استفاده عملیاتی و ترفندهای کاربردی آن به زبان ساده آشنا شوید.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <Link
              href="/settings/features"
              className="inline-flex items-center justify-center gap-2 bg-white/[0.05] hover:bg-white/[0.1] text-slate-200 border border-white/10 px-4 py-2.5 rounded-xl text-xs font-semibold transition"
            >
              <Settings className="w-4 h-4 text-cyan-400" />
              <span>مدیریت ماژول‌ها</span>
            </Link>
            <Link
              href="/settings/integrations"
              className="inline-flex items-center justify-center gap-2 bg-cyan-600 hover:bg-cyan-500 text-white px-4 py-2.5 rounded-xl text-xs font-bold transition shadow-[0_0_15px_rgba(6,182,212,0.4)]"
            >
              <Zap className="w-4 h-4" />
              <span>پیکربندی اتصال‌ها</span>
            </Link>
          </div>
        </div>
      </div>

      {/* Search and Category Filters */}
      <div className="space-y-4">
        {/* Search Input */}
        <div className="relative">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="جستجو در آموزش‌ها (مثال: فیش واریزی، بارکد، درگاه، کوپن، انبار، ثبت سفارش)..."
            className="w-full bg-[#0b101d]/90 dark:bg-[#0b101d]/90 light:bg-white border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-white light:text-slate-900 rounded-2xl pr-11 pl-4 py-3 text-sm focus:ring-2 focus:ring-cyan-500 outline-none transition shadow-sm backdrop-blur-xl"
          />
          <Search className="w-5 h-5 text-slate-400 absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>

        {/* Category Pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-none">
          {CATEGORIES.map((cat) => {
            const isSelected = selectedCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={cn(
                  'px-3.5 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all cursor-pointer',
                  isSelected
                    ? 'bg-cyan-600 text-white shadow-[0_0_15px_rgba(6,182,212,0.4)] border border-cyan-400/40'
                    : 'bg-white/[0.03] dark:bg-white/[0.03] light:bg-slate-100 text-slate-400 light:text-slate-600 hover:text-white light:hover:text-slate-900 hover:bg-white/[0.06] border border-white/[0.05] light:border-slate-200'
                )}
              >
                {cat}
              </button>
            );
          })}
        </div>
      </div>

      {/* Modules Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {filteredItems.map((item) => {
          const Icon = item.icon;
          return (
            <div
              key={item.id}
              className="bg-[#0b101d]/90 dark:bg-[#0b101d]/90 light:bg-white border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 rounded-3xl p-6 shadow-xl backdrop-blur-2xl flex flex-col justify-between space-y-5 hover:border-cyan-500/30 transition-all duration-300 group"
            >
              <div className="space-y-4">
                {/* Header */}
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        'w-12 h-12 rounded-2xl bg-gradient-to-tr flex items-center justify-center text-white shadow-lg shrink-0',
                        item.accentColor
                      )}
                    >
                      <Icon className="w-6 h-6" />
                    </div>
                    <div>
                      <div className="text-[11px] font-bold text-cyan-400 uppercase tracking-wider">
                        {item.category}
                      </div>
                      <h2 className="text-lg font-bold text-white light:text-slate-900 mt-0.5">
                        {item.title}
                      </h2>
                    </div>
                  </div>

                  <Link
                    href={item.href}
                    className="p-2 rounded-xl bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 hover:bg-cyan-500/20 text-slate-400 hover:text-cyan-300 transition-colors shrink-0"
                    title={`ورود به ${item.title}`}
                  >
                    <ExternalLink className="w-4 h-4" />
                  </Link>
                </div>

                <p className="text-xs font-semibold text-slate-300 light:text-slate-700">
                  {item.subtitle}
                </p>

                <p className="text-xs text-slate-400 light:text-slate-600 leading-relaxed">
                  {item.description}
                </p>

                {/* Why needed */}
                <div className="bg-white/[0.02] dark:bg-white/[0.02] light:bg-slate-50 border border-white/[0.04] light:border-slate-100 rounded-2xl p-3.5 space-y-1">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-amber-400">
                    <HelpCircle className="w-3.5 h-3.5" />
                    <span>چرا به این بخش نیاز داریم؟</span>
                  </div>
                  <p className="text-xs text-slate-300 light:text-slate-600 leading-relaxed">
                    {item.whyNeeded}
                  </p>
                </div>

                {/* How to use */}
                <div className="space-y-2">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-cyan-400">
                    <Compass className="w-3.5 h-3.5" />
                    <span>چگونه با آن کار کنیم؟ (گام‌به‌گام)</span>
                  </div>
                  <ul className="space-y-1.5 pr-2">
                    {item.howToUse.map((step, idx) => (
                      <li
                        key={idx}
                        className="text-xs text-slate-300 light:text-slate-600 flex items-start gap-2"
                      >
                        <span className="w-4 h-4 rounded-full bg-cyan-500/10 text-cyan-400 text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5 border border-cyan-500/20">
                          {idx + 1}
                        </span>
                        <span className="leading-relaxed">{step}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Key features */}
                <div className="space-y-1.5 pt-1">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-400">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>امکانات و قابلیت‌های کلیدی:</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {item.keyFeatures.map((feat, idx) => (
                      <span
                        key={idx}
                        className="text-[11px] bg-white/[0.03] dark:bg-white/[0.03] light:bg-slate-100 border border-white/[0.06] light:border-slate-200 text-slate-300 light:text-slate-700 px-2.5 py-1 rounded-lg"
                      >
                        {feat}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Pro tip */}
                <div className="bg-cyan-500/[0.05] border border-cyan-500/20 rounded-2xl p-3 flex items-start gap-2.5">
                  <Lightbulb className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
                  <p className="text-xs text-cyan-200 light:text-cyan-900 leading-relaxed">
                    <strong className="font-bold text-cyan-300 ml-1">نکته حرفه‌ای:</strong>
                    {item.proTips}
                  </p>
                </div>
              </div>

              {/* Bottom Action */}
              <div className="pt-3 border-t border-white/[0.06] light:border-slate-100">
                <Link
                  href={item.href}
                  className="w-full inline-flex items-center justify-center gap-2 bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 hover:bg-cyan-600 hover:text-white light:hover:bg-cyan-600 light:hover:text-white text-slate-300 light:text-slate-700 font-bold text-xs py-2.5 rounded-xl transition duration-200 group-hover:border-cyan-500/30"
                >
                  <span>ورود به صفحه {item.title}</span>
                  <ArrowRight className="w-3.5 h-3.5 rotate-180" />
                </Link>
              </div>
            </div>
          );
        })}
      </div>

      {filteredItems.length === 0 && (
        <div className="text-center py-16 bg-[#0b101d]/60 rounded-3xl border border-white/[0.06] p-8 space-y-3">
          <HelpCircle className="w-12 h-12 text-slate-600 mx-auto" />
          <h3 className="text-base font-bold text-white">موردی برای جستجوی شما یافت نشد</h3>
          <p className="text-xs text-slate-400">
            لطفاً عبارت دیگری را جستجو کنید یا فیلتر دسته‌بندی را روی «همه دسته‌ها» قرار دهید.
          </p>
        </div>
      )}
    </div>
  );
}
