/**
 * Sidebar navigation. Three sections (OPERATIONS / CONFIGURATION / AUDIT)
 * styled with Sasai semantic tokens.
 */
"use client";

import {
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
      <div className="flex h-14 items-center gap-2 border-b border-sidebar-border px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary">
          <ClipboardList className="h-3.5 w-3.5 text-primary-foreground" />
        </div>
        <div className="flex flex-col leading-tight">
          <span className="text-sm font-semibold text-sidebar-foreground">Sasai Wallet</span>
          <span className="text-[10px] text-sidebar-foreground/60">Admin Console</span>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-2">
        <NavGroup title="Operations" items={operations} />
        <NavGroup title="Configuration" items={CONFIG} />
        <NavGroup title="Audit" items={AUDIT} />
      </nav>
      <div className="border-t border-sidebar-border px-4 py-3 text-[10px] text-sidebar-foreground/50">
        Phase F.5 · v0.1
      </div>
    </aside>
  );
}
