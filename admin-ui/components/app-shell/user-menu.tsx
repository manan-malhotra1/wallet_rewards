/**
 * UserMenu — shows the authenticated operator's username + their realm
 * roles, with a sign-out action.
 */
"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { LogOut, User } from "lucide-react";

import { signOutAction } from "@/app/(authenticated)/_actions";

import type { TopbarUser } from "./topbar";

export function UserMenu({ user }: { user: TopbarUser }) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className="inline-flex h-8 items-center gap-2 rounded-md border border-[--color-border] bg-[--color-surface-0] px-2 text-[12px] text-[--color-text-1] hover:bg-[--color-surface-2]"
        >
          <User className="h-3.5 w-3.5" />
          <span className="hidden text-[12px] font-medium sm:inline">
            {user.username}
          </span>
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          className="z-50 w-[220px] rounded-md border border-[--color-border] bg-[--color-surface-1] p-1 text-[13px] shadow-xl"
        >
          <div className="px-2 py-2">
            <div className="text-[12px] font-medium text-[--color-text-1]">
              {user.username}
            </div>
            {user.email && (
              <div className="text-[11px] text-[--color-text-3]">{user.email}</div>
            )}
            <div className="mt-2 flex flex-wrap gap-1">
              {user.roles.map((role) => (
                <span
                  key={role}
                  className="inline-flex items-center rounded bg-[--color-surface-3] px-1.5 py-0.5 text-[10px] text-[--color-text-2]"
                >
                  {role}
                </span>
              ))}
            </div>
          </div>
          <DropdownMenu.Separator className="my-1 h-px bg-[--color-border]" />
          <form action={signOutAction}>
            <DropdownMenu.Item asChild>
              <button
                type="submit"
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[--color-text-1] hover:bg-[--color-surface-2]"
              >
                <LogOut className="h-3.5 w-3.5" />
                Sign out
              </button>
            </DropdownMenu.Item>
          </form>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
