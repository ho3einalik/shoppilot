'use client';

import React, { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useStore } from '@/contexts/StoreContext';
import { PaymentTransaction } from '@/types';
import { formatCurrency, formatNumber, formatDate, cn } from '@/lib/utils';
import {
  CreditCard,
  CheckCircle2,
  XCircle,
  Search,
  Filter,
  Image as ImageIcon,
  AlertCircle,
  Eye,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Plus,
  Calendar,
  Layers,
  Receipt,
  PieChart,
  FileSpreadsheet,
  Building2,
  Scale,
  X
} from 'lucide-react';

interface FinancialStatement {
  gross_sales: number;
  total_discounts: number;
  net_sales: number;
  cogs: number;
  gross_profit: number;
  total_operating_expenses: number;
  net_operating_profit: number;
  gross_margin_percent: number;
  net_margin_percent: number;
  expenses_by_category: Record<string, number>;
}

interface Expense {
  id: string;
  category: string;
  category_display: string;
  title: string;
  amount: number;
  expense_date: string;
  vendor_or_payee?: string;
  receipt_image_url?: string;
  notes?: string;
  created_at: string;
}

export default function PaymentsAndFinancePage() {
  const { activeStore } = useStore();
  const [activeTab, setActiveTab] = useState<'statement' | 'expenses' | 'slips' | 'settlements' | 'debts'>('statement');
  const [currency, setCurrency] = useState('IRT');

  // Statement State
  const [statementDays, setStatementDays] = useState(30);
  const [statement, setStatement] = useState<FinancialStatement | null>(null);
  const [loadingStatement, setLoadingStatement] = useState(false);

  // Expenses State
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [loadingExpenses, setLoadingExpenses] = useState(false);
  const [showAddExpenseModal, setShowAddExpenseModal] = useState(false);
  const [newExpense, setNewExpense] = useState({
    title: '',
    category: 'MARKETING',
    amount: '',
    expense_date: new Date().toISOString().split('T')[0],
    vendor_or_payee: '',
    notes: '',
  });

  // Offline Slips State
  const [payments, setPayments] = useState<PaymentTransaction[]>([]);
  const [statusFilter, setStatusFilter] = useState('PENDING_VERIFICATION');
  const [loadingPayments, setLoadingPayments] = useState(false);
  const [showRejectModal, setShowRejectModal] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<PaymentTransaction | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  useEffect(() => {
    if (activeStore) {
      setCurrency(activeStore.currency || 'IRT');
    }
  }, [activeStore]);

  // Load Financial Statement
  const loadStatement = async () => {
    if (!activeStore) return;
    setLoadingStatement(true);
    try {
      const data = await api.getFinancialStatement(statementDays);
      setStatement(data);
    } catch (err) {
      console.error('Error loading financial statement', err);
    } finally {
      setLoadingStatement(false);
    }
  };

  // Load Expenses
  const loadExpenses = async () => {
    if (!activeStore) return;
    setLoadingExpenses(true);
    try {
      const data = await api.getExpenses();
      const list = Array.isArray(data) ? data : (data as any)?.results || [];
      setExpenses(list);
    } catch (err) {
      console.error('Error loading expenses', err);
    } finally {
      setLoadingExpenses(false);
    }
  };

  // Load Payments
  const loadPayments = async () => {
    if (!activeStore) return;
    setLoadingPayments(true);
    try {
      const data = await api.getPayments({ status: statusFilter });
      const list = Array.isArray(data) ? data : (data as any)?.results || [];
      setPayments(list);
    } catch (err) {
      console.error('Error loading payments', err);
    } finally {
      setLoadingPayments(false);
    }
  };

  // Settlements State
  const [settlements, setSettlements] = useState<any[]>([]);
  const [loadingSettlements, setLoadingSettlements] = useState(false);
  const loadSettlements = async () => {
    if (!activeStore) return;
    setLoadingSettlements(true);
    try {
      const data = await api.getGatewaySettlements();
      const list = Array.isArray(data) ? data : (data as any)?.results || [];
      setSettlements(list);
    } catch (err) {
      console.error('Error loading settlements', err);
    } finally {
      setLoadingSettlements(false);
    }
  };

  // Debts and Receivables State
  const [debts, setDebts] = useState<any[]>([]);
  const [loadingDebts, setLoadingDebts] = useState(false);
  const loadDebts = async () => {
    if (!activeStore) return;
    setLoadingDebts(true);
    try {
      const data = await api.getAccountsPayableReceivable();
      const list = Array.isArray(data) ? data : (data as any)?.results || [];
      setDebts(list);
    } catch (err) {
      console.error('Error loading debts', err);
    } finally {
      setLoadingDebts(false);
    }
  };

  useEffect(() => {
    if (activeStore) {
      if (activeTab === 'statement') loadStatement();
      if (activeTab === 'expenses') loadExpenses();
      if (activeTab === 'slips') loadPayments();
      if (activeTab === 'settlements') loadSettlements();
      if (activeTab === 'debts') loadDebts();
    }
  }, [activeStore, activeTab, statementDays, statusFilter]);

  const handleAddExpense = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newExpense.title || !newExpense.amount) return;
    try {
      await api.createExpense({
        ...newExpense,
        amount: Number(newExpense.amount),
      });
      setShowAddExpenseModal(false);
      setNewExpense({
        title: '',
        category: 'MARKETING',
        amount: '',
        expense_date: new Date().toISOString().split('T')[0],
        vendor_or_payee: '',
        notes: '',
      });
      loadExpenses();
      loadStatement();
    } catch (err: any) {
      alert(`خطا در ثبت هزینه: ${err.message}`);
    }
  };

  const handleVerifyPayment = async (id: string) => {
    try {
      await api.verifyPayment(id);
      loadPayments();
    } catch (err: any) {
      alert(`خطا در تأیید تراکنش: ${err.message}`);
    }
  };

  const handleRejectPayment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rejectTarget) return;
    try {
      await api.rejectPayment(rejectTarget.id, rejectReason);
      setShowRejectModal(false);
      setRejectTarget(null);
      setRejectReason('');
      loadPayments();
    } catch (err: any) {
      alert(`خطا در رد فیش: ${err.message}`);
    }
  };

  const getCategoryLabel = (cat: string) => {
    const map: Record<string, string> = {
      RENT: 'اجاره بها',
      SALARY: 'حقوق و دستمزد',
      MARKETING: 'تبلیغات و مارکتینگ',
      PACKAGING: 'بسته‌بندی و ملزومات',
      SHIPPING: 'لجستیک و حمل',
      SOFTWARE: 'اشتراک نرم‌افزار',
      UTILITIES: 'قبوض و انرژی',
      OTHER: 'سایر هزینه‌ها',
    };
    return map[cat] || cat;
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-white tracking-tight flex items-center gap-3">
            <DollarSign className="w-7 h-7 text-emerald-400" />
            امور مالی، سود و زیان و تأیید پرداخت‌ها
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            صورت سود و زیان بلادرنگ (P&L)، ثبت هزینه‌های جاری عملیاتی و انطباق فیش‌های کارت‌به‌کارت
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={async () => {
              try {
                await api.downloadFile('/finance/export-csv/', `financial_report_${new Date().toISOString().slice(0, 10)}.csv`);
              } catch (e: any) {
                alert(`خطا در دریافت فایل گزارش مالی: ${e.message}`);
              }
            }}
            className="flex items-center gap-2 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/20 px-3.5 py-2 rounded-xl text-xs font-semibold transition cursor-pointer"
          >
            <FileSpreadsheet className="w-4 h-4" />
            خروجی اکسل و CSV گزارش مالی
          </button>

          {/* Tab Switcher */}
          <div className="flex flex-wrap items-center gap-1.5 p-1 bg-white/[0.04] border border-white/[0.08] rounded-2xl">
            <button
              onClick={() => setActiveTab('statement')}
              className={cn(
                'px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer',
                activeTab === 'statement'
                  ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 shadow-[0_0_15px_rgba(16,185,129,0.2)]'
                  : 'text-slate-400 hover:text-white'
              )}
            >
              <PieChart className="w-3.5 h-3.5" />
              صورت سود و زیان
            </button>
            <button
              onClick={() => setActiveTab('expenses')}
              className={cn(
                'px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer',
                activeTab === 'expenses'
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 shadow-[0_0_15px_rgba(6,182,212,0.2)]'
                  : 'text-slate-400 hover:text-white'
              )}
            >
              <Receipt className="w-3.5 h-3.5" />
              هزینه‌های جاری
            </button>
            <button
              onClick={() => setActiveTab('slips')}
              className={cn(
                'px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer',
                activeTab === 'slips'
                  ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30 shadow-[0_0_15px_rgba(59,130,246,0.2)]'
                  : 'text-slate-400 hover:text-white'
              )}
            >
              <CreditCard className="w-3.5 h-3.5" />
              تأیید فیش‌ها
            </button>
            <button
              onClick={() => setActiveTab('settlements')}
              className={cn(
                'px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer',
                activeTab === 'settlements'
                  ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30 shadow-[0_0_15px_rgba(245,158,11,0.2)]'
                  : 'text-slate-400 hover:text-white'
              )}
            >
              <Building2 className="w-3.5 h-3.5" />
              تسویه درگاه‌ها
            </button>
            <button
              onClick={() => setActiveTab('debts')}
              className={cn(
                'px-3.5 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer',
                activeTab === 'debts'
                  ? 'bg-purple-500/20 text-purple-300 border border-purple-500/30 shadow-[0_0_15px_rgba(168,85,247,0.2)]'
                  : 'text-slate-400 hover:text-white'
              )}
            >
              <Scale className="w-3.5 h-3.5" />
              بدهی‌ها و مطالبات
            </button>
          </div>
        </div>
      </div>

      {/* TAB 1: FINANCIAL STATEMENT */}
      {activeTab === 'statement' && (
        <div className="space-y-6">
          {/* Controls Bar */}
          <div className="flex items-center justify-between bg-white/[0.03] border border-white/[0.06] p-4 rounded-3xl">
            <span className="text-xs font-bold text-slate-300">بازه محاسباتی صورتحساب مالی:</span>
            <div className="flex items-center gap-2">
              {[7, 30, 90].map((d) => (
                <button
                  key={d}
                  onClick={() => setStatementDays(d)}
                  className={cn(
                    'px-3 py-1.5 rounded-xl text-xs font-bold transition cursor-pointer',
                    statementDays === d
                      ? 'bg-white/10 text-white border border-white/20'
                      : 'text-slate-400 hover:text-slate-200'
                  )}
                >
                  {d} روز گذشته
                </button>
              ))}
            </div>
          </div>

          {loadingStatement ? (
            <div className="py-20 text-center text-slate-400 text-sm">در حال محاسبه صورت مالی و بهای تمام‌شده...</div>
          ) : statement ? (
            <div className="space-y-6">
              {/* Bento Grid KPI Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {/* Gross Sales */}
                <div className="bg-white/[0.02] border border-white/[0.06] p-5 rounded-3xl space-y-2 relative overflow-hidden group hover:border-emerald-500/30 transition">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>فروش ناخالص (Gross Sales)</span>
                    <TrendingUp className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div className="text-2xl font-black text-white">
                    {formatCurrency(statement?.gross_sales || 0, currency)}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    تخفیفات اعطا شده: {formatCurrency(statement?.total_discounts || 0, currency)}
                  </div>
                </div>

                {/* COGS */}
                <div className="bg-white/[0.02] border border-white/[0.06] p-5 rounded-3xl space-y-2 relative overflow-hidden group hover:border-amber-500/30 transition">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>بهای تمام‌شده کالا (COGS)</span>
                    <Layers className="w-4 h-4 text-amber-400" />
                  </div>
                  <div className="text-2xl font-black text-amber-400">
                    {formatCurrency(statement?.cogs || 0, currency)}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    سود ناخالص: {formatCurrency(statement?.gross_profit || 0, currency)} ({statement?.gross_margin_percent || 0}٪)
                  </div>
                </div>

                {/* Operating Expenses */}
                <div className="bg-white/[0.02] border border-white/[0.06] p-5 rounded-3xl space-y-2 relative overflow-hidden group hover:border-rose-500/30 transition">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>هزینه‌های جاری (Opex)</span>
                    <TrendingDown className="w-4 h-4 text-rose-400" />
                  </div>
                  <div className="text-2xl font-black text-rose-400">
                    {formatCurrency(statement?.total_operating_expenses || 0, currency)}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    اجاره، تبلیغات، بسته‌بندی، لجستیک و دستمزد
                  </div>
                </div>

                {/* Net Operating Profit */}
                <div className={cn(
                  "p-5 rounded-3xl space-y-2 relative overflow-hidden border transition",
                  (statement?.net_operating_profit || 0) >= 0
                    ? "bg-emerald-500/[0.06] border-emerald-500/30 shadow-[0_0_20px_rgba(16,185,129,0.15)]"
                    : "bg-rose-500/[0.06] border-rose-500/30 shadow-[0_0_20px_rgba(244,63,94,0.15)]"
                )}>
                  <div className="flex items-center justify-between text-xs text-slate-300">
                    <span className="font-bold">سود خالص عملیاتی (Net Profit)</span>
                    <DollarSign className="w-4 h-4 text-emerald-400" />
                  </div>
                  <div className={cn(
                    "text-2xl font-black",
                    (statement?.net_operating_profit || 0) >= 0 ? "text-emerald-300" : "text-rose-400"
                  )}>
                    {formatCurrency(statement?.net_operating_profit || 0, currency)}
                  </div>
                  <div className="text-[11px] text-slate-400">
                    حاشیه سود خالص: <span className="font-bold text-white">{statement?.net_margin_percent || 0}٪</span>
                  </div>
                </div>
              </div>

              {/* Breakdown by Category */}
              <div className="bg-white/[0.02] border border-white/[0.06] p-6 rounded-3xl space-y-4">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <PieChart className="w-4 h-4 text-cyan-400" />
                  تفکیک هزینه‌های جاری عملیاتی بر اساس سرفصل
                </h3>
                {Object.keys(statement?.expenses_by_category || {}).length === 0 ? (
                  <p className="text-xs text-slate-500 py-4">هیچ هزینه عملیاتی ثبت شده‌ای در این بازه زمانی وجود ندارد.</p>
                ) : (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-2">
                    {Object.entries(statement?.expenses_by_category || {}).map(([cat, amount]) => (
                      <div key={cat} className="p-4 bg-white/[0.02] border border-white/[0.04] rounded-2xl space-y-1">
                        <span className="text-[11px] text-slate-400">{getCategoryLabel(cat)}</span>
                        <div className="text-base font-bold text-white">
                          {formatCurrency(Number(amount), currency)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* TAB 2: OPERATING EXPENSES */}
      {activeTab === 'expenses' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">فهرست کل هزینه‌های عملیاتی جاری کسب‌وکار</span>
            <button
              onClick={() => setShowAddExpenseModal(true)}
              className="bg-cyan-600 hover:bg-cyan-500 text-white font-bold text-xs px-4 py-2.5 rounded-xl transition flex items-center gap-1.5 shadow-[0_0_15px_rgba(6,182,212,0.3)] cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              ثبت هزینه جدید
            </button>
          </div>

          <div className="bg-white/[0.02] border border-white/[0.06] rounded-3xl overflow-hidden">
            <table className="w-full text-right text-xs">
              <thead className="bg-white/[0.03] border-b border-white/[0.06] text-slate-400 font-bold uppercase">
                <tr>
                  <th className="py-4 px-6">عنوان هزینه</th>
                  <th className="py-4 px-6">سرفصل</th>
                  <th className="py-4 px-6">مبلغ</th>
                  <th className="py-4 px-6">تاریخ</th>
                  <th className="py-4 px-6">دریافت‌کننده / فروشنده</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {loadingExpenses ? (
                  <tr>
                    <td colSpan={5} className="py-12 text-center text-slate-500">در حال دریافت هزینه‌ها...</td>
                  </tr>
                ) : expenses.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-12 text-center text-slate-500">هیچ هزینه‌ای ثبت نشده است.</td>
                  </tr>
                ) : (
                  expenses.map((exp) => (
                    <tr key={exp.id} className="hover:bg-white/[0.02] transition">
                      <td className="py-4 px-6">
                        <div className="font-bold text-white text-sm">{exp.title}</div>
                        {exp.notes && <div className="text-[11px] text-slate-400 mt-0.5">{exp.notes}</div>}
                      </td>
                      <td className="py-4 px-6">
                        <span className="bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 px-2.5 py-1 rounded-full text-[11px] font-bold">
                          {exp.category_display || getCategoryLabel(exp.category)}
                        </span>
                      </td>
                      <td className="py-4 px-6 font-bold text-white text-sm">
                        {formatCurrency(exp.amount, currency)}
                      </td>
                      <td className="py-4 px-6 text-slate-400">
                        {formatDate(exp.expense_date)}
                      </td>
                      <td className="py-4 px-6 text-slate-300">
                        {exp.vendor_or_payee || '-'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 3: OFFLINE SLIPS VERIFICATION */}
      {activeTab === 'slips' && (
        <div className="space-y-6">
          <div className="flex items-center gap-2 bg-white/[0.03] border border-white/[0.06] p-3 rounded-2xl">
            {['PENDING_VERIFICATION', 'VERIFIED', 'REJECTED'].map((st) => (
              <button
                key={st}
                onClick={() => setStatusFilter(st)}
                className={cn(
                  'text-xs font-bold px-3 py-1.5 rounded-xl transition cursor-pointer',
                  statusFilter === st
                    ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                    : 'text-slate-400 hover:text-slate-200'
                )}
              >
                {st === 'PENDING_VERIFICATION' ? 'در انتظار بررسی و تأیید' : st === 'VERIFIED' ? 'تأیید شده' : 'رد شده'}
              </button>
            ))}
          </div>

          <div className="bg-white/[0.02] border border-white/[0.06] rounded-3xl overflow-hidden">
            <table className="w-full text-right text-xs">
              <thead className="bg-white/[0.03] border-b border-white/[0.06] text-slate-400 font-bold uppercase">
                <tr>
                  <th className="py-4 px-6">سفارش و مشتری</th>
                  <th className="py-4 px-6">مبلغ واریزی</th>
                  <th className="py-4 px-6">روش پرداخت</th>
                  <th className="py-4 px-6">شناسه / کارت</th>
                  <th className="py-4 px-6 text-center">تصویر فیش</th>
                  <th className="py-4 px-6 text-center">وضعیت</th>
                  <th className="py-4 px-6 text-center">اقدام</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {loadingPayments ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-500">در حال دریافت فیش‌ها...</td>
                  </tr>
                ) : payments.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-12 text-center text-slate-500">هیچ تراکنشی در این وضعیت وجود ندارد.</td>
                  </tr>
                ) : (
                  payments.map((p) => (
                    <tr key={p.id} className="hover:bg-white/[0.02] transition">
                      <td className="py-4 px-6">
                        <div className="font-bold text-white text-sm">{p.order_number}</div>
                        <div className="text-[11px] text-slate-400 mt-0.5">{p.customer_name} &bull; {formatDate(p.created_at)}</div>
                      </td>
                      <td className="py-4 px-6 font-bold text-emerald-400 text-sm">
                        {formatCurrency(p.amount, currency)}
                      </td>
                      <td className="py-4 px-6 text-slate-300">
                        <span className="bg-white/[0.04] border border-white/[0.08] px-2.5 py-1 rounded-lg">
                          {p.method_display}
                        </span>
                      </td>
                      <td className="py-4 px-6 text-slate-400">
                        {p.payer_card_mask ? `کارت: ${p.payer_card_mask}` : p.tracking_code || '-'}
                      </td>
                      <td className="py-4 px-6 text-center">
                        {p.receipt_image_url ? (
                          <button
                            onClick={() => setPreviewImage(p.receipt_image_url)}
                            className="inline-flex items-center gap-1 text-cyan-400 hover:text-cyan-300 font-bold cursor-pointer"
                          >
                            <Eye className="w-3.5 h-3.5" />
                            <span>مشاهده فیش</span>
                          </button>
                        ) : (
                          <span className="text-slate-600">-</span>
                        )}
                      </td>
                      <td className="py-4 px-6 text-center">
                        <span className={cn(
                          'inline-block px-2.5 py-1 rounded-full text-[10px] font-bold border',
                          p.status === 'VERIFIED' && 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
                          p.status === 'PENDING_VERIFICATION' && 'bg-amber-500/10 text-amber-400 border-amber-500/20',
                          p.status === 'REJECTED' && 'bg-rose-500/10 text-rose-400 border-rose-500/20'
                        )}>
                          {p.status_display}
                        </span>
                      </td>
                      <td className="py-4 px-6 text-center">
                        {p.status === 'PENDING_VERIFICATION' && (
                          <div className="flex items-center justify-center gap-2">
                            <button
                              onClick={() => handleVerifyPayment(p.id)}
                              className="bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 p-1.5 rounded-xl border border-emerald-500/30 transition cursor-pointer"
                              title="تأیید فیش"
                            >
                              <CheckCircle2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => {
                                setRejectTarget(p);
                                setShowRejectModal(true);
                              }}
                              className="bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 p-1.5 rounded-xl border border-rose-500/30 transition cursor-pointer"
                              title="رد فیش"
                            >
                              <XCircle className="w-4 h-4" />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 4: GATEWAY SETTLEMENTS */}
      {activeTab === 'settlements' && (
        <div className="bg-[#0b101d]/90 border border-white/[0.08] rounded-3xl p-6 backdrop-blur-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Building2 className="w-4 h-4 text-amber-400" />
                تسویه‌های بانکی درگاه‌های پرداخت (شاپرک / زرین‌پال / سامان)
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                تطبیق کارمزد کسرشده و واریز خالص به شماره شبای بانکی همراه با ردیابی مغایرت‌ها
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-right text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-slate-400">
                  <th className="py-3 px-4">درگاه بانکی</th>
                  <th className="py-3 px-4">تاریخ تسویه</th>
                  <th className="py-3 px-4">مبلغ ناخالص</th>
                  <th className="py-3 px-4">کارمزد درگاه</th>
                  <th className="py-3 px-4">واریزی خالص</th>
                  <th className="py-3 px-4">شماره شبا مقصد</th>
                  <th className="py-3 px-4">شناسه پیگیری</th>
                  <th className="py-3 px-4">وضعیت تطبیق</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {settlements.map((s) => (
                  <tr key={s.id} className="hover:bg-white/[0.02]">
                    <td className="py-3 px-4 font-semibold text-white">{s.gateway_name}</td>
                    <td className="py-3 px-4 text-slate-300">{formatDate(s.settlement_date)}</td>
                    <td className="py-3 px-4 text-slate-300">
                      {formatCurrency(s.gross_amount, currency)}
                    </td>
                    <td className="py-3 px-4 text-rose-400">
                      {formatCurrency(s.gateway_fee, currency)}
                    </td>
                    <td className="py-3 px-4 text-emerald-400 font-bold">
                      {formatCurrency(s.net_deposited_amount, currency)}
                    </td>
                    <td className="py-3 px-4 text-slate-400">{s.sheba_number || '-'}</td>
                    <td className="py-3 px-4 text-blue-400">{s.tracking_reference || '-'}</td>
                    <td className="py-3 px-4">
                      {s.is_reconciled ? (
                        <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[11px]">
                          تطبیق کامل
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20 text-[11px]">
                          دارای مغایرت
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
                {settlements.length === 0 && (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-slate-500">
                      هیچ سند تسویه درگاهی ثبت نشده است.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* TAB 5: ACCOUNTS PAYABLE & RECEIVABLE */}
      {activeTab === 'debts' && (
        <div className="bg-[#0b101d]/90 border border-white/[0.08] rounded-3xl p-6 backdrop-blur-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Scale className="w-4 h-4 text-purple-400" />
                دفتر کل بدهی‌ها به تأمین‌کنندگان و مطالبات نسیه مشتریان B2B
              </h3>
              <p className="text-xs text-slate-400 mt-1">
                رهگیری سررسید چک‌ها، بدهی فاکتورهای خرید عمده و مانده‌حساب اعتباری همکاران
              </p>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-right text-xs">
              <thead>
                <tr className="border-b border-white/[0.06] text-slate-400">
                  <th className="py-3 px-4">نوع سند</th>
                  <th className="py-3 px-4">عنوان و شرح</th>
                  <th className="py-3 px-4">مبلغ کل</th>
                  <th className="py-3 px-4">تسویه‌شده</th>
                  <th className="py-3 px-4">مانده بدهی / طلب</th>
                  <th className="py-3 px-4">تاریخ سررسید</th>
                  <th className="py-3 px-4">وضعیت</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {debts.map((d) => (
                  <tr key={d.id} className="hover:bg-white/[0.02]">
                    <td className="py-3 px-4">
                      {d.entity_type === 'SUPPLIER_DEBT' ? (
                        <span className="px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20 text-[11px]">
                          بدهی به تامین‌کننده
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 text-[11px]">
                          طلب از مشتری B2B
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 font-semibold text-white">{d.title}</td>
                    <td className="py-3 px-4 text-slate-300">
                      {formatCurrency(d.total_amount, currency)}
                    </td>
                    <td className="py-3 px-4 text-emerald-400">
                      {formatCurrency(d.paid_amount, currency)}
                    </td>
                    <td className="py-3 px-4 text-amber-400 font-bold">
                      {formatCurrency(d.remaining_balance, currency)}
                    </td>
                    <td className="py-3 px-4 text-slate-400">{d.due_date ? formatDate(d.due_date) : 'نامشخص'}</td>
                    <td className="py-3 px-4">
                      <span className="px-2 py-0.5 rounded-full bg-white/[0.06] text-slate-300 text-[11px]">
                        {d.status_display}
                      </span>
                    </td>
                  </tr>
                ))}
                {debts.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-8 text-center text-slate-500">
                      هیچ سند بدهی یا بستانکاری ثبت نشده است.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add Expense Modal */}
      {showAddExpenseModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="bg-[#0b101d] rounded-3xl max-w-md w-full p-6 shadow-2xl border border-white/10 space-y-5">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-bold text-white flex items-center gap-2">
                <Receipt className="w-5 h-5 text-cyan-400" />
                ثبت هزینه عملیاتی جدید
              </h2>
              <button onClick={() => setShowAddExpenseModal(false)} className="text-slate-400 hover:text-white cursor-pointer">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleAddExpense} className="space-y-4 text-xs">
              <div>
                <label className="block font-bold text-slate-300 mb-1.5">عنوان هزینه</label>
                <input
                  type="text"
                  required
                  placeholder="مثال: اجاره دفتر انبار، هزینه کمپین اینستاگرام..."
                  value={newExpense.title}
                  onChange={(e) => setNewExpense({ ...newExpense, title: e.target.value })}
                  className="w-full bg-white/[0.04] border border-white/[0.1] text-white rounded-xl px-3.5 py-2.5 outline-none focus:border-cyan-400/70"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-bold text-slate-300 mb-1.5">سرفصل هزینه</label>
                  <select
                    value={newExpense.category}
                    onChange={(e) => setNewExpense({ ...newExpense, category: e.target.value })}
                    className="w-full bg-[#0b101d] border border-white/[0.1] text-white rounded-xl px-3.5 py-2.5 outline-none focus:border-cyan-400/70"
                  >
                    <option value="MARKETING">تبلیغات و مارکتینگ</option>
                    <option value="PACKAGING">بسته‌بندی و ملزومات</option>
                    <option value="SHIPPING">لجستیک و حمل</option>
                    <option value="RENT">اجاره بها</option>
                    <option value="SALARY">حقوق و دستمزد</option>
                    <option value="SOFTWARE">نرم‌افزار و ابزارها</option>
                    <option value="UTILITIES">قبوض و انرژی</option>
                    <option value="OTHER">سایر هزینه‌ها</option>
                  </select>
                </div>
                <div>
                  <label className="block font-bold text-slate-300 mb-1.5">مبلغ ({currency})</label>
                  <input
                    type="number"
                    required
                    placeholder="مثال: 5000000"
                    value={newExpense.amount}
                    onChange={(e) => setNewExpense({ ...newExpense, amount: e.target.value })}
                    className="w-full bg-white/[0.04] border border-white/[0.1] text-white rounded-xl px-3.5 py-2.5 font-mono outline-none focus:border-cyan-400/70"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-bold text-slate-300 mb-1.5">تاریخ ثبت</label>
                  <input
                    type="date"
                    value={newExpense.expense_date}
                    onChange={(e) => setNewExpense({ ...newExpense, expense_date: e.target.value })}
                    className="w-full bg-white/[0.04] border border-white/[0.1] text-white rounded-xl px-3.5 py-2.5 font-mono outline-none focus:border-cyan-400/70"
                  />
                </div>
                <div>
                  <label className="block font-bold text-slate-300 mb-1.5">فروشنده / دریافت‌کننده</label>
                  <input
                    type="text"
                    placeholder="مثال: چاپخانه البرز"
                    value={newExpense.vendor_or_payee}
                    onChange={(e) => setNewExpense({ ...newExpense, vendor_or_payee: e.target.value })}
                    className="w-full bg-white/[0.04] border border-white/[0.1] text-white rounded-xl px-3.5 py-2.5 outline-none focus:border-cyan-400/70"
                  />
                </div>
              </div>

              <div>
                <label className="block font-bold text-slate-300 mb-1.5">یادداشت تکمیلی</label>
                <textarea
                  rows={2}
                  placeholder="توضیحات و شرح فاکتور..."
                  value={newExpense.notes}
                  onChange={(e) => setNewExpense({ ...newExpense, notes: e.target.value })}
                  className="w-full bg-white/[0.04] border border-white/[0.1] text-white rounded-xl px-3.5 py-2.5 outline-none focus:border-cyan-400/70"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-white/[0.06]">
                <button
                  type="button"
                  onClick={() => setShowAddExpenseModal(false)}
                  className="text-slate-400 hover:text-white px-4 py-2 cursor-pointer"
                >
                  انصراف
                </button>
                <button
                  type="submit"
                  className="bg-cyan-600 hover:bg-cyan-500 text-white font-bold px-5 py-2.5 rounded-xl transition shadow-[0_0_15px_rgba(6,182,212,0.4)] cursor-pointer"
                >
                  ثبت هزینه در سیستم
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Reject Slip Modal */}
      {showRejectModal && rejectTarget && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="bg-[#0b101d] rounded-3xl max-w-md w-full p-6 shadow-2xl border border-white/10 space-y-4">
            <h2 className="text-base font-bold text-rose-400">رد فیش واریزی</h2>
            <p className="text-xs text-slate-300">
              علت عدم تأیید فیش سفارش {rejectTarget.order_number} برای مشتری ثبت خواهد شد:
            </p>
            <form onSubmit={handleRejectPayment} className="space-y-4">
              <input
                type="text"
                required
                placeholder="مثال: عدم انطباق با گردش حساب، فیش نامعتبر..."
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                className="w-full bg-white/[0.04] border border-white/[0.1] text-white rounded-xl px-3.5 py-2.5 text-xs outline-none focus:border-rose-400"
              />
              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowRejectModal(false)}
                  className="text-slate-400 hover:text-white text-xs px-4 py-2 cursor-pointer"
                >
                  انصراف
                </button>
                <button
                  type="submit"
                  className="bg-rose-600 hover:bg-rose-500 text-white font-bold text-xs px-5 py-2.5 rounded-xl transition cursor-pointer"
                >
                  رد قطعی فیش
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Receipt Image Preview Modal */}
      {previewImage && (
        <div
          onClick={() => setPreviewImage(null)}
          className="fixed inset-0 bg-black/80 backdrop-blur-md z-50 flex items-center justify-center p-4 cursor-pointer"
        >
          <div className="max-w-xl max-h-[85vh] bg-[#0b101d] p-3 rounded-3xl border border-white/10 shadow-2xl">
            <img src={previewImage} alt="Receipt Slip" className="max-h-[80vh] w-auto rounded-2xl object-contain mx-auto" />
          </div>
        </div>
      )}
    </div>
  );
}
