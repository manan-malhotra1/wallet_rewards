/**
 * Sidebar navigation. Three sections (OPERATIONS / CONFIGURATION / AUDIT)
 * styled with Sasai semantic tokens.
 */
"use client";

import {
  Banknote,
  Box,
  ChevronDown,
  Coins,
  CreditCard,
  Gauge,
  GitPullRequest,
  HandCoins,
  KeyRound,
  Layers,
  ListChecks,
  Megaphone,
  PiggyBank,
  Receipt,
  Repeat,
  ScanLine,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Tag,
  Ticket,
  Undo2,
  Users,
  Users2,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { SasaiLogo } from "@/components/branding/sasai-logo";
import { REWARDS_ONLY_NAV } from "@/lib/tenant-mode";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: number;
}

/**
 * A collapsible parent with indented children. Routes are unchanged — this is
 * purely a grouping shell (e.g. Pricing ▸ Service charges / Commission / Taxes).
 */
interface NavParent {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  children: NavItem[];
}

/** A CONFIG-section entry is either a flat link or a collapsible parent. */
type NavEntry = NavItem | NavParent;

function isParent(entry: NavEntry): entry is NavParent {
  return "children" in entry;
}

const OPERATIONS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: Gauge },
  { label: "Users", href: "/users", icon: Users },
  { label: "Merchants", href: "/merchants", icon: Box },
  { label: "System wallets", href: "/system-wallets", icon: Banknote },
  // Two separate menus by design (spec D14): disbursement PAYS the earner,
  // withdrawal CLAWS BACK to an operator account. Different business acts.
  {
    label: "Commission disbursement",
    href: "/commission-disbursement",
    icon: HandCoins,
  },
  {
    label: "Commission withdrawal",
    href: "/commission-withdrawal",
    icon: Undo2,
  },
  { label: "Reconciliation", href: "/reconciliation", icon: ScanLine },
];

const CONFIG: NavEntry[] = [
  { label: "Campaigns", href: "/campaigns", icon: Megaphone },
  { label: "Segments", href: "/segments", icon: Layers },
  { label: "Multipliers", href: "/multipliers", icon: Zap },
  { label: "Budgets", href: "/budgets", icon: PiggyBank },
  { label: "Limits", href: "/limits", icon: ListChecks },
  { label: "Step-up PIN", href: "/step-up", icon: ShieldAlert },
  {
    label: "Pricing",
    icon: Coins,
    children: [
      { label: "Service charges", href: "/pricing", icon: Coins },
      { label: "Commission", href: "/commissions", icon: Coins },
      { label: "Taxes", href: "/taxes", icon: Receipt },
    ],
  },
  { label: "Approvals", href: "/approvals", icon: GitPullRequest },
  { label: "Redemption", href: "/redemption", icon: CreditCard },
  { label: "Points rates", href: "/redemption-rates", icon: Repeat },
  { label: "Services", href: "/services", icon: Tag },
  { label: "Instruments", href: "/instruments", icon: Ticket },
  { label: "User types", href: "/user-types", icon: Users2 },
  { label: "Tenants", href: "/tenants", icon: Settings2 },
  { label: "API keys", href: "/api-keys", icon: KeyRound },
];

const AUDIT: NavItem[] = [
  { label: "Audit log", href: "/audit", icon: ShieldCheck },
  { label: "Events", href: "/events", icon: Receipt },
];

/** A single navigable link row. `indented` shifts children under a parent. */
function NavLink({ item, indented = false }: { item: NavItem; indented?: boolean }) {
  const pathname = usePathname();
  const isActive = pathname === item.href || pathname?.startsWith(`${item.href}/`);
  return (
    <Link
      href={item.href}
      className={cn(
        "group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
        indented && "pl-9",
        isActive
          ? "bg-sidebar-primary text-sidebar-primary-foreground font-medium shadow-sm"
          : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
      )}
    >
      {!indented && (
        <item.icon
          className={cn(
            "h-4 w-4 shrink-0",
            isActive
              ? "text-sidebar-primary-foreground"
              : "text-sidebar-foreground/60 group-hover:text-sidebar-accent-foreground",
          )}
        />
      )}
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
  );
}

/** A collapsible parent header with indented child links. */
function NavParentItem({ parent }: { parent: NavParent }) {
  const pathname = usePathname();
  const hasActiveChild = parent.children.some(
    (c) => pathname === c.href || pathname?.startsWith(`${c.href}/`),
  );
  // Default-open when a child route is active so the user isn't hunting for it.
  const [open, setOpen] = React.useState(hasActiveChild);
  React.useEffect(() => {
    if (hasActiveChild) setOpen(true);
  }, [hasActiveChild]);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className={cn(
          "group flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
          hasActiveChild
            ? "text-sidebar-foreground font-medium"
            : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        )}
      >
        <parent.icon className="h-4 w-4 shrink-0 text-sidebar-foreground/60 group-hover:text-sidebar-accent-foreground" />
        <span className="flex-1 text-left">{parent.label}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-sidebar-foreground/60 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <ul className="mt-0.5 space-y-0.5">
          {parent.children.map((child) => (
            <li key={child.href}>
              <NavLink item={child} indented />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NavGroup({ title, items }: { title: string; items: NavEntry[] }) {
  return (
    <div className="px-3 pb-2">
      <div className="px-2 pb-1.5 pt-3 text-[10px] font-semibold uppercase tracking-wider text-sidebar-foreground/60">
        {title}
      </div>
      <ul className="space-y-0.5">
        {items.map((entry) => (
          <li key={isParent(entry) ? entry.label : entry.href}>
            {isParent(entry) ? (
              <NavParentItem parent={entry} />
            ) : (
              <NavLink item={entry} />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Sidebar({
  pendingCount,
  approvalsPendingCount,
  brandIconUrl,
  showRewards = true,
}: {
  pendingCount?: number;
  approvalsPendingCount?: number;
  brandIconUrl?: string | null;
  /**
   * Whether the active tenant's mode includes a points programme (B6.1).
   * When false the rewards-only sections are dropped entirely — a wallet-only
   * tenant must not see a rewards console it did not buy. Defaults to true so
   * an unresolved tenant fails open to the full nav rather than hiding
   * sections on a loading hiccup.
   */
  showRewards?: boolean;
}) {
  const operations = OPERATIONS.map((item) =>
    item.href === "/reconciliation" && pendingCount
      ? { ...item, badge: pendingCount }
      : item,
  );
  // Surface the total count of PENDING requests awaiting review across the
  // approval queues this admin can see (config + money + user). Rewards-only
  // sections are dropped first for a tenant with no points programme (B6.1).
  const config: NavEntry[] = CONFIG.filter(
    (entry) => showRewards || isParent(entry) || !REWARDS_ONLY_NAV.has(entry.href),
  ).map((entry) => {
    if (isParent(entry)) return entry;
    if (entry.href === "/approvals" && approvalsPendingCount) {
      return { ...entry, badge: approvalsPendingCount };
    }
    return entry;
  });
  return (
    // `border-0 border-r`: Tailwind's utilities layer outranks @layer
    // components, so `border-0` zeroes out `.glass-panel`'s all-side glass
    // border and `border-r` re-adds just the rail's outer edge. `bg-sidebar/90`
    // is likewise a utility, so it beats the glass tint, giving a translucent
    // tenant-accent rail over the blur (product decision: rail stays
    // brand-accent in both schemes). In fallback modes (no backdrop-filter /
    // reduced transparency) the utility still applies over the solid
    // collapse, so the rail stays branded there too. Note: in dark mode
    // `bg-sidebar` is the deep navy `#01101f` at 90% — visually close to the
    // previous dark frost, intended.
    <aside className="glass-panel bg-sidebar/90 rounded-none border-0 border-r flex h-full w-[240px] shrink-0 flex-col">
      <div className="flex h-16 items-center justify-between border-b px-4">
        <Link href="/dashboard" aria-label="Sasai Wallet Admin home" className="flex items-center">
          {brandIconUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            // Height-constrained, width-auto (capped) so a wide wordmark logo
            // shows in full instead of being squished into a small square.
            <img
              src={brandIconUrl}
              alt="Tenant logo"
              className="h-9 w-auto max-w-[150px] rounded-md object-contain"
            />
          ) : (
            <SasaiLogo height={34} />
          )}
        </Link>
        <span className="rounded-full bg-sidebar-accent px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-sidebar-accent-foreground">
          Admin
        </span>
      </div>
      <nav className="flex-1 overflow-y-auto py-2">
        <NavGroup title="Operations" items={operations} />
        <NavGroup title="Configuration" items={config} />
        <NavGroup title="Audit" items={AUDIT} />
      </nav>
      <div className="flex items-center justify-center border-t px-4 py-3">
        <span className="text-sm font-medium text-sidebar-foreground/50">
          v1.0.0
        </span>
      </div>
    </aside>
  );
}
