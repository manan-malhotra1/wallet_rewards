/**
 * Behaviour tests for ConfigViewButton's version-history panel.
 *
 * The motivating change: a seed-created config has no applied maker-checker
 * history, so the backend now synthesizes a single "current" baseline version
 * (`synthesized: true`) rather than returning an empty list. These tests lock
 * in that (1) that lone baseline still renders as a row labelled
 * "Current (baseline)" — not the old "No prior versions" dead-end — and is
 * never offered for restore (it already is current), and (2) a real multi-
 * version history is unaffected: prior versions still expose "Make this version
 * latest".
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfigViewButton } from "@/app/(authenticated)/_components/config-view-button";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { ConfigChangeRequest } from "@/lib/api-types";

// The history + restore server actions — the panel is unit-tested against the
// versions it renders, not the backend it fetches them from.
const loadConfigHistoryAction = vi.fn();
const proposeConfigUpdateAction = vi.fn().mockResolvedValue({ ok: true });
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  loadConfigHistoryAction: (...args: unknown[]) => loadConfigHistoryAction(...args),
  proposeConfigUpdateAction: (...args: unknown[]) => proposeConfigUpdateAction(...args),
}));

/** A minimal live limit config row (also used as the synthesized payload). */
const liveLimit: Record<string, unknown> = {
  transaction_type: "cashout",
  account_type: "financial_wallet",
  currency: "ZAR",
  user_type: "consumer",
  min_amount: "10",
  max_amount: "5000",
};

/** Build a history entry with sensible defaults. */
function version(overrides: Partial<ConfigChangeRequest>): ConfigChangeRequest {
  return {
    id: "req-1",
    tenant_id: "tenant-1",
    config_type: "limit",
    operation: "create",
    payload: liveLimit,
    target_config_id: null,
    status: "APPLIED",
    maker_admin_id: "system",
    maker_admin_name: null,
    checker_admin_id: null,
    checker_admin_name: null,
    revision: 1,
    created_at: "2026-07-25T00:00:00Z",
    updated_at: "2026-07-25T00:00:00Z",
    reviews: [],
    ...overrides,
  };
}

function renderButton() {
  return render(
    <TooltipProvider>
      <ConfigViewButton
        configType="limit"
        data={liveLimit}
        title="Limit — cashout"
        tenantId="tenant-1"
        targetConfigId="live-limit-1"
        canPropose
        changeProposed={false}
      />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ConfigViewButton version history — synthesized baseline", () => {
  it("renders a lone synthesized baseline as 'Current (baseline)' with no restore", async () => {
    loadConfigHistoryAction.mockResolvedValue({
      ok: true,
      versions: [version({ id: "live-limit-1", synthesized: true })],
    });
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: "View" }));

    // The baseline row appears (not the "No prior versions" dead-end)...
    expect(await screen.findByText("Current (baseline)")).toBeInTheDocument();
    expect(screen.queryByText("No prior versions.")).not.toBeInTheDocument();
    // ...attributed to the system (no real maker), not "Unknown".
    expect(screen.getByText(/· System/)).toBeInTheDocument();
    // ...and it's the current config, so it can't be "made latest".
    expect(
      screen.queryByRole("button", { name: "Make this version latest" }),
    ).not.toBeInTheDocument();
    // A single version has nothing to compare against.
    expect(
      screen.queryByRole("button", { name: /Compare versions/ }),
    ).not.toBeInTheDocument();
  });

  it("still offers restore on prior versions when real applied history exists", async () => {
    loadConfigHistoryAction.mockResolvedValue({
      ok: true,
      versions: [
        version({ id: "req-1", maker_admin_name: "Alice" }),
        version({ id: "req-2", operation: "update", maker_admin_name: "Bob" }),
      ],
    });
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: "View" }));

    // Newest is the active version; the older one can be restored.
    expect(await screen.findByText("Active · v2")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Make this version latest" }),
    ).toBeInTheDocument();
  });
});
