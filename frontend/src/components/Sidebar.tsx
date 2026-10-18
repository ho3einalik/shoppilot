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
        'relative z-20 flex flex-col justify-between transition-all duration-300 select-none py-5 px-3 my-4 mr-4',
        'bg-[#0b101d]/90 dark:bg-[#0b101d]/90 light:bg-white/95 backdrop-blur-2xl border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 rounded-3xl shadow-[0_10px_40px_rgba(0,0,0,0.4)]',
        expanded ? 'w-64' : 'w-[72px]'
      )}
    >
      {/* Top Section / Nav Items */}
      <div className="flex flex-col items-center gap-6 w-full">
        {/* Toggle Expand / Collapse button */}
        <button
          onClick={() => setExpanded(!expanded)}
          title={expanded ? 'کوچک کردن منو' : 'باز کردن منو'}
          className="w-10 h-10 rounded-2xl bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 hover:bg-white/[0.08] border border-white/[0.06] text-slate-400 hover:text-white dark:hover:text-white light:hover:text-slate-900 flex items-center justify-center transition-all"
        >
          {expanded ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>

        {/* Navigation Icons Column */}
        <nav className="flex flex-col items-center gap-3 w-full">
          {mainNavItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));

            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.label}
                className={cn(
                  'group relative flex items-center transition-all duration-200 rounded-2xl',
                  expanded
                    ? 'w-full px-3.5 py-3 gap-3.5 justify-start'
                    : 'w-12 h-12 justify-center',
                  isActive
                    ? 'bg-blue-600 text-white shadow-[0_0_22px_rgba(37,99,235,0.65)] border border-blue-400/40'
                    : 'text-slate-400 hover:text-slate-100 dark:hover:text-slate-100 light:hover:text-slate-900 hover:bg-white/[0.06] light:hover:bg-slate-100'
                )}
              >
                <Icon
                  className={cn(
                    'w-5 h-5 shrink-0 transition-transform duration-200 group-hover:scale-110',
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
                  <div className="absolute right-full mr-3.5 px-3 py-1.5 bg-[#0e1628] text-slate-200 text-xs font-medium rounded-xl shadow-xl border border-white/10 opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity duration-150 whitespace-nowrap z-50">
                    {item.label}
                  </div>
                )}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Bottom Section (Theme Toggle + User Pill) */}
      <div className="flex flex-col items-center gap-4 w-full pt-4 border-t border-white/[0.06] light:border-slate-200">
        {/* Working Theme mode button */}
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'تغییر به حالت روشن' : 'تغییر به حالت تاریک'}
          className="flex flex-col items-center justify-center gap-1 text-slate-400 hover:text-white light:hover:text-slate-900 transition-colors group cursor-pointer"
        >
          <div className="w-10 h-10 rounded-2xl bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 hover:bg-white/[0.08] light:hover:bg-slate-200 flex items-center justify-center transition-all group-hover:shadow-[0_0_12px_rgba(255,255,255,0.2)]">
            {theme === 'dark' ? (
              <Sun className="w-4 h-4 text-amber-400" />
            ) : (
              <Moon className="w-4 h-4 text-sky-500" />
            )}
          </div>
          <span className="text-[10px] text-slate-400 font-medium">
            {theme === 'dark' ? 'Light' : 'Dark'}
          </span>
        </button>

        {/* User Pill matching reference image */}
        <div
          className={cn(
            'flex items-center gap-2 rounded-2xl bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 border border-white/[0.06] light:border-slate-200 p-1.5 transition-all w-full cursor-pointer hover:bg-white/[0.08] light:hover:bg-slate-200',
            expanded ? 'justify-start px-2.5' : 'justify-center'
          )}
          title={user?.full_name || 'حساب کاربری'}
        >
          <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-blue-600 to-cyan-400 flex items-center justify-center text-[11px] font-bold text-white shadow-inner shrink-0">
            {user?.full_name ? user.full_name.charAt(0) : 'U'}
          </div>
          {expanded && (
            <div className="overflow-hidden flex-1">
              <div className="text-xs font-semibold text-slate-200 light:text-slate-800 truncate">
                {user?.full_name || 'کاربر شاپ‌پایلوت'}
              </div>
              <div className="text-[10px] text-slate-500 truncate">
                {user?.phone_number || 'آنلاین'}
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
