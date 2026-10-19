'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useStore } from '@/contexts/StoreContext';
import { Store, User, LogOut, Bell, ChevronDown, Sparkles, Check, CheckCheck, X } from 'lucide-react';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

export function Navbar() {
  const { user, logout } = useAuth();
  const { stores, activeStore, switchStore } = useStore();

  const [notifications, setNotifications] = useState<any[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [showStoreDropdown, setShowStoreDropdown] = useState(false);
  const storeDropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (storeDropdownRef.current && !storeDropdownRef.current.contains(event.target as Node)) {
        setShowStoreDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    if (user && activeStore) {
      loadNotifications();
    }
  }, [user, activeStore]);

  const loadNotifications = async () => {
    try {
      const data = await api.getNotifications(false);
      const list = Array.isArray(data) ? data : (data as any)?.results || [];
      setNotifications(list);
    } catch {
      // silent fallback
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await api.markAllNotificationsRead();
      setNotifications([]);
    } catch (err) {
      console.error(err);
    }
  };

  const handleMarkRead = async (id: string) => {
    try {
      await api.markNotificationRead(id);
      setNotifications(notifications.filter((n) => n.id !== id));
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <header className="h-16 bg-[#080c17]/75 backdrop-blur-xl border-b border-white/[0.06] px-6 flex items-center justify-between sticky top-0 z-30 shadow-[0_4px_20px_rgba(0,0,0,0.3)]">
      {/* Brand & Store Selector */}
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-blue-600 to-cyan-400 text-white flex items-center justify-center font-black text-base shadow-[0_0_15px_rgba(56,189,248,0.5)]">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-base tracking-tight text-white flex items-center gap-2">
            شاپ‌پایلوت
            <span className="text-[10px] font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 px-2 py-0.5 rounded-full">
              هوشمند
            </span>
          </span>
        </div>

        {/* Custom Modern Store Switcher */}
        {stores.length > 0 && (
          <div className="relative" ref={storeDropdownRef}>
            <button
              type="button"
              onClick={() => setShowStoreDropdown(!showStoreDropdown)}
              className={cn(
                'flex items-center gap-2.5 bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 hover:border-cyan-500/40 hover:bg-white/[0.07] light:hover:bg-slate-200 transition-all rounded-xl px-3 py-1.5 cursor-pointer shadow-sm',
                showStoreDropdown && 'border-cyan-500/50 bg-white/[0.08]'
              )}
            >
              <div className="w-5 h-5 rounded-lg bg-gradient-to-tr from-cyan-500/20 to-blue-500/20 border border-cyan-500/30 text-cyan-400 flex items-center justify-center shrink-0">
                <Store className="w-3.5 h-3.5" />
              </div>
              <span className="text-slate-200 light:text-slate-800 text-xs font-semibold">
                {activeStore?.name || 'انتخاب شعبه'}
              </span>
              <span className="text-[10px] font-mono text-cyan-400/80 bg-cyan-500/10 px-1.5 py-0.5 rounded-md hidden sm:inline-block">
                {activeStore?.currency === 'IRT' ? 'تومان' : 'ریال'}
              </span>
              <ChevronDown
                className={cn(
                  'w-3.5 h-3.5 text-slate-400 transition-transform duration-200',
                  showStoreDropdown && 'rotate-180 text-cyan-400'
                )}
              />
            </button>

            {/* Custom Glassmorphism Dropdown */}
            {showStoreDropdown && (
              <div className="absolute right-0 top-full mt-2 w-72 bg-[#0c1324]/95 dark:bg-[#0c1324]/95 light:bg-white backdrop-blur-2xl border border-white/10 dark:border-white/10 light:border-slate-200 rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.5)] p-2 z-50 space-y-1 animate-in fade-in zoom-in-95 text-right">
                <div className="px-3 py-2 text-[11px] font-bold text-slate-400 light:text-slate-500 border-b border-white/[0.06] light:border-slate-100 flex items-center justify-between">
                  <span>فروشگاه‌ها و شعب فعال</span>
                  <span className="text-[10px] text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded-full font-medium">
                    {stores.length} شعبه
                  </span>
                </div>

                <div className="max-h-60 overflow-y-auto space-y-1 py-1">
                  {stores.map((s) => {
                    const isSelected = s.id === activeStore?.id;
                    return (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => {
                          switchStore(s.id);
                          setShowStoreDropdown(false);
                        }}
                        className={cn(
                          'w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs transition cursor-pointer text-right group',
                          isSelected
                            ? 'bg-gradient-to-l from-blue-600/20 to-cyan-500/10 border border-blue-500/30 text-white font-bold shadow-sm'
                            : 'hover:bg-white/[0.05] light:hover:bg-slate-100 text-slate-300 light:text-slate-700'
                        )}
                      >
                        <div className="flex items-center gap-2.5">
                          <div
                            className={cn(
                              'w-8 h-8 rounded-xl flex items-center justify-center shrink-0 transition-colors',
                              isSelected
                                ? 'bg-gradient-to-tr from-blue-600 to-cyan-500 text-white shadow-[0_0_12px_rgba(6,182,212,0.4)]'
                                : 'bg-white/[0.04] text-slate-400 group-hover:text-slate-200 group-hover:bg-white/[0.08]'
                            )}
                          >
                            <Store className="w-4 h-4" />
                          </div>
                          <div className="text-right">
                            <div className="font-semibold text-slate-100 light:text-slate-900 group-hover:text-white">
                              {s.name}
                            </div>
                            <div className="text-[10px] text-slate-400 light:text-slate-500 mt-0.5">
                              واحد ارزی: {s.currency === 'IRT' ? 'تومان' : 'ریال'}
                            </div>
                          </div>
                        </div>
                        {isSelected && (
                          <div className="w-5 h-5 rounded-full bg-cyan-500/20 text-cyan-400 flex items-center justify-center shrink-0 border border-cyan-500/30">
                            <Check className="w-3 h-3" />
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Right Controls */}
      <div className="flex items-center gap-4">
        {/* Live operational badge */}
        <div className="hidden md:flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span>سامانه فعال</span>
        </div>

        {/* Notification Bell */}
        {user && (
          <div className="relative">
            <button
              onClick={() => setShowNotifications(!showNotifications)}
              title="اعلان‌های سیستم"
              className="relative p-2 text-slate-400 hover:text-white hover:bg-white/[0.06] rounded-xl border border-white/[0.05] transition-all cursor-pointer"
            >
              <Bell className="w-4 h-4" />
              {notifications.length > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-rose-500 text-[10px] font-bold text-white flex items-center justify-center">
                  {notifications.length}
                </span>
              )}
            </button>

            {/* Notification Dropdown */}
            {showNotifications && (
              <div className="absolute left-0 mt-3 w-80 bg-[#0b101d] border border-white/[0.1] rounded-2xl shadow-2xl p-4 z-50 text-right space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-white/[0.06]">
                  <span className="text-xs font-bold text-white">اعلان‌های درون‌برنامه‌ای</span>
                  {notifications.length > 0 && (
                    <button
                      onClick={handleMarkAllRead}
                      className="text-[11px] text-blue-400 hover:text-blue-300 flex items-center gap-1 cursor-pointer"
                    >
                      <CheckCheck className="w-3 h-3" />
                      خوانده شدن همه
                    </button>
                  )}
                </div>

                <div className="max-h-64 overflow-y-auto space-y-2 pr-1">
                  {notifications.map((n) => (
                    <div
                      key={n.id}
                      onClick={() => handleMarkRead(n.id)}
                      className="p-2.5 rounded-xl bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.04] cursor-pointer transition-all space-y-1"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-white">{n.title}</span>
                        <span className="text-[10px] text-slate-400">{n.category_display}</span>
                      </div>
                      <p className="text-[11px] text-slate-300 leading-relaxed">{n.message}</p>
                    </div>
                  ))}
                  {notifications.length === 0 && (
                    <div className="py-6 text-center text-xs text-slate-500">
                      اعلان خوانده‌نشده‌ای وجود ندارد.
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {user ? (
          <div className="flex items-center gap-3">
            <div className="text-left hidden sm:block">
              <div className="text-xs font-semibold text-slate-200">{user.full_name}</div>
              <div className="text-[10px] text-slate-400">{user.email || user.phone_number}</div>
            </div>
            <button
              onClick={logout}
              title="خروج از حساب"
              className="p-2 text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 rounded-xl border border-white/[0.05] hover:border-rose-500/20 transition-all cursor-pointer"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <a
            href="/login"
            className="text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded-xl shadow-[0_0_15px_rgba(37,99,235,0.4)] transition-all"
          >
            ورود به سیستم
          </a>
        )}
      </div>
    </header>
  );
}
