/**
 * Tenant switcher — combobox in the topbar. Styled with semantic tokens.
 */
"use client";

import * as Popover from "@radix-ui/react-popover";
import { Building2, Check, ChevronsUpDown } from "lucide-react";
import { useRouter } from "next/navigation";
import * as React from "react";

import { setActiveTenantAction } from "@/app/(authenticated)/_actions";
import { cn } from "@/lib/utils";

import type { TopbarTenant } from "./topbar";

export interface TenantSwitcherProps {
  tenants: TopbarTenant[];
  activeTenantId: string | null;
}

export function TenantSwitcher({ tenants, activeTenantId }: TenantSwitcherProps) {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();
  const active = tenants.find((t) => t.id === activeTenantId) ?? tenants[0];

  if (!active) {
    return (
      <span className="text-xs text-muted-foreground">No tenants</span>
    );
  }

  const handleSwitch = async (tenantId: string) => {
    setOpen(false);
    await setActiveTenantAction(tenantId);
    router.refresh();
  };

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          className="inline-flex h-9 items-center gap-2 rounded-md border bg-background px-3 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-foreground">{active.name}</span>
          <span className="text-xs text-muted-foreground">{active.baseCurrency}</span>
          <ChevronsUpDown className="h-3 w-3 text-muted-foreground" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={6}
          className="glass-overlay z-50 w-[260px] rounded-md p-1 text-popover-foreground"
        >
          <div className="px-2 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Switch tenant
          </div>
          <ul className="space-y-0.5">
            {tenants.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => handleSwitch(t.id)}
                  className={cn(
                    "flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground",
                    t.id === active.id && "bg-accent text-accent-foreground",
                  )}
                >
                  <div>
                    <div className="font-medium">{t.name}</div>
                    <div className="text-[11px] text-muted-foreground">
                      {t.baseCurrency}
                    </div>
                  </div>
                  {t.id === active.id && (
                    <Check className="h-3.5 w-3.5 text-emerald-500" />
                  )}
                </button>
              </li>
            ))}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
