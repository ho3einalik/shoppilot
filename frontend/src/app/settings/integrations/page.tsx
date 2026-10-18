'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import {
  Link2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  ShieldCheck,
  Zap,
  Info,
  RefreshCw,
  ExternalLink,
  Lock,
  Eye,
  EyeOff,
  Smartphone,
  Share2,
  CreditCard,
  Truck,
  Mail,
  Bot,
  Layers,
  ChevronLeft,
  Send,
  Sliders,
  Check,
  X,
  SlidersHorizontal,
  HelpCircle,
  Sparkles
} from 'lucide-react';
import { api } from '@/lib/api';

interface SchemaField {
  name: string;
  label_fa: string;
  type: 'text' | 'password' | 'number' | 'boolean' | 'select' | 'url';
  required: boolean;
  is_secret: boolean;
  help_text_fa?: string;
  placeholder?: string;
  default?: any;
  options?: Array<{ value: string; label: string }>;
}

interface IntegrationItem {
  id: string;
  name: string;
  category: string;
  display_name_fa: string;
  description_fa: string;
  guide_fa: string;
  status: string;
  is_active: boolean;
  is_ready: boolean;
  message: string;
  last_tested_at?: string;
  last_connected_at?: string;
  last_test_error?: string;
  last_test_success?: boolean;
  schema: SchemaField[];
  config: Record<string, any>;
}

const CATEGORIES = [
  { id: 'ALL', label: 'همه اتصال‌ها', icon: Layers },
  { id: 'SMS', label: 'پیامک و اعلان‌ها', icon: Smartphone },
  { id: 'SOCIAL', label: 'شبکه‌های اجتماعی', icon: Share2 },
  { id: 'PAYMENT', label: 'درگاه‌های پرداخت', icon: CreditCard },
  { id: 'SHIPPING', label: 'حمل‌ونقل و رهگیری', icon: Truck },
  { id: 'EMAIL', label: 'ایمیل و مکاتبات', icon: Mail },
  { id: 'AI', label: 'هوش مصنوعی', icon: Bot },
];

export default function IntegrationsManagementPage() {
  const [integrations, setIntegrations] = useState<IntegrationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedCategory, setSelectedCategory] = useState('ALL');
  const [activeConfigModal, setActiveConfigModal] = useState<IntegrationItem | null>(null);
  const [formValues, setFormValues] = useState<Record<string, any>>({});
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error' | 'warning'; message: string } | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  // Test SMS / Email Modal State
  const [testModal, setTestModal] = useState<{
    integration: IntegrationItem;
    type: 'SMS' | 'EMAIL';
    targetValue: string;
  } | null>(null);
  const [testActionLoading, setTestActionLoading] = useState(false);

  const fetchIntegrations = async () => {
    try {
      setLoading(true);
      const res = await api.getCanonicalIntegrations();
      setIntegrations(res);
      // If modal open, refresh its data
      if (activeConfigModal) {
        const updated = res.find((i) => i.id === activeConfigModal.id);
        if (updated) {
          setActiveConfigModal(updated);
        }
      }
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'خطا در بارگذاری لیست اتصال‌ها' });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIntegrations();
  }, []);

  const handleOpenConfig = (item: IntegrationItem) => {
    setActiveConfigModal(item);
    const initialValues: Record<string, any> = {};
    item.schema.forEach((field) => {
      initialValues[field.name] = item.config[field.name] ?? field.default ?? '';
    });
    setFormValues(initialValues);
    setShowSecrets({});
  };

  const handleSaveConfig = async () => {
    if (!activeConfigModal) return;
    try {
      setActionLoading(true);
      setFeedback(null);
      const res = await api.saveIntegrationConfig(activeConfigModal.id, formValues);
      setFeedback({ type: 'success', message: res.message });
      await fetchIntegrations();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'خطا در ذخیره تنظیمات' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleTestConnection = async (integrationId: string) => {
    try {
      setActionLoading(true);
      setFeedback(null);
      const res = await api.testIntegration(integrationId);
      setFeedback({
        type: res.success ? 'success' : 'error',
        message: res.message
      });
      await fetchIntegrations();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'خطا در اجرای تست اتصال' });
      await fetchIntegrations();
    } finally {
      setActionLoading(false);
    }
  };

  const handleToggleActivation = async (item: IntegrationItem) => {
    try {
      setActionLoading(true);
      setFeedback(null);
      if (item.is_active) {
        const res = await api.deactivateIntegration(item.id);
        setFeedback({ type: 'success', message: res.message });
      } else {
        const res = await api.activateIntegration(item.id);
        setFeedback({ type: 'success', message: res.message });
      }
      await fetchIntegrations();
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'عملیات فعال‌سازی یا غیرفعال‌سازی با خطا مواجه شد.' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleSendTestDispatch = async () => {
    if (!testModal) return;
    try {
      setTestActionLoading(true);
      if (testModal.type === 'SMS') {
        const res = await api.sendTestSMS(testModal.integration.id, testModal.targetValue);
        setFeedback({ type: 'success', message: res.message });
      } else {
        const res = await api.sendTestEmail(testModal.integration.id, testModal.targetValue);
        setFeedback({ type: 'success', message: res.message });
      }
      setTestModal(null);
    } catch (err: any) {
      setFeedback({ type: 'error', message: err.message || 'ارسال پیام آزمایشی ناموفق بود.' });
    } finally {
      setTestActionLoading(false);
    }
  };

  const filteredIntegrations = integrations.filter((item) => {
    if (selectedCategory === 'ALL') return true;
    return item.category === selectedCategory;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'ACTIVE':
      case 'CONNECTED':
        return {
          label: 'فعال و متصل',
          color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
          dot: 'bg-emerald-400',
        };
      case 'READY':
        return {
          label: 'تست موفق - آماده فعال‌سازی',
          color: 'bg-teal-500/10 text-teal-300 border-teal-500/20',
          dot: 'bg-teal-400',
        };
      case 'CONFIGURED':
        return {
          label: 'تنظیم شده - نیازمند تست',
          color: 'bg-sky-500/10 text-sky-400 border-sky-500/20',
          dot: 'bg-sky-400',
        };
      case 'TESTING':
        return {
          label: 'در حال تست اتصال...',
          color: 'bg-amber-500/10 text-amber-400 border-amber-500/20 animate-pulse',
          dot: 'bg-amber-400',
        };
      case 'TEST_FAILED':
        return {
          label: 'تست ناموفق',
          color: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
          dot: 'bg-rose-400',
        };
      case 'REAUTH_REQUIRED':
      case 'NEEDS_REAUTH':
        return {
          label: 'نیازمند اتصال مجدد',
          color: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
          dot: 'bg-purple-400',
        };
      case 'DISABLED':
      case 'DISABLED_BY_STORE':
        return {
          label: 'غیرفعال',
          color: 'bg-slate-800 text-slate-400 border-slate-700',
          dot: 'bg-slate-500',
        };
      case 'NOT_CONFIGURED':
      default:
        return {
          label: 'هنوز تنظیم نشده',
          color: 'bg-slate-800/80 text-slate-500 border-slate-800',
          dot: 'bg-slate-600',
        };
    }
  };

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'SMS':
        return <Smartphone className="w-5 h-5 text-sky-400" />;
      case 'SOCIAL':
        return <Share2 className="w-5 h-5 text-pink-400" />;
      case 'PAYMENT':
        return <CreditCard className="w-5 h-5 text-emerald-400" />;
      case 'SHIPPING':
        return <Truck className="w-5 h-5 text-amber-400" />;
      case 'EMAIL':
        return <Mail className="w-5 h-5 text-indigo-400" />;
      case 'AI':
        return <Bot className="w-5 h-5 text-purple-400" />;
      default:
        return <Zap className="w-5 h-5 text-slate-400" />;
    }
  };

  return (
    <div className="min-h-screen bg-[#070b14] text-slate-100 p-4 md:p-8 space-y-8" dir="rtl">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-800/80 pb-6">
        <div>
          <div className="flex items-center gap-2 text-xs text-slate-400 mb-1">
            <Link href="/settings/features" className="hover:text-blue-400 transition-colors">
              تنظیمات و ماژول‌ها
            </Link>
            <ChevronLeft className="w-3.5 h-3.5 text-slate-600" />
            <span className="text-slate-200 font-medium">اتصال‌ها و یکپارچه‌سازی‌ها</span>
          </div>
          <h1 className="text-2xl font-black text-white flex items-center gap-3">
            <Link2 className="w-7 h-7 text-blue-500" />
            <span>مرکز مدیریت اتصال‌ها و یکپارچه‌سازی‌ها</span>
          </h1>
          <p className="text-xs md:text-sm text-slate-400 mt-1.5 leading-relaxed max-w-3xl">
            پیکربندی، تست اعتبار و فعال‌سازی امن سرویس‌های پیامکی، شبکه‌های اجتماعی، درگاه پرداخت، شرکت‌های پستی و هوش مصنوعی مختص این فروشگاه بدون نیاز به تغییر دستی کد.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchIntegrations}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-slate-900 border border-slate-800 hover:bg-slate-800 text-xs font-medium text-slate-300 transition-all shadow-sm"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-blue-400' : ''}`} />
            <span>بروزرسانی وضعیت</span>
          </button>
        </div>
      </div>

      {/* Global Alert Notification */}
      {feedback && (
        <div
          className={`p-4 rounded-2xl border text-xs md:text-sm flex items-center justify-between gap-3 shadow-lg transition-all ${
            feedback.type === 'success'
              ? 'bg-emerald-950/40 border-emerald-500/30 text-emerald-300'
              : feedback.type === 'warning'
              ? 'bg-amber-950/40 border-amber-500/30 text-amber-300'
              : 'bg-rose-950/40 border-rose-500/30 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-2.5">
            {feedback.type === 'success' ? (
              <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
            ) : feedback.type === 'warning' ? (
              <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
            ) : (
              <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
            )}
            <span>{feedback.message}</span>
          </div>
          <button
            onClick={() => setFeedback(null)}
            className="p-1 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Categories Bar */}
      <div className="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-none">
        {CATEGORIES.map((cat) => {
          const Icon = cat.icon;
          const isSelected = selectedCategory === cat.id;
          return (
            <button
              key={cat.id}
              onClick={() => setSelectedCategory(cat.id)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-2xl text-xs font-semibold whitespace-nowrap transition-all border ${
                isSelected
                  ? 'bg-blue-600 text-white border-blue-500 shadow-[0_0_20px_rgba(37,99,235,0.4)]'
                  : 'bg-slate-900/80 hover:bg-slate-800 text-slate-300 border-slate-800/80 hover:border-slate-700'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{cat.label}</span>
            </button>
          );
        })}
      </div>

      {/* Integrations Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3, 4, 5, 6].map((idx) => (
            <div
              key={idx}
              className="bg-slate-900/50 border border-slate-800/60 rounded-3xl p-6 h-64 animate-pulse"
            />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredIntegrations.map((item) => {
            const badge = getStatusBadge(item.status);
            const isCanActivate = item.status === 'READY' || item.is_active;

            return (
              <div
                key={item.id}
                className="bg-slate-900/70 border border-slate-800/80 hover:border-slate-700/90 rounded-3xl p-6 flex flex-col justify-between transition-all hover:shadow-xl hover:shadow-black/40 group"
              >
                <div>
                  {/* Card Header */}
                  <div className="flex items-start justify-between gap-3 mb-4">
                    <div className="w-12 h-12 rounded-2xl bg-slate-950 border border-slate-800 flex items-center justify-center shadow-inner">
                      {getCategoryIcon(item.category)}
                    </div>
                    <span
                      className={`text-[11px] px-3 py-1 rounded-full font-medium border flex items-center gap-1.5 ${badge.color}`}
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${badge.dot}`} />
                      <span>{badge.label}</span>
                    </span>
                  </div>

                  {/* Title & Description */}
                  <h3 className="text-base font-bold text-white group-hover:text-blue-400 transition-colors mb-1.5">
                    {item.display_name_fa}
                  </h3>
                  <p className="text-xs text-slate-400 leading-relaxed mb-4 line-clamp-2">
                    {item.description_fa}
                  </p>

                  {/* Health & Status Message Box */}
                  <div className="p-3.5 rounded-2xl bg-slate-950/70 border border-slate-800/60 text-xs space-y-1 mb-4">
                    <div className="flex items-center gap-1.5 font-medium text-slate-400 text-[11px]">
                      <Info className="w-3.5 h-3.5 text-blue-400" />
                      <span>وضعیت اتصال:</span>
                    </div>
                    <p className="text-slate-300 text-[11px] leading-relaxed">
                      {item.message || 'پیکربندی نشده است.'}
                    </p>
                    {item.last_test_error && (
                      <p className="text-rose-400 text-[11px] pt-1 border-t border-slate-800/50">
                        علت خطا: {item.last_test_error}
                      </p>
                    )}
                  </div>

                  {/* Timestamps */}
                  <div className="flex items-center justify-between text-[10px] text-slate-500 mb-4 px-1">
                    <span>
                      {item.last_tested_at ? (
                        <>آخرین تست: {new Date(item.last_tested_at).toLocaleDateString('fa-IR')}</>
                      ) : (
                        'تستی انجام نشده'
                      )}
                    </span>
                    <span>
                      {item.last_connected_at ? (
                        <>آخرین اتصال: {new Date(item.last_connected_at).toLocaleDateString('fa-IR')}</>
                      ) : (
                        'فاقد اتصال موفق'
                      )}
                    </span>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="pt-4 border-t border-slate-800/60 flex items-center gap-2">
                  <button
                    onClick={() => handleOpenConfig(item)}
                    className="flex-1 py-2 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 transition-colors flex items-center justify-center gap-1.5 shadow-sm"
                  >
                    <SlidersHorizontal className="w-3.5 h-3.5 text-blue-400" />
                    <span>تنظیمات</span>
                  </button>

                  <button
                    onClick={() => handleTestConnection(item.id)}
                    disabled={actionLoading}
                    title="تست ارتباط زنده با ارائه‌دهنده"
                    className="py-2 px-3 rounded-xl bg-slate-950 border border-slate-800 hover:border-slate-700 text-xs font-semibold text-slate-300 hover:text-white transition-colors flex items-center justify-center gap-1.5"
                  >
                    <Zap className="w-3.5 h-3.5 text-amber-400" />
                    <span>تست</span>
                  </button>

                  {item.is_active ? (
                    <button
                      onClick={() => handleToggleActivation(item)}
                      disabled={actionLoading}
                      title="غیرفعال‌سازی موقت سرویس"
                      className="py-2 px-3 rounded-xl bg-rose-500/10 border border-rose-500/20 hover:bg-rose-500/20 text-xs font-bold text-rose-400 transition-colors"
                    >
                      غیرفعال
                    </button>
                  ) : (
                    <button
                      onClick={() => handleToggleActivation(item)}
                      disabled={actionLoading || !isCanActivate}
                      title={
                        isCanActivate
                          ? 'فعال‌سازی سرویس در عملیات فروشگاه'
                          : 'ابتدا باید تست اتصال با موفقیت انجام شود'
                      }
                      className={`py-2 px-3 rounded-xl text-xs font-bold transition-colors ${
                        isCanActivate
                          ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-sm shadow-emerald-950'
                          : 'bg-slate-800/50 text-slate-600 border border-slate-800 cursor-not-allowed'
                      }`}
                    >
                      فعال‌سازی
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Dedicated Configuration Modal / Drawer */}
      {activeConfigModal && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-3xl max-w-2xl w-full p-6 space-y-6 shadow-2xl max-h-[90vh] overflow-y-auto">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-2xl bg-slate-950 border border-slate-800 flex items-center justify-center">
                  {getCategoryIcon(activeConfigModal.category)}
                </div>
                <div>
                  <h2 className="text-base font-bold text-white">
                    تنظیمات {activeConfigModal.display_name_fa}
                  </h2>
                  <p className="text-xs text-slate-400">{activeConfigModal.description_fa}</p>
                </div>
              </div>
              <button
                onClick={() => setActiveConfigModal(null)}
                className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Provider Guide Box */}
            {activeConfigModal.guide_fa && (
              <div className="p-4 rounded-2xl bg-blue-950/20 border border-blue-500/20 text-xs text-blue-200 space-y-1.5">
                <div className="flex items-center gap-2 font-bold text-blue-300">
                  <HelpCircle className="w-4 h-4 text-blue-400 shrink-0" />
                  <span>راهنمای دریافت اطلاعات از ارائه‌دهنده سرویس:</span>
                </div>
                <p className="text-[11px] leading-relaxed text-blue-200/90 pr-6">
                  {activeConfigModal.guide_fa}
                </p>
              </div>
            )}

            {/* Dynamic Form Fields */}
            <div className="space-y-4">
              {activeConfigModal.schema.map((field) => {
                const isSecret = field.is_secret;
                const isShow = showSecrets[field.name];
                const value = formValues[field.name] ?? '';

                return (
                  <div key={field.name} className="space-y-1.5">
                    <label className="block text-xs font-semibold text-slate-300">
                      {field.label_fa}
                      {field.required && <span className="text-rose-400 mr-1">*</span>}
                    </label>

                    {field.type === 'boolean' ? (
                      <label className="flex items-center gap-3 cursor-pointer py-1">
                        <input
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(e) =>
                            setFormValues({ ...formValues, [field.name]: e.target.checked })
                          }
                          className="w-4 h-4 rounded text-blue-600 focus:ring-blue-500 border-slate-700 bg-slate-950"
                        />
                        <span className="text-xs text-slate-300">{field.help_text_fa}</span>
                      </label>
                    ) : field.type === 'select' ? (
                      <select
                        value={value}
                        onChange={(e) =>
                          setFormValues({ ...formValues, [field.name]: e.target.value })
                        }
                        className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
                      >
                        {(field.options || []).map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <div className="relative">
                        <input
                          type={isSecret && !isShow ? 'password' : 'text'}
                          value={value}
                          placeholder={field.placeholder || ''}
                          onChange={(e) =>
                            setFormValues({ ...formValues, [field.name]: e.target.value })
                          }
                          className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-mono tracking-wide"
                        />
                        {isSecret && (
                          <button
                            type="button"
                            onClick={() =>
                              setShowSecrets({
                                ...showSecrets,
                                [field.name]: !showSecrets[field.name],
                              })
                            }
                            className="absolute left-3 top-2.5 text-slate-500 hover:text-slate-300"
                          >
                            {isShow ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        )}
                      </div>
                    )}

                    {field.help_text_fa && field.type !== 'boolean' && (
                      <p className="text-[11px] text-slate-500 pr-1">{field.help_text_fa}</p>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Special Test Actions for SMS / Email */}
            {activeConfigModal.id.includes('sms') && (
              <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
                <span className="text-xs text-slate-400">ارسال پیامک آزمایشی به شماره مدیر:</span>
                <button
                  type="button"
                  onClick={() =>
                    setTestModal({
                      integration: activeConfigModal,
                      type: 'SMS',
                      targetValue: '',
                    })
                  }
                  className="px-3 py-1.5 rounded-xl bg-sky-500/10 border border-sky-500/20 hover:bg-sky-500/20 text-xs text-sky-400 font-medium transition-colors"
                >
                  تست ارسال پیامک واقعی
                </button>
              </div>
            )}

            {activeConfigModal.id.includes('email') && (
              <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
                <span className="text-xs text-slate-400">ارسال ایمیل آزمایشی جهت تایید نهایی:</span>
                <button
                  type="button"
                  onClick={() =>
                    setTestModal({
                      integration: activeConfigModal,
                      type: 'EMAIL',
                      targetValue: '',
                    })
                  }
                  className="px-3 py-1.5 rounded-xl bg-indigo-500/10 border border-indigo-500/20 hover:bg-indigo-500/20 text-xs text-indigo-400 font-medium transition-colors"
                >
                  ارسال ایمیل تستی
                </button>
              </div>
            )}

            {/* Modal Actions */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-800 gap-3">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleTestConnection(activeConfigModal.id)}
                  disabled={actionLoading}
                  className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 transition-colors flex items-center gap-1.5"
                >
                  <Zap className="w-4 h-4 text-amber-400" />
                  <span>تست اتصال</span>
                </button>

                {activeConfigModal.is_active ? (
                  <button
                    type="button"
                    onClick={() => handleToggleActivation(activeConfigModal)}
                    disabled={actionLoading}
                    className="px-4 py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-xs font-bold text-white transition-colors"
                  >
                    غیرفعال‌سازی
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => handleToggleActivation(activeConfigModal)}
                    disabled={actionLoading || activeConfigModal.status !== 'READY'}
                    title={
                      activeConfigModal.status === 'READY'
                        ? 'فعال‌سازی اتصال'
                        : 'ابتدا باید تست اتصال با موفقیت به پایان برسد.'
                    }
                    className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-colors ${
                      activeConfigModal.status === 'READY'
                        ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-md shadow-emerald-950'
                        : 'bg-slate-800 text-slate-600 cursor-not-allowed'
                    }`}
                  >
                    فعال‌سازی سرویس
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveConfigModal(null)}
                  className="px-4 py-2.5 rounded-xl border border-slate-700 text-slate-300 hover:bg-slate-800 text-xs font-medium transition-colors"
                >
                  انصراف
                </button>
                <button
                  type="button"
                  onClick={handleSaveConfig}
                  disabled={actionLoading}
                  className="px-5 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-xs font-bold text-white transition-colors shadow-md shadow-blue-950"
                >
                  {actionLoading ? 'در حال ذخیره...' : 'ذخیره تنظیمات'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Confirmation Modal for Live Test Dispatch (SMS or Email) */}
      {testModal && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-3xl max-w-md w-full p-6 space-y-4 shadow-2xl">
            <div className="w-12 h-12 rounded-2xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center mx-auto">
              <Send className="w-6 h-6" />
            </div>

            <div className="text-center">
              <h3 className="text-base font-bold text-white">
                ارسال {testModal.type === 'SMS' ? 'پیامک آزمایشی' : 'ایمیل آزمایشی'}
              </h3>
              <p className="text-xs text-slate-400 mt-2 leading-relaxed">
                {testModal.type === 'SMS' ? (
                  <>
                    توجه: ارسال این پیامک واقعی بوده و شامل کسر تعرفه پیامکی از شارژ حساب کاوه‌نگار شما خواهد شد. با کلیک روی تست معمولی، هیچ پیامکی ارسال نمی‌شود.
                  </>
                ) : (
                  <>یک ایمیل تست برای اطمینان از ارسال موفق به آدرس وارد شده فرستاده خواهد شد.</>
                )}
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">
                {testModal.type === 'SMS' ? 'شماره موبایل تست گیرنده:' : 'آدرس ایمیل تست گیرنده:'}
              </label>
              <input
                type={testModal.type === 'SMS' ? 'tel' : 'email'}
                placeholder={testModal.type === 'SMS' ? 'مثلاً 09123456789' : 'admin@yourstore.ir'}
                value={testModal.targetValue}
                onChange={(e) =>
                  setTestModal({ ...testModal, targetValue: e.target.value })
                }
                className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
              />
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                type="button"
                onClick={() => setTestModal(null)}
                className="flex-1 py-2.5 rounded-xl border border-slate-700 text-slate-300 hover:bg-slate-800 text-xs font-medium transition-colors"
              >
                انصراف
              </button>
              <button
                type="button"
                onClick={handleSendTestDispatch}
                disabled={testActionLoading || !testModal.targetValue}
                className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition-colors shadow-sm shadow-blue-950"
              >
                {testActionLoading ? 'در حال ارسال...' : 'تأیید و ارسال تست'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
