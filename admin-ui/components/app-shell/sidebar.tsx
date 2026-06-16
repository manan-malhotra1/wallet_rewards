/**
 * Sidebar navigation. Three sections (OPERATIONS / CONFIGURATION / AUDIT)
 * matching docs/04-ui-layouts.md §3. Active link is highlighted via
 * `pathname` from next/navigation.
 */
"use client";

import {
  AlertCircle,
  Box,
  ClipboardList,
  Coins,
  CreditCard,
  Gauge,
  GitMerge,
  Layers,
  ListChecks,
  Receipt,
  ScanLine,
  Settings2,
  ShieldCheck,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

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
  { label: "Reconciliation", href: "/reconciliation", icon: ScanLine },
];

const CONFIG: NavItem[] = [
  { label: "Rules", href: "/rules", icon: GitMerge },
  { label: "Segments", href: "/segments", icon: Layers },
  { label: "Limits", href: "/limits", icon: ListChecks },
  { label: "Pricing", href: "/pricing", icon: Coins },
  { label: "Redemption", href: "/redemption", icon: CreditCard },
  { label: "Tenants", href: "/tenants", icon: Settings2 },
];

const AUDIT: NavItem[] = [
  { label: "Audit log", href: "/audit", icon: ShieldCheck },
  { label: "Events", href: "/events", icon: Receipt },
];

function NavGroup({ title, items }: { title: string; items: NavItem[] }) {
  const pathname = usePathname();
  return (
    <div className="px-2">
      <div className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-[--color-text-3]">
        {title}
      </div>
      <ul className="space-y-px">
        {items.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-2 py-1.5 text-[13px] transition-colors",
                  isActive
                    ? "bg-[--color-surface-3] text-[--color-text-1]"
                    : "text-[--color-text-2] hover:bg-[--color-surface-2] hover:text-[--color-text-1]",
                )}
              >
                <item.icon className="h-4 w-4 shrink-0" />
                <span className="flex-1">{item.label}</span>
                {item.badge ? (
                  <span className="rounded bg-[--color-warning]/15 px-1.5 py-0.5 text-[10px] font-medium text-[--color-warning]">
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

/**
 * Sidebar — fixed width 240px, scrolls independently of main content.
 * Receives a `pendingCount` so the Reconciliation link can show a badge.
 */
export function Sidebar({ pendingCount }: { pendingCount?: number }) {
  const operations = OPERATIONS.map((item) =>
    item.href === "/reconciliation" && pendingCount
      ? { ...item, badge: pendingCount }
      : item,
  );
  return (
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-[--color-border] bg-[--color-surface-1]">
      <div className="flex h-[48px] items-center gap-2 border-b border-[--color-border] px-4">
        <ClipboardList className="h-4 w-4 text-[--color-brand]" />
        <span className="text-[14px] font-semibold">Sasai Wallet</span>
      </div>
      <nav className="flex-1 overflow-y-auto py-2">
        <NavGroup title="Operations" items={operations} />
        <NavGroup title="Configuration" items={CONFIG} />
        <NavGroup title="Audit" items={AUDIT} />
      </nav>
      <div className="border-t border-[--color-border] px-4 py-3 text-[11px] text-[--color-text-3]">
        <div className="flex items-center gap-1.5">
          <AlertCircle className="h-3 w-3" />
          Phase F.5 · v0.1
        </div>
      </div>
    </aside>
  );
}
