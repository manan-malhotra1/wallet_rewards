/**
 * Sidebar navigation. Three sections (OPERATIONS / CONFIGURATION / AUDIT)
 * styled with Sasai semantic tokens.
 */
"use client";

import {
  Banknote,
  Box,
  Coins,
  CreditCard,
  Gauge,
  Layers,
  ListChecks,
  Megaphone,
  PiggyBank,
  Receipt,
  ScanLine,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Tag,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { SasaiLogo } from "@/components/branding/sasai-logo";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: number;
}

const OPERATIONS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: Gauge },
  { label: "Users", href: "/users", icon: Users },
  { label: "Merchants", href: "/merchants", icon: Box },
  { label: "System wallets", href: "/system-wallets", icon: Banknote },
  { label: "Reconciliation", href: "/reconciliation", icon: ScanLine },
];

const CONFIG: NavItem[] = [
  { label: "Campaigns", href: "/campaigns", icon: Megaphone },
  { label: "Segments", href: "/segments", icon: Layers },
  { label: "Budgets", href: "/budgets", icon: PiggyBank },
  { label: "Limits", href: "/limits", icon: ListChecks },
  { label: "Step-up PIN", href: "/step-up", icon: ShieldAlert },
  { label: "Pricing", href: "/pricing", icon: Coins },
  { label: "Redemption", href: "/redemption", icon: CreditCard },
  { label: "Services", href: "/services", icon: Tag },
  { label: "Tenants", href: "/tenants", icon: Settings2 },
];

const AUDIT: NavItem[] = [
  { label: "Audit log", href: "/audit", icon: ShieldCheck },
  { label: "Events", href: "/events", icon: Receipt },
];

function NavGroup({ title, items }: { title: string; items: NavItem[] }) {
  const pathname = usePathname();
  return (
    <div className="px-3 pb-2">
      <div className="px-2 pb-1.5 pt-3 text-[10px] font-semibold uppercase tracking-wider text-sidebar-foreground/60">
        {title}
      </div>
      <ul className="space-y-0.5">
        {items.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={cn(
                  "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  isActive
                    ? "bg-sidebar-primary text-sidebar-primary-foreground font-medium shadow-sm"
                    : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                )}
              >
                <item.icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    isActive
                      ? "text-sidebar-primary-foreground"
                      : "text-sidebar-foreground/60 group-hover:text-sidebar-accent-foreground",
                  )}
                />
                <span className="flex-1">{item.label}</span>
                {item.badge ? (
                  <span
                    className={cn(
                      "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                      isActive
                        ? "bg-sidebar-primary-foreground/20 text-sidebar-primary-foreground"
                        : "bg-amber-500/15 text-amber-700 dark:text-amber-400",
                    )}
                  >
                    {item.badge}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function Sidebar({ pendingCount }: { pendingCount?: number }) {
  const operations = OPERATIONS.map((item) =>
    item.href === "/reconciliation" && pendingCount
      ? { ...item, badge: pendingCount }
      : item,
  );
  return (
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar">
      <div className="flex h-16 items-center justify-between border-b border-sidebar-border px-4">
        <Link href="/dashboard" aria-label="Sasai Wallet Admin home" className="flex items-center">
          <SasaiLogo height={28} />
        </Link>
        <span className="rounded-full bg-sidebar-accent px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-sidebar-accent-foreground">
          Admin
        </span>
      </div>
      <nav className="flex-1 overflow-y-auto py-2">
        <NavGroup title="Operations" items={operations} />
        <NavGroup title="Configuration" items={CONFIG} />
        <NavGroup title="Audit" items={AUDIT} />
      </nav>
      <div className="flex items-center justify-between border-t border-sidebar-border px-4 py-3">
        <span className="text-[10px] font-medium text-sidebar-foreground/50">
          v0.1
        </span>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
          <span className="h-1 w-1 rounded-full bg-emerald-500" />
          Phase F.5
        </span>
      </div>
    </aside>
  );
}
