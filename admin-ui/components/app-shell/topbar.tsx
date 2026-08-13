/**
 * Topbar — tenant switcher, search trigger, notifications, user menu,
 * theme toggle. Styled with Sasai semantic tokens.
 */
"use client";

import { Bell, Moon, Search, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import * as React from "react";

import { Button } from "@/components/ui/button";
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

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);
  if (!mounted) return <span className="h-8 w-8" />;
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      aria-label="Toggle theme"
    >
      {theme === "dark" ? <Sun /> : <Moon />}
    </Button>
  );
}

export function Topbar({ tenants, activeTenantId, user, unreadAlerts = 0 }: TopbarProps) {
  React.useEffect(() => {
    function onKey(e: KeyboardEvent) {
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
    <header className="glass-panel rounded-none border-0 border-b flex h-14 shrink-0 items-center gap-3 px-4">
      <TenantSwitcher tenants={tenants} activeTenantId={activeTenantId} />
      <button
        type="button"
        onClick={openPalette}
        className="flex h-9 max-w-xl flex-1 items-center gap-2 rounded-md border bg-muted/40 px-3 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="flex-1 text-left">Search users, transactions, rules…</span>
        <KbdHint>⌘K</KbdHint>
      </button>
      <div className="flex items-center gap-1.5">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Notifications"
          className="relative"
        >
          <Bell />
          {unreadAlerts > 0 && (
            <span className="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-white">
              {unreadAlerts > 9 ? "9+" : unreadAlerts}
            </span>
          )}
        </Button>
        <ThemeToggle />
        <UserMenu user={user} />
      </div>
    </header>
  );
}
