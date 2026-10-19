'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  LayoutGrid,
  Boxes,
  ShoppingCart,
  CreditCard,
  Users,
  CheckSquare,
  Calendar,
  Settings,
  Sun,
  Moon,
  ChevronRight,
  ChevronLeft,
  Truck,
  RotateCcw,
  MessageSquare,
  Tag,
  Sparkles,
  Store,
  Link2,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';
import { useTheme } from '@/contexts/ThemeContext';

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const mainNavItems: NavItem[] = [
  { href: '/', label: 'داشبورد عملیات', icon: LayoutDashboard },
  { href: '/products', label: 'کاتالوگ و محصولات', icon: LayoutGrid },
  { href: '/inventory', label: 'موجودی و انبارداری', icon: Boxes },
  { href: '/orders', label: 'مدیریت سفارشات', icon: ShoppingCart },
  { href: '/pos', label: 'صندوق حضوری و B2B', icon: Store },
  { href: '/returns', label: 'مرجوعی‌ها و RMA', icon: RotateCcw },
  { href: '/suppliers', label: 'تامین‌کنندگان و خرید', icon: Truck },
  { href: '/payments', label: 'تأیید فیش‌های واریزی', icon: CreditCard },
  { href: '/crm', label: 'مشتریان و پیام‌ها', icon: MessageSquare },
  { href: '/tasks', label: 'کارتابل و وظایف', icon: CheckSquare },
  { href: '/social/calendar', label: 'تقویم محتوا و رسانه‌ها', icon: Calendar },
  { href: '/marketing', label: 'تخفیف‌ها و اتوماسیون', icon: Tag },
  { href: '/intelligence', label: 'هوش تجاری و پیش‌بینی', icon: Sparkles },
  { href: '/team', label: 'تیم و دسترسی‌ها', icon: Users },
  { href: '/settings/integrations', label: 'اتصال‌ها و یکپارچه‌سازی‌ها', icon: Link2 },
  { href: '/settings/features', label: 'تنظیمات و ماژول‌ها', icon: Settings },
];


export function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [expanded, setExpanded] = useState(false);

  return (
    <aside
      className={cn(
        'sticky top-[5rem] z-20 self-start shrink-0 flex flex-col transition-all duration-300 select-none py-3 px-2 max-h-[calc(100vh-6rem)]',
        'bg-[#0b101d]/90 dark:bg-[#0b101d]/90 light:bg-white/95 backdrop-blur-2xl border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 rounded-3xl shadow-[0_10px_40px_rgba(0,0,0,0.4)]',
        expanded ? 'w-64 sm:w-68' : 'w-[72px]'
      )}
    >
      {/* Top Toggle Button & Header */}
      <div
        className={cn(
          'flex items-center w-full transition-all',
          expanded ? 'justify-between px-2 pb-2.5 mb-1.5 border-b border-white/[0.06] light:border-slate-200' : 'justify-center mb-1'
        )}
      >
        {expanded && (
          <span className="text-xs font-bold text-slate-200 light:text-slate-800 tracking-tight">
            منوی عملیات
          </span>
        )}
        <button
          onClick={() => setExpanded(!expanded)}
          title={expanded ? 'کوچک کردن منو' : 'باز کردن منو'}
          className="w-8 h-8 rounded-xl bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 hover:bg-white/[0.08] light:hover:bg-slate-200 border border-white/[0.06] light:border-slate-200 text-slate-400 hover:text-white dark:hover:text-white light:hover:text-slate-900 flex items-center justify-center transition-all cursor-pointer"
        >
          {expanded ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Navigation Icons Column with smooth scroll */}
      <nav className="flex flex-col gap-1 w-full flex-1 overflow-y-auto overflow-x-hidden py-1 px-0.5">
        {mainNavItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));

          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              className={cn(
                'group relative flex items-center transition-all duration-200 rounded-xl h-10',
                expanded
                  ? 'w-full px-3 gap-3 justify-start'
                  : 'w-10 justify-center mx-auto',
                isActive
                  ? 'bg-blue-600 text-white shadow-[0_0_18px_rgba(37,99,235,0.6)] border border-blue-400/40'
                  : 'text-slate-400 hover:text-slate-100 dark:hover:text-slate-100 light:hover:text-slate-900 hover:bg-white/[0.06] light:hover:bg-slate-100'
              )}
            >
              <Icon
                className={cn(
                  'w-4.5 h-4.5 shrink-0 transition-transform duration-200 group-hover:scale-110',
                  isActive ? 'text-white' : 'text-slate-400 group-hover:text-slate-200 light:group-hover:text-slate-800'
                )}
              />

              {expanded && (
                <span
                  className={cn(
                    'text-xs font-medium whitespace-nowrap overflow-hidden transition-all',
                    isActive ? 'text-white font-semibold' : 'text-slate-300 light:text-slate-700'
                  )}
                >
                  {item.label}
                </span>
              )}

              {/* Floating tooltip when collapsed */}
              {!expanded && (
                <div className="absolute right-full mr-3 px-3 py-1.5 bg-[#0e1628] text-slate-200 text-xs font-medium rounded-xl shadow-xl border border-white/10 opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity duration-150 whitespace-nowrap z-50">
                  {item.label}
                </div>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Bottom Section (Theme Toggle + User Pill) */}
      <div className="flex flex-col items-center gap-1.5 w-full pt-2.5 mt-1 border-t border-white/[0.06] light:border-slate-200">
        {/* Working Theme mode button */}
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'تغییر به حالت روشن' : 'تغییر به حالت تاریک'}
          className={cn(
            'flex items-center text-slate-400 hover:text-white light:hover:text-slate-900 transition-colors group cursor-pointer rounded-xl hover:bg-white/[0.04] light:hover:bg-slate-100 h-10',
            expanded ? 'w-full px-3 gap-3 justify-start' : 'w-10 justify-center'
          )}
        >
          <div className="w-7 h-7 rounded-lg bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 hover:bg-white/[0.08] light:hover:bg-slate-200 flex items-center justify-center transition-all group-hover:shadow-[0_0_10px_rgba(255,255,255,0.2)] shrink-0">
            {theme === 'dark' ? (
              <Sun className="w-4 h-4 text-amber-400" />
            ) : (
              <Moon className="w-4 h-4 text-sky-500" />
            )}
          </div>
          {expanded && (
            <span className="text-xs text-slate-300 light:text-slate-700 font-medium whitespace-nowrap">
              {theme === 'dark' ? 'حالت روشن' : 'حالت تاریک'}
            </span>
          )}
        </button>

        {/* User Pill */}
        <div
          className={cn(
            'flex items-center rounded-xl bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 border border-white/[0.06] light:border-slate-200 transition-all w-full cursor-pointer hover:bg-white/[0.08] light:hover:bg-slate-200',
            expanded ? 'justify-start px-2.5 py-1.5 gap-2.5' : 'justify-center p-1.5'
          )}
          title={user?.full_name || 'حساب کاربری'}
        >
          <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-blue-600 to-cyan-400 flex items-center justify-center text-xs font-bold text-white shadow-inner shrink-0">
            {user?.full_name ? user.full_name.charAt(0) : 'U'}
          </div>
          {expanded && (
            <div className="overflow-hidden flex-1">
              <div className="text-xs font-semibold text-slate-200 light:text-slate-800 truncate">
                {user?.full_name || 'کاربر شاپ‌پایلوت'}
              </div>
              <div className="text-[10px] text-slate-400 light:text-slate-500 truncate">
                {user?.phone_number || 'آنلاین'}
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

