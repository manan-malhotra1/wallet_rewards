/**
 * Topbar — search trigger (⌘K), tenant switcher, notification bell, user
 * menu. Persists at the top of every authenticated page.
 *
 * The ⌘K hotkey lives here in a small effect; the actual palette lives in
 * <CommandPalette> and listens for the `open-command-palette` event.
 */
"use client";

import { Bell, Search } from "lucide-react";
import * as React from "react";

import { KbdHint } from "@/components/ui/kbd-hint";
import { TenantSwitcher } from "@/components/app-shell/tenant-switcher";
import { UserMenu } from "@/components/app-shell/user-menu";

export interface TopbarTenant {
  id: string;
  name: string;
  baseCurrency: string;
}

export interface TopbarUser {
  username: string;
  email?: string;
  roles: string[];
}

export interface TopbarProps {
  tenants: TopbarTenant[];
  activeTenantId: string | null;
  user: TopbarUser;
  unreadAlerts?: number;
}

/**
 * Renders the persistent top bar across every authenticated page. ⌘K
 * triggers a custom event the command palette listens for.
 */
export function Topbar({ tenants, activeTenantId, user, unreadAlerts = 0 }: TopbarProps) {
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // ⌘K (mac) / Ctrl+K (others) → open palette
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("open-command-palette"));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const openPalette = () =>
    window.dispatchEvent(new CustomEvent("open-command-palette"));

  return (
    <header className="flex h-[48px] shrink-0 items-center gap-3 border-b border-[--color-border] bg-[--color-surface-1] px-4">
      <TenantSwitcher tenants={tenants} activeTenantId={activeTenantId} />
      <button
        type="button"
        onClick={openPalette}
        className="flex h-8 flex-1 max-w-[640px] items-center gap-2 rounded-md border border-[--color-border] bg-[--color-surface-0] px-3 text-[12px] text-[--color-text-3] hover:text-[--color-text-2]"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="flex-1 text-left">Search users, transactions, rules…</span>
        <KbdHint>⌘K</KbdHint>
      </button>
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label="Notifications"
          className="relative inline-flex h-8 w-8 items-center justify-center rounded-md text-[--color-text-2] hover:bg-[--color-surface-2] hover:text-[--color-text-1]"
        >
          <Bell className="h-4 w-4" />
          {unreadAlerts > 0 && (
            <span className="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-[--color-danger] px-1 text-[10px] font-semibold text-white">
              {unreadAlerts > 9 ? "9+" : unreadAlerts}
            </span>
          )}
        </button>
        <UserMenu user={user} />
      </div>
    </header>
  );
}
