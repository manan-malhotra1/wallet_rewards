/**
 * UserMenu — operator identity + sign-out. Styled with semantic tokens.
 *
 * Signout uses `next-auth/react`'s client-side `signOut` rather than a
 * server-action <form action> inside the dropdown. Reason: Radix closes
 * the menu (unmounting the Portal'd Content) on click, and React 19's
 * server-action form loses its host element before the NEXT_REDIRECT
 * response is applied — the click looks like a silent no-op. The client
 * helper makes its own fetch + navigation, independent of the menu's
 * lifecycle.
 */
"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { LogOut, User } from "lucide-react";
import { signOut } from "next-auth/react";

import type { TopbarUser } from "./topbar";

export function UserMenu({ user }: { user: TopbarUser }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="inline-flex h-9 items-center gap-2 rounded-md border bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <div className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <User className="h-3 w-3" />
          </div>
          <span className="hidden sm:inline">{user.username}</span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="z-50 w-[240px] rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        >
          <div className="px-2.5 py-2">
            <div className="text-sm font-semibold text-foreground">
              {user.username}
            </div>
            {user.email && (
              <div className="text-[11px] text-muted-foreground">{user.email}</div>
            )}
            <div className="mt-2 flex flex-wrap gap-1">
              {user.roles.map((role) => (
                <span
                  key={role}
                  className="inline-flex items-center rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
                >
                  {role}
                </span>
              ))}
            </div>
          </div>
          <DropdownMenu.Separator className="my-1 h-px bg-border" />
          <DropdownMenu.Item
            onSelect={(event) => {
              // Keep Radix from auto-closing the menu before we've kicked
              // off the signout fetch; `signOut` handles its own redirect
              // to /login when it completes.
              event.preventDefault();
              void signOut({ callbackUrl: "/login" });
            }}
            className="flex w-full cursor-pointer items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
