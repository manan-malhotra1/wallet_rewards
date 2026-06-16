/**
 * Tenant switcher — combobox in the topbar that swaps the active tenant
 * cookie. The selection persists across page reloads via the
 * `sasai_active_tenant` cookie; server components read it to scope queries.
 */
"use client";

import { Check, ChevronsUpDown } from "lucide-react";
import * as Popover from "@radix-ui/react-popover";
import { useRouter } from "next/navigation";
import * as React from "react";

import { setActiveTenantAction } from "@/app/(authenticated)/_actions";
import { cn } from "@/lib/utils";

import type { TopbarTenant } from "./topbar";

export interface TenantSwitcherProps {
  tenants: TopbarTenant[];
  activeTenantId: string | null;
}

/**
 * Renders the active tenant button + a popover with the full list.
 * Clicking an entry calls a server action that updates the cookie and then
 * triggers a full router refresh so server components re-fetch.
 */
export function TenantSwitcher({ tenants, activeTenantId }: TenantSwitcherProps) {
  const [open, setOpen] = React.useState(false);
  const router = useRouter();
  const active = tenants.find((t) => t.id === activeTenantId) ?? tenants[0];

  if (!active) {
    return (
      <span className="text-[12px] text-[--color-text-3]">No tenants</span>
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
          className="inline-flex h-8 items-center gap-2 rounded-md border border-[--color-border] bg-[--color-surface-0] px-2.5 text-[13px] text-[--color-text-1] hover:bg-[--color-surface-2]"
        >
          <span className="font-medium">{active.name}</span>
          <span className="text-[--color-text-3]">{active.baseCurrency}</span>
          <ChevronsUpDown className="h-3 w-3 text-[--color-text-3]" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="z-50 w-[240px] rounded-md border border-[--color-border] bg-[--color-surface-1] p-1 shadow-xl"
        >
          <div className="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-[--color-text-3]">
            Switch tenant
          </div>
          <ul className="space-y-px">
            {tenants.map((t) => (
              <li key={t.id}>
                <button
                  type="button"
                  onClick={() => handleSwitch(t.id)}
                  className={cn(
                    "flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-[13px] hover:bg-[--color-surface-2]",
                    t.id === active.id && "bg-[--color-surface-2]",
                  )}
                >
                  <div>
                    <div className="font-medium">{t.name}</div>
                    <div className="text-[11px] text-[--color-text-3]">
                      {t.baseCurrency}
                    </div>
                  </div>
                  {t.id === active.id && (
                    <Check className="h-3.5 w-3.5 text-[--color-success]" />
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
