/**
 * Command palette (⌘K). Styled with Sasai semantic tokens.
 */
"use client";

import { Command } from "cmdk";
import {
  ArrowRight,
  Box,
  Coins,
  CreditCard,
  Gauge,
  Megaphone,
  Layers,
  ListChecks,
  Receipt,
  ScanLine,
  Settings2,
  ShieldCheck,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { setActiveTenantAction } from "@/app/(authenticated)/_actions";
import { Dialog, DialogContent } from "@/components/ui/dialog";

import type { TopbarTenant } from "@/components/app-shell/topbar";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV: NavItem[] = [
  { label: "Go to Dashboard", href: "/dashboard", icon: Gauge },
  { label: "Go to Users", href: "/users", icon: Users },
  { label: "Go to Merchants", href: "/merchants", icon: Box },
  { label: "Go to Reconciliation", href: "/reconciliation", icon: ScanLine },
  { label: "Go to Campaigns", href: "/campaigns", icon: Megaphone },
  { label: "Go to Segments", href: "/segments", icon: Layers },
  { label: "Go to Limits", href: "/limits", icon: ListChecks },
  { label: "Go to Pricing", href: "/pricing", icon: Coins },
  { label: "Go to Redemption", href: "/redemption", icon: CreditCard },
  { label: "Go to Tenants", href: "/tenants", icon: Settings2 },
  { label: "Go to Audit log", href: "/audit", icon: ShieldCheck },
  { label: "Go to Events", href: "/events", icon: Receipt },
];

export interface CommandPaletteProps {
  tenants: TopbarTenant[];
  activeTenantId: string | null;
}

export function CommandPalette({ tenants, activeTenantId }: CommandPaletteProps) {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();

  React.useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener("open-command-palette", handler);
    return () => window.removeEventListener("open-command-palette", handler);
  }, []);

  React.useEffect(() => {
    let armed: ReturnType<typeof setTimeout> | null = null;
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLElement) {
        const tag = e.target.tagName;
        if (tag === "INPUT" || tag === "TEXTAREA" || e.target.isContentEditable) {
          return;
        }
      }
      if (e.key.toLowerCase() === "g" && !armed) {
        armed = setTimeout(() => {
          armed = null;
        }, 600);
        return;
      }
      if (armed) {
        clearTimeout(armed);
        armed = null;
        const map: Record<string, string> = {
          d: "/dashboard",
          u: "/users",
          r: "/campaigns",
          a: "/audit",
          m: "/merchants",
          c: "/reconciliation",
          p: "/redemption",
          t: "/tenants",
          e: "/events",
        };
        const dest = map[e.key.toLowerCase()];
        if (dest) {
          e.preventDefault();
          router.push(dest);
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  const handleNav = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  const handleTenantSwitch = async (tenantId: string) => {
    setOpen(false);
    await setActiveTenantAction(tenantId);
    router.refresh();
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="top-[20%] max-w-2xl translate-y-0 gap-0 p-0">
        <Command label="Command palette" className="w-full">
          <Command.Input
            placeholder="Type a command or search…"
            className="h-12 w-full border-b bg-transparent px-4 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
          />
          <Command.List className="max-h-[420px] overflow-y-auto p-2">
            <Command.Empty className="px-3 py-6 text-center text-xs text-muted-foreground">
              No results.
            </Command.Empty>
            <Command.Group
              heading="Navigate"
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"
            >
              {NAV.map((item) => (
                <Command.Item
                  key={item.href}
                  value={item.label}
                  onSelect={() => handleNav(item.href)}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md px-3 py-2 text-sm text-foreground data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
                >
                  <item.icon className="h-4 w-4 text-muted-foreground" />
                  <span className="flex-1">{item.label}</span>
                  <ArrowRight className="h-3 w-3 text-muted-foreground" />
                </Command.Item>
              ))}
            </Command.Group>
            {tenants.length > 1 && (
              <Command.Group
                heading="Switch tenant"
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-muted-foreground"
              >
                {tenants.map((tenant) => (
                  <Command.Item
                    key={tenant.id}
                    value={`switch tenant ${tenant.name}`}
                    onSelect={() => handleTenantSwitch(tenant.id)}
                    className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground"
                  >
                    <span className="flex-1">{tenant.name}</span>
                    <span className="text-[11px] text-muted-foreground">
                      {tenant.baseCurrency}
                    </span>
                    {tenant.id === activeTenantId && (
                      <span className="text-[11px] text-emerald-500">●</span>
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
