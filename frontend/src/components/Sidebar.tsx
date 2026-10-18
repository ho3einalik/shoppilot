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
        'sticky top-[5rem] z-20 self-start flex flex-col transition-all duration-300 select-none py-2.5 px-2 h-fit',
        'bg-[#0b101d]/90 dark:bg-[#0b101d]/90 light:bg-white/95 backdrop-blur-2xl border border-white/[0.08] dark:border-white/[0.08] light:border-slate-200 rounded-3xl shadow-[0_10px_40px_rgba(0,0,0,0.4)]',
        expanded ? 'w-60' : 'w-[68px]'
      )}
    >
      {/* Top Toggle Button */}
      <div className="flex items-center justify-center w-full mb-1">
        <button
          onClick={() => setExpanded(!expanded)}
          title={expanded ? 'کوچک کردن منو' : 'باز کردن منو'}
          className="w-8 h-8 rounded-xl bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 hover:bg-white/[0.08] border border-white/[0.06] text-slate-400 hover:text-white dark:hover:text-white light:hover:text-slate-900 flex items-center justify-center transition-all cursor-pointer"
        >
          {expanded ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronLeft className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Navigation Icons Column (No scrollbar) */}
      <nav className="flex flex-col items-center gap-1 w-full py-0.5">
        {mainNavItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));

          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              className={cn(
                'group relative flex items-center transition-all duration-200 rounded-xl',
                expanded
                  ? 'w-full px-2.5 py-1.5 gap-2.5 justify-start'
                  : 'w-9 h-9 justify-center',
                isActive
                  ? 'bg-blue-600 text-white shadow-[0_0_16px_rgba(37,99,235,0.6)] border border-blue-400/40'
                  : 'text-slate-400 hover:text-slate-100 dark:hover:text-slate-100 light:hover:text-slate-900 hover:bg-white/[0.06] light:hover:bg-slate-100'
              )}
            >
              <Icon
                className={cn(
                  'w-4 h-4 shrink-0 transition-transform duration-200 group-hover:scale-110',
                  isActive ? 'text-white' : 'text-slate-400 group-hover:text-slate-200 light:group-hover:text-slate-800'
                )}
              />

              {expanded && (
                <span
                  className={cn(
                    'text-[11px] font-medium whitespace-nowrap overflow-hidden transition-all',
                    isActive ? 'text-white font-semibold' : 'text-slate-300 light:text-slate-700'
                  )}
                >
                  {item.label}
                </span>
              )}

              {/* Floating tooltip when collapsed */}
              {!expanded && (
                <div className="absolute right-full mr-2.5 px-2.5 py-1 bg-[#0e1628] text-slate-200 text-[11px] font-medium rounded-lg shadow-xl border border-white/10 opacity-0 pointer-events-none group-hover:opacity-100 transition-opacity duration-150 whitespace-nowrap z-50">
                  {item.label}
                </div>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Bottom Section (Theme Toggle + User Pill) - Directly below nav items */}
      <div className="flex flex-col items-center gap-1.5 w-full pt-2 mt-1.5 border-t border-white/[0.06] light:border-slate-200">
        {/* Working Theme mode button */}
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'تغییر به حالت روشن' : 'تغییر به حالت تاریک'}
          className={cn(
            'flex items-center text-slate-400 hover:text-white light:hover:text-slate-900 transition-colors group cursor-pointer rounded-xl hover:bg-white/[0.04]',
            expanded ? 'w-full px-2.5 py-1.5 gap-2.5 justify-start' : 'w-8 h-8 justify-center'
          )}
        >
          <div className="w-7 h-7 rounded-lg bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 hover:bg-white/[0.08] light:hover:bg-slate-200 flex items-center justify-center transition-all group-hover:shadow-[0_0_10px_rgba(255,255,255,0.2)]">
            {theme === 'dark' ? (
              <Sun className="w-3.5 h-3.5 text-amber-400" />
            ) : (
              <Moon className="w-3.5 h-3.5 text-sky-500" />
            )}
          </div>
          {expanded && (
            <span className="text-[11px] text-slate-300 light:text-slate-700 font-medium">
              {theme === 'dark' ? 'حالت روشن' : 'حالت تاریک'}
            </span>
          )}
        </button>

        {/* User Pill */}
        <div
          className={cn(
            'flex items-center gap-2 rounded-xl bg-white/[0.04] dark:bg-white/[0.04] light:bg-slate-100 border border-white/[0.06] light:border-slate-200 p-1 transition-all w-full cursor-pointer hover:bg-white/[0.08] light:hover:bg-slate-200',
            expanded ? 'justify-start px-2' : 'justify-center'
          )}
          title={user?.full_name || 'حساب کاربری'}
        >
          <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-blue-600 to-cyan-400 flex items-center justify-center text-[10px] font-bold text-white shadow-inner shrink-0">
            {user?.full_name ? user.full_name.charAt(0) : 'U'}
          </div>
          {expanded && (
            <div className="overflow-hidden flex-1">
              <div className="text-[11px] font-semibold text-slate-200 light:text-slate-800 truncate">
                {user?.full_name || 'کاربر شاپ‌پایلوت'}
              </div>
              <div className="text-[9px] text-slate-500 truncate">
                {user?.phone_number || 'آنلاین'}
              </div>
            </div>
          )}
        </div>
      </div>
    </aside>

  );
}
