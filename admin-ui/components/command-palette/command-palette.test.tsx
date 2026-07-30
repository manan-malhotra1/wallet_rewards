/**
 * Interaction tests for <CommandPalette> — the global ⌘K launcher.
 *
 * The palette opens on a window `open-command-palette` event, fuzzy-filters its
 * command list as the admin types, and on selecting an item either navigates
 * (Navigate group) or switches the active tenant (Switch tenant group). These
 * tests drive it as an admin would and assert the navigation / tenant-switch
 * side effects. next/navigation and the tenant-switch action are mocked.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CommandPalette } from "@/components/command-palette/command-palette";
import type { TopbarTenant } from "@/components/app-shell/topbar";

// cmdk observes its list for resizing; jsdom omits ResizeObserver, so shim it.
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, refresh }),
}));

const setActiveTenantAction = vi.fn();
vi.mock("@/app/(authenticated)/_actions", () => ({
  setActiveTenantAction: (...args: unknown[]) => setActiveTenantAction(...args),
}));

const TENANTS: TopbarTenant[] = [
  { id: "tenant-1", name: "Sasai ZA", baseCurrency: "ZAR" },
  { id: "tenant-2", name: "Sasai ZW", baseCurrency: "USD" },
];

/** Render the palette and fire the global open event so it appears. */
async function openPalette(tenants: TopbarTenant[] = TENANTS, activeTenantId = "tenant-1") {
  const user = userEvent.setup();
  render(<CommandPalette tenants={tenants} activeTenantId={activeTenantId} />);
  fireEvent(window, new Event("open-command-palette"));
  await screen.findByPlaceholderText("Type a command or search…");
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  setActiveTenantAction.mockResolvedValue(undefined);
});

describe("Command palette", () => {
  it("Verify the command palette opens and runs a command", async () => {
    const user = await openPalette();

    await user.click(screen.getByText("Go to Users"));

    // Selecting a Navigate item routes to its destination.
    expect(push).toHaveBeenCalledWith("/users");
  });

  it("Verify an admin can search the command palette to find a command", async () => {
    const user = await openPalette();

    await user.type(screen.getByPlaceholderText("Type a command or search…"), "audit");

    // Fuzzy filter keeps the matching command and drops the rest.
    expect(await screen.findByText("Go to Audit log")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("Go to Users")).not.toBeInTheDocument(),
    );
  });

  it("Verify an admin can switch tenant from the command palette", async () => {
    const user = await openPalette();

    await user.click(screen.getByText("Sasai ZW"));

    // Switching tenant persists the choice and refreshes server data.
    await waitFor(() =>
      expect(setActiveTenantAction).toHaveBeenCalledWith("tenant-2"),
    );
    expect(refresh).toHaveBeenCalled();
  });
});
