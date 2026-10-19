'use client';

import React, { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useStore } from '@/contexts/StoreContext';
import { Product, Category } from '@/types';
import { formatCurrency, formatNumber } from '@/lib/utils';
import { Package, Plus, Search, Tag, Filter, CheckCircle2, AlertCircle, ChevronDown } from 'lucide-react';

export default function ProductsPage() {
  const { activeStore } = useStore();
  const [products, setProducts] = useState<Product[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [search, setSearch] = useState('');
  const [selectedCat, setSelectedCat] = useState('');
  const [loading, setLoading] = useState(true);

  // Modal create product
  const [showModal, setShowModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newBrand, setNewBrand] = useState('');
  const [newCatId, setNewCatId] = useState('');
  const [newSku, setNewSku] = useState('');
  const [newRetailPrice, setNewRetailPrice] = useState('');
  const [newCostPrice, setNewCostPrice] = useState('');

  const loadProducts = async () => {
    if (!activeStore) return;
    setLoading(true);
    try {
      const [prodsData, catsData] = await Promise.all([
        api.getProducts({ search, category: selectedCat }),
        api.getCategories(),
      ]);
      const pList: Product[] = Array.isArray(prodsData) ? prodsData : prodsData.results || [];
      const cList: Category[] = Array.isArray(catsData) ? catsData : catsData.results || [];
      setProducts(pList);
      setCategories(cList);
    } catch (err) {
      console.error('Error loading products', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeStore) {
      loadProducts();
    }
  }, [activeStore, selectedCat]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadProducts();
  };

  const handleCreateProduct = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.createProduct({
        name: newName,
        brand: newBrand,
        category: newCatId || null,
        variants_data: [
          {
            name: 'تنوع اصلی',
            sku: newSku || `SKU-${Date.now().toString().slice(-6)}`,
            retail_price: parseFloat(newRetailPrice || '0'),
            cost_price: parseFloat(newCostPrice || '0'),
          },
        ],
      });
      setShowModal(false);
      setNewName('');
      setNewBrand('');
      setNewSku('');
      setNewRetailPrice('');
      setNewCostPrice('');
      await loadProducts();
    } catch (err: any) {
      alert(`خطا در ایجاد محصول: ${err.message}`);
    }
  };

  const currency = activeStore?.currency || 'IRT';

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white light:text-slate-900 tracking-tight">کاتالوگ و محصولات</h1>
          <p className="text-sm text-slate-400 light:text-slate-500 mt-1">مدیریت تنوع کالا، قیمت‌گذاری و وضعیت موجودی قابل فروش</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="inline-flex items-center gap-2 bg-sky-600 hover:bg-sky-500 text-white font-semibold text-sm px-4 py-2.5 rounded-xl transition shadow-[0_0_15px_rgba(2,132,199,0.3)] cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          <span>افزودن محصول جدید</span>
        </button>
      </div>

      {/* Filters & Search */}
      <div className="bg-[#0b101d]/80 dark:bg-[#0b101d]/80 light:bg-white p-4 rounded-2xl border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 shadow-lg backdrop-blur-xl flex flex-col md:flex-row gap-4 items-center justify-between">
        <form onSubmit={handleSearch} className="relative w-full md:w-96">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="جستجو بر اساس نام محصول، SKU، یا بارکد..."
            className="w-full bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-50 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-slate-100 light:text-slate-900 placeholder:text-slate-500 rounded-xl pr-10 pl-4 py-2 text-sm focus:ring-2 focus:ring-sky-500 focus:border-sky-400/50 outline-none transition"
          />
          <Search className="w-4 h-4 text-slate-400 absolute right-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
        </form>

        <div className="relative flex items-center w-full md:w-auto">
          <Filter className="w-4 h-4 text-cyan-400 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <select
            value={selectedCat}
            onChange={(e) => setSelectedCat(e.target.value)}
            className="w-full md:w-auto bg-[#0f172a] dark:bg-[#0f172a] light:bg-slate-50 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-slate-200 dark:text-slate-200 light:text-slate-700 text-sm rounded-xl py-2 pr-9 pl-9 font-medium cursor-pointer focus:ring-2 focus:ring-sky-500 outline-none appearance-none transition shadow-sm"
          >
            <option value="" className="bg-[#0b101d] text-slate-200">همه دسته‌بندی‌ها</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id} className="bg-[#0b101d] text-slate-200">
                {c.name}
              </option>
            ))}
          </select>
          <ChevronDown className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
      </div>

      {/* Products Table */}
      <div className="bg-[#0b101d]/80 dark:bg-[#0b101d]/80 light:bg-white rounded-2xl border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 shadow-xl overflow-hidden backdrop-blur-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-right text-sm">
            <thead className="bg-white/[0.02] dark:bg-white/[0.02] light:bg-slate-50 border-b border-white/[0.06] light:border-slate-200 text-xs font-bold text-slate-400 light:text-slate-500 uppercase">
              <tr>
                <th className="py-3.5 px-6">محصول و دسته‌بندی</th>
                <th className="py-3.5 px-6">کد کالا (SKU)</th>
                <th className="py-3.5 px-6">قیمت تمام‌شده (خرید)</th>
                <th className="py-3.5 px-6">قیمت فروش</th>
                <th className="py-3.5 px-6 text-center">موجودی فیزیکی</th>
                <th className="py-3.5 px-6 text-center">قابل فروش</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04] dark:divide-white/[0.04] light:divide-slate-100">
              {loading ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    در حال دریافت لیست محصولات...
                  </td>
                </tr>
              ) : products.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    محصولی با این مشخصات یافت نشد.
                  </td>
                </tr>
              ) : (
                products.map((p) => {
                  return p.variants.map((v) => (
                    <tr
                      key={v.id}
                      className="hover:bg-white/[0.04] dark:hover:bg-white/[0.04] light:hover:bg-slate-50/70 transition-colors"
                    >
                      <td className="py-4 px-6">
                        <div className="font-bold text-white light:text-slate-900">{p.name}</div>
                        <div className="text-xs text-slate-400 light:text-slate-500 flex items-center gap-2 mt-0.5">
                          <span>{v.name}</span>
                          {p.category_name && (
                            <span className="bg-white/[0.06] dark:bg-white/[0.06] light:bg-slate-100 px-2 py-0.5 rounded text-[11px] text-slate-300 light:text-slate-600 border border-white/[0.04] light:border-transparent">
                              {p.category_name}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-4 px-6 font-mono text-xs text-slate-400 light:text-slate-600">{v.sku}</td>
                      <td className="py-4 px-6 text-slate-400 light:text-slate-500">{formatCurrency(v.cost_price, currency)}</td>
                      <td className="py-4 px-6 font-bold text-white light:text-slate-900">{formatCurrency(v.retail_price, currency)}</td>
                      <td className="py-4 px-6 text-center font-medium text-slate-300 light:text-slate-700">
                        {formatNumber(v.total_on_hand)}
                      </td>
                      <td className="py-4 px-6 text-center">
                        <span
                          className={`inline-block font-bold px-2.5 py-1 rounded-full text-xs border ${
                            v.total_available <= 3
                              ? 'bg-rose-500/10 text-rose-400 border-rose-500/20 light:bg-rose-100 light:text-rose-700 light:border-transparent'
                              : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 light:bg-emerald-100 light:text-emerald-800 light:border-transparent'
                          }`}
                        >
                          {formatNumber(v.total_available)} عدد
                        </span>
                      </td>
                    </tr>
                  ));
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create Product Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <div className="bg-[#0c1324] dark:bg-[#0c1324] light:bg-white rounded-3xl max-w-lg w-full p-6 shadow-2xl border border-white/10 dark:border-white/10 light:border-slate-100 space-y-5 animate-in fade-in zoom-in-95">
            <h2 className="text-lg font-bold text-white light:text-slate-900">ثبت محصول جدید</h2>
            <form onSubmit={handleCreateProduct} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-slate-300 light:text-slate-700 mb-1">نام محصول</label>
                <input
                  type="text"
                  required
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="مثال: پیراهن لینن بهاره"
                  className="w-full bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-50 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-white light:text-slate-900 rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-sky-500 outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 light:text-slate-700 mb-1">برند</label>
                  <input
                    type="text"
                    value={newBrand}
                    onChange={(e) => setNewBrand(e.target.value)}
                    placeholder="مثال: لوتوس"
                    className="w-full bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-50 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-white light:text-slate-900 rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-sky-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 light:text-slate-700 mb-1">دسته‌بندی</label>
                  <select
                    value={newCatId}
                    onChange={(e) => setNewCatId(e.target.value)}
                    className="w-full bg-[#0f172a] dark:bg-[#0f172a] light:bg-slate-50 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-slate-200 dark:text-slate-200 light:text-slate-700 rounded-xl px-3 py-2.5 text-sm focus:ring-2 focus:ring-sky-500 outline-none"
                  >
                    <option value="" className="bg-[#0b101d] text-slate-200">انتخاب دسته‌بندی...</option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.id} className="bg-[#0b101d] text-slate-200">
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-300 light:text-slate-700 mb-1">شناسه کالا (SKU)</label>
                <input
                  type="text"
                  value={newSku}
                  onChange={(e) => setNewSku(e.target.value)}
                  placeholder="مثال: SHIRT-LNN-01"
                  className="w-full bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-50 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-white light:text-slate-900 rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-sky-500 outline-none font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold text-slate-300 light:text-slate-700 mb-1">قیمت خرید (تومان)</label>
                  <input
                    type="number"
                    value={newCostPrice}
                    onChange={(e) => setNewCostPrice(e.target.value)}
                    placeholder="250000"
                    className="w-full bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-50 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-white light:text-slate-900 rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-sky-500 outline-none"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-300 light:text-slate-700 mb-1">قیمت فروش عادی (تومان)</label>
                  <input
                    type="number"
                    value={newRetailPrice}
                    onChange={(e) => setNewRetailPrice(e.target.value)}
                    placeholder="450000"
                    className="w-full bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-50 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 text-white light:text-slate-900 rounded-xl px-3.5 py-2.5 text-sm focus:ring-2 focus:ring-sky-500 outline-none"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-white/[0.06] light:border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="text-sm font-medium text-slate-400 hover:text-white light:text-slate-600 light:hover:text-slate-800 px-4 py-2 cursor-pointer transition"
                >
                  انصراف
                </button>
                <button
                  type="submit"
                  className="bg-sky-600 hover:bg-sky-500 text-white font-bold text-sm px-5 py-2.5 rounded-xl transition shadow-[0_0_15px_rgba(2,132,199,0.3)] cursor-pointer"
                >
                  ذخیره محصول
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
