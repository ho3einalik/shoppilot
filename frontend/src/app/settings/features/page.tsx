'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Layers,
  CheckCircle2,
  AlertTriangle,
  SlidersHorizontal,
  Shield,
  Zap,
  Info,
  Check,
  X,
  ExternalLink,
  Lock,
  ArrowRight,
  RefreshCw,
  Sparkles,
  Bot,
  MessageSquare,
  Smartphone,
  Share2,
  BookOpen
} from 'lucide-react';
import { api } from '@/lib/api';

interface FeatureItem {
  key: string;
  name_fa: string;
  description_fa: string;
  category: string;
  is_core: boolean;
  is_entitled: boolean;
  is_active: boolean;
  min_tier: string;
  depends_on: string[];
  missing_dependencies: string[];
  dependents: string[];
  integrations: string[];
  impact_warning_fa: string;
}

interface IntegrationItem {
  name: string;
  display_name_fa: string;
  description_fa: string;
  status: string;
  is_ready: boolean;
  message: string;
}

const CATEGORIES = [
  { id: 'ALL', label: 'همه ماژول‌ها' },
  { id: 'CORE', label: 'پایه و انبارداری' },
  { id: 'OPERATIONS', label: 'عملیات و وظایف' },
  { id: 'TEAM', label: 'تیم و دسترسی‌ها' },
  { id: 'SOCIAL', label: 'شبکه‌های اجتماعی' },
  { id: 'AI', label: 'هوش مصنوعی' },
  { id: 'MARKETING', label: 'بازاریابی و مشتریان' },
];

const TIERS = [
  { id: 'FREE', label: 'طرح رایگان (Free)', desc: 'کاتالوگ، سفارشات و انبار پایه' },
  { id: 'STARTER', label: 'طرح شروع (Starter)', desc: 'مدیریت تیم، کارتابل وظایف و تقویم محتوا' },
  { id: 'PRO', label: 'طرح حرفه‌ای (Pro)', desc: 'انتشار خودکار اینستاگرام، وظایف دوره‌ای و باشگاه مشتریان' },
  { id: 'ENTERPRISE', label: 'طرح سازمانی (Enterprise)', desc: 'پیش‌بینی هوشمند، چندین انبار و دستیار دایرکت' },
];

export default function FeaturesSettingsPage() {
  const [catalog, setCatalog] = useState<{
    tier: string;
    tier_display: string;
    features: FeatureItem[];
  } | null>(null);
  const [integrations, setIntegrations] = useState<Record<string, IntegrationItem>>({});
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState('ALL');
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error' | 'warning'; message: string } | null>(null);
  const [confirmModal, setConfirmModal] = useState<{
    feature: FeatureItem;
    targetState: boolean;
  } | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [catalogRes, integRes] = await Promise.all([
        api.getFeatureCatalog(),
        api.getIntegrations(),
      ]);
      setCatalog(catalogRes);
      setIntegrations(integRes);
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'خطا در بارگذاری تنظیمات ماژول‌ها' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();

    // Check if redirected back from payment gateway
    if (typeof window !== 'undefined') {
      const queryParams = new URLSearchParams(window.location.search);
      const authority = queryParams.get('Authority') || queryParams.get('authority');
      if (authority) {
        api.verifySubscriptionInvoice({ authority })
          .then((res: any) => {
            setFeedback({
              type: 'success',
              message: res.message || 'پرداخت اشتراک با موفقیت تأیید شد و پلن فروشگاه ارتقا یافت.'
            });
            fetchData();
          })
          .catch((err: any) => {
            setFeedback({
              type: 'error',
              message: err.message || 'خطا در تأیید پرداخت درگاه اشتراک'
            });
          });
      }
    }
  }, []);

  const handleToggleClick = (feature: FeatureItem) => {
    if (feature.is_core) return;

    if (feature.is_active) {
      // Deactivating: show confirmation modal with impact warning
      setConfirmModal({ feature, targetState: false });
    } else {
      // Activating: check entitlement first
      if (!feature.is_entitled) {
        setFeedback({
          type: 'warning',
          message: `این ماژول نیازمند ارتقای پلن اشتراک به ${feature.min_tier} است.`
        });
        return;
      }
      if (feature.missing_dependencies.length > 0) {
        setFeedback({
          type: 'warning',
          message: `برای فعال‌سازی این ماژول ابتدا باید پیش‌نیازهای آن را فعال نمایید.`
        });
        return;
      }
      executeToggle(feature.key, true);
    }
  };

  const executeToggle = async (featureKey: string, enabled: boolean) => {
    try {
      setActionLoading(true);
      setConfirmModal(null);
      const res = await api.toggleFeature(featureKey, enabled);
      setFeedback({
        type: 'success',
        message: res.message || (enabled ? 'ماژول با موفقیت فعال شد.' : 'ماژول با موفقیت غیرفعال شد.')
      });
      await fetchData();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'خطا در تغییر وضعیت ماژول' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleTierChange = async (tier: string) => {
    try {
      setActionLoading(true);
      // Try direct tier update (works for downgrades, platform staff, or DEBUG mode)
      try {
        await api.updateSubscriptionTier(tier);
        setFeedback({ type: 'success', message: `پلن اشتراک فروشگاه به ${tier} تغییر یافت.` });
        await fetchData();
        return;
      } catch (directErr: any) {
        // If direct change is forbidden due to invoice requirement, initiate checkout invoice
        const invoice = await api.createSubscriptionInvoice({ tier, billing_cycle: 'MONTHLY' });
        const currentUrl = typeof window !== 'undefined' ? window.location.href.split('?')[0] : '';
        const checkout = await api.checkoutSubscriptionInvoice(invoice.id, {
          callback_url: currentUrl,
        });

        if (checkout.payment_url) {
          window.location.href = checkout.payment_url;
          return;
        } else {
          setFeedback({
            type: 'warning',
            message: `فاکتور ارتقای پلن به شماره ${invoice.invoice_number || invoice.id} صادر گردید.`
          });
          await fetchData();
        }
      }
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'خطا در ارتقای پلن اشتراک' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleSimulateIntegration = async (name: string, state: string) => {
    try {
      setActionLoading(true);
      await api.configureIntegration(name, state);
      setFeedback({ type: 'success', message: `وضعیت اتصال سرویس '${name}' به‌روزرسانی شد.` });
      await fetchData();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'خطا در تنظیم سرویس' });
    } finally {
      setActionLoading(false);
    }
  };

  const filteredFeatures = catalog?.features.filter((f) => {
    if (selectedCategory === 'ALL') return true;
    return f.category === selectedCategory;
  }) || [];

  return (
    <div className="space-y-8 max-w-7xl mx-auto p-4 md:p-6" dir="rtl">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-sky-500/10 border border-sky-500/20 flex items-center justify-center text-sky-400">
              <SlidersHorizontal className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">مدیریت ماژول‌ها و اشتراک</h1>
              <p className="text-xs text-slate-400 mt-0.5">
                فعال‌سازی ماژولار قابلیت‌ها، بررسی وابستگی‌ها و مدیریت تاب‌آوری سرویس‌ها
              </p>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Link to Full User Guide */}
          <Link
            href="/settings/guide"
            className="inline-flex items-center gap-2 bg-gradient-to-r from-cyan-500/20 to-blue-600/20 hover:from-cyan-500/30 hover:to-blue-600/30 text-cyan-300 border border-cyan-500/30 px-3.5 py-2.5 rounded-2xl text-xs font-bold transition shadow-sm"
          >
            <BookOpen className="w-4 h-4" />
            <span>راهنما و آموزش جامع ماژول‌ها</span>
          </Link>

          {/* Current Plan Badge & Tier Switcher */}
          <div className="flex flex-wrap items-center gap-3 bg-slate-900/90 border border-slate-800 p-2.5 rounded-2xl">
          <div className="text-xs text-slate-400 font-medium px-2">
            پلن فعلی:
            <span className="text-sky-400 font-bold mr-1">
              {catalog?.tier_display || catalog?.tier || 'در حال بارگذاری...'}
            </span>
          </div>
          <div className="flex items-center gap-1 bg-slate-800/80 p-1 rounded-xl">
            {TIERS.map((t) => (
              <button
                key={t.id}
                onClick={() => handleTierChange(t.id)}
                disabled={actionLoading || catalog?.tier === t.id}
                className={`text-[11px] px-2.5 py-1 rounded-lg transition-all font-medium ${
                  catalog?.tier === t.id
                    ? 'bg-sky-600 text-white shadow-sm'
                    : 'text-slate-400 hover:text-white hover:bg-slate-700/60'
                }`}
                title={t.desc}
              >
                {t.id}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>

      {/* Feedback Banner */}
      {feedback && (
        <div
          className={`flex items-center justify-between p-4 rounded-xl border text-xs ${
            feedback.type === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
              : feedback.type === 'warning'
              ? 'bg-amber-500/10 border-amber-500/20 text-amber-300'
              : 'bg-rose-500/10 border-rose-500/20 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2">
            {feedback.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 shrink-0" />
            ) : feedback.type === 'warning' ? (
              <AlertTriangle className="w-4 h-4 shrink-0" />
            ) : (
              <X className="w-4 h-4 shrink-0" />
            )}
            <span>{feedback.message}</span>
          </div>
          <button onClick={() => setFeedback(null)} className="text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Category Tabs */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-none">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            onClick={() => setSelectedCategory(cat.id)}
            className={`px-3.5 py-2 rounded-xl text-xs font-medium whitespace-nowrap transition-all ${
              selectedCategory === cat.id
                ? 'bg-sky-600 text-white shadow-sm shadow-sky-900/50'
                : 'bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800/60'
            }`}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* Features Grid */}
      {loading ? (
        <div className="flex items-center justify-center p-12 text-slate-400 text-sm gap-3">
          <RefreshCw className="w-5 h-5 animate-spin text-sky-400" />
          <span>در حال دریافت کاتالوگ ماژول‌ها...</span>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {filteredFeatures.map((feat) => {
            const isMissingDeps = feat.missing_dependencies.length > 0;
            const canToggle = !feat.is_core && (feat.is_active || (feat.is_entitled && !isMissingDeps));

            return (
              <div
                key={feat.key}
                className={`bg-slate-900/80 border rounded-2xl p-5 flex flex-col justify-between transition-all duration-200 ${
                  feat.is_active
                    ? 'border-slate-800 hover:border-slate-700 shadow-sm'
                    : 'border-slate-800/60 opacity-80 hover:opacity-100'
                }`}
              >
                <div>
                  {/* Top Bar of Card */}
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${
                            feat.is_core
                              ? 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20'
                              : feat.category === 'SOCIAL'
                              ? 'bg-pink-500/10 text-pink-400 border border-pink-500/20'
                              : feat.category === 'AI'
                              ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20'
                              : feat.category === 'OPERATIONS'
                              ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                              : 'bg-sky-500/10 text-sky-400 border border-sky-500/20'
                          }`}
                        >
                          {feat.category}
                        </span>
                        {!feat.is_entitled && (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20">
                            نیازمند پلن {feat.min_tier}
                          </span>
                        )}
                      </div>
                      <h3 className="text-sm font-bold text-white mt-1.5">{feat.name_fa}</h3>
                    </div>

                    {/* Toggle Switch */}
                    {feat.is_core ? (
                      <div className="flex items-center gap-1 text-[11px] text-slate-500 bg-slate-800/50 px-2 py-1 rounded-lg">
                        <Lock className="w-3.5 h-3.5 text-slate-400" />
                        <span>پایه</span>
                      </div>
                    ) : (
                      <button
                        onClick={() => handleToggleClick(feat)}
                        disabled={actionLoading}
                        className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                          feat.is_active ? 'bg-sky-600' : 'bg-slate-700'
                        }`}
                        title={feat.is_active ? 'غیرفعال‌سازی ماژول' : 'فعال‌سازی ماژول'}
                      >
                        <span
                          className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow-lg ring-0 transition duration-200 ease-in-out ${
                            feat.is_active ? '-translate-x-5' : 'translate-x-0'
                          }`}
                        />
                      </button>
                    )}
                  </div>

                  {/* Description */}
                  <p className="text-xs text-slate-400 leading-relaxed min-h-[38px] mb-4">
                    {feat.description_fa}
                  </p>

                  {/* Dependencies Section */}
                  {feat.depends_on.length > 0 && (
                    <div className="mb-3 pt-3 border-t border-slate-800/60">
                      <div className="text-[11px] text-slate-400 mb-1.5 flex items-center gap-1">
                        <Info className="w-3 h-3 text-slate-500" />
                        <span>پیش‌نیازهای فعال‌سازی:</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {feat.depends_on.map((dep) => {
                          const isMissing = feat.missing_dependencies.includes(dep);
                          return (
                            <span
                              key={dep}
                              className={`text-[10px] px-2 py-0.5 rounded-md flex items-center gap-1 ${
                                isMissing
                                  ? 'bg-rose-500/10 text-rose-300 border border-rose-500/20'
                                  : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                              }`}
                            >
                              {isMissing ? <X className="w-2.5 h-2.5" /> : <Check className="w-2.5 h-2.5" />}
                              <span>{dep}</span>
                            </span>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {/* Active Dependents Note */}
                  {feat.dependents.length > 0 && feat.is_active && (
                    <div className="text-[10px] text-slate-500 mb-2">
                      <span>ماژول‌های متکی به این ویژگی: {feat.dependents.join(', ')}</span>
                    </div>
                  )}
                </div>

                {/* Footer Status */}
                <div className="pt-3 border-t border-slate-800/60 flex items-center justify-between text-[11px]">
                  <span className="text-slate-500">حداقل پلن: {feat.min_tier}</span>
                  <span
                    className={`font-semibold flex items-center gap-1 ${
                      feat.is_active ? 'text-emerald-400' : 'text-slate-500'
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${
                        feat.is_active ? 'bg-emerald-400' : 'bg-slate-500'
                      }`}
                    />
                    {feat.is_active ? 'فعال' : 'غیرفعال'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* External Integrations Hub */}
      <div className="bg-slate-900 border border-slate-800 rounded-3xl p-6 mt-10">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-800 pb-4 mb-6">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Zap className="w-5 h-5 text-amber-400" />
              <span>اتصال سرویس‌های خارجی و آداپتورهای مستقل</span>
            </h2>
            <p className="text-xs text-slate-400 mt-1">
              در صورت قطعی یا عدم اتصال هر سرویس، سیستم به صورت خودکار به وضعیت تاب‌آور (Graceful Fallback) تغییر وضعیت می‌دهد.
            </p>
          </div>
          <a
            href="/settings/integrations"
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-xs font-bold text-white transition-colors shadow-sm shadow-blue-950 shrink-0"
          >
            <span>مدیریت کامل اتصال‌ها و کلیدها</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {Object.entries(integrations || {}).map(([name, integ]) => {
            const isInstagram = name === 'instagram';
            const isAI = name === 'ai_provider';
            const isSMS = name === 'sms_gateway';

            return (
              <div
                key={name}
                className="bg-slate-950/60 border border-slate-800/80 rounded-2xl p-5 flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="w-8 h-8 rounded-xl bg-slate-800 flex items-center justify-center text-slate-300">
                      {isInstagram ? (
                        <Share2 className="w-4 h-4 text-pink-400" />
                      ) : isAI ? (
                        <Bot className="w-4 h-4 text-purple-400" />
                      ) : (
                        <Smartphone className="w-4 h-4 text-sky-400" />
                      )}
                    </div>
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                        integ.status === 'CONNECTED'
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : integ.status === 'NOT_CONFIGURED'
                          ? 'bg-slate-800 text-slate-400'
                          : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                      }`}
                    >
                      {integ.status}
                    </span>
                  </div>

                  <h4 className="text-sm font-bold text-white mb-1">{integ.display_name_fa}</h4>
                  <p className="text-xs text-slate-400 leading-relaxed mb-4">{integ.description_fa}</p>

                  <div className="p-3 rounded-xl bg-slate-900 border border-slate-800/60 text-[11px] text-slate-300 mb-4">
                    <span className="font-medium text-slate-400 block mb-0.5">وضعیت سلامت اتصال:</span>
                    <span>{integ.message}</span>
                  </div>
                </div>

                {/* State simulation actions for demo */}
                <div className="flex items-center gap-2 pt-3 border-t border-slate-800/60">
                  <button
                    onClick={() =>
                      handleSimulateIntegration(
                        name,
                        integ.status === 'CONNECTED' ? 'NOT_CONFIGURED' : 'CONNECTED'
                      )
                    }
                    disabled={actionLoading}
                    className="flex-1 py-1.5 px-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-[11px] font-medium text-slate-200 transition-colors"
                  >
                    {integ.status === 'CONNECTED' ? 'تست قطع موقت اتصال' : 'تست برقراری اتصال'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Confirmation Modal for Deactivating a Feature */}
      {confirmModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center mx-auto">
              <AlertTriangle className="w-6 h-6" />
            </div>

            <div className="text-center">
              <h3 className="text-base font-bold text-white">
                غیرفعال‌سازی ماژول {confirmModal.feature.name_fa}
              </h3>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                {confirmModal.feature.impact_warning_fa ||
                  'با غیرفعال‌سازی، دسترسی اعضا به این بخش موقتاً مسدود می‌شود.'}
              </p>
            </div>

            <div className="p-3.5 bg-sky-500/10 border border-sky-500/20 rounded-xl text-xs text-sky-300">
              <div className="flex items-center gap-2 font-bold mb-1">
                <Shield className="w-4 h-4 text-sky-400 shrink-0" />
                <span>اصل تضمین بقای داده‌ها (Data Preservation)</span>
              </div>
              <p className="text-[11px] text-sky-200/90 leading-relaxed">
                کلیه سوابق، جداول، محتواها و رکوردهای قبلی ثبت‌شده به هیچ عنوان حذف نمی‌شوند و به محض فعال‌سازی مجدد، بدون تغییر در دسترس خواهند بود.
              </p>
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                onClick={() => setConfirmModal(null)}
                className="flex-1 py-2.5 rounded-xl border border-slate-700 text-slate-300 hover:bg-slate-800 text-xs font-medium transition-colors"
              >
                انصراف
              </button>
              <button
                onClick={() => executeToggle(confirmModal.feature.key, false)}
                disabled={actionLoading}
                className="flex-1 py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold transition-colors shadow-sm shadow-rose-950"
              >
                تأیید غیرفعال‌سازی
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
