/**
 * Interaction tests for RequestDetailDrawer — the config maker-checker review
 * surface, driven from the approver's (and the maker's) point of view.
 *
 * These exercise real user actions through the drawer footer: a second admin
 * approving a pending config change, a checker being forced to leave a comment
 * when requesting changes, a backend rejection surfacing its reason, and the
 * maker withdrawing their own request. The payload renderers (ConfigDetail /
 * ConfigCompare) are stubbed — this file tests the review controls, not the
 * config presentation — and a `create` request is used so no history fetch is
 * needed. Server actions are mocked.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RequestDetailDrawer } from "@/app/(authenticated)/config-requests/_components/request-detail-drawer";
import type { ConfigChangeRequest } from "@/lib/api-types";

// The payload presentation isn't under test here — stub it to a plain marker.
vi.mock("@/app/(authenticated)/_components/config-detail", () => ({
  ConfigDetail: () => <div>proposed config</div>,
}));
vi.mock("@/app/(authenticated)/_components/config-compare", () => ({
  ConfigCompare: () => <div>config compare</div>,
}));

// Mock the config-request review verbs.
const approveConfigRequestAction = vi.fn();
const requestConfigChangesAction = vi.fn();
const withdrawConfigRequestAction = vi.fn();
const loadConfigHistoryAction = vi.fn();
vi.mock("@/app/(authenticated)/config-requests/_actions", () => ({
  approveConfigRequestAction: (...args: unknown[]) => approveConfigRequestAction(...args),
  requestConfigChangesAction: (...args: unknown[]) => requestConfigChangesAction(...args),
  withdrawConfigRequestAction: (...args: unknown[]) => withdrawConfigRequestAction(...args),
  loadConfigHistoryAction: (...args: unknown[]) => loadConfigHistoryAction(...args),
}));

const MAKER = "admin-maker";
const CHECKER = "admin-checker";

/** A pending tax `create` request, maker = MAKER (no history to load). */
function makeRequest(overrides: Partial<ConfigChangeRequest> = {}): ConfigChangeRequest {
  return {
    id: "req-1",
    tenant_id: "tenant-1",
    config_type: "tax",
    operation: "create",
    payload: { currency: "ZAR", rate: "0.15" },
    target_config_id: null,
    status: "PENDING",
    maker_admin_id: MAKER,
    maker_admin_name: "Mandla Maker",
    checker_admin_id: null,
    checker_admin_name: null,
    revision: 1,
    created_at: "2026-07-25T00:00:00Z",
    updated_at: "2026-07-25T00:00:00Z",
    reviews: [],
    ...overrides,
  };
}

function renderDrawer(
  request: ConfigChangeRequest,
  currentAdminId: string,
  canApprove: boolean,
) {
  const onUpdated = vi.fn();
  render(
    <RequestDetailDrawer
      request={request}
      tenantId="tenant-1"
      canApprove={canApprove}
      currentAdminId={currentAdminId}
      open
      onOpenChange={vi.fn()}
      onUpdated={onUpdated}
    />,
  );
  return { onUpdated };
}

beforeEach(() => {
  vi.clearAllMocks();
  approveConfigRequestAction.mockResolvedValue({ ok: true, request: makeRequest() });
  requestConfigChangesAction.mockResolvedValue({ ok: true, request: makeRequest() });
  withdrawConfigRequestAction.mockResolvedValue({ ok: true, request: makeRequest() });
  loadConfigHistoryAction.mockResolvedValue({ ok: true, versions: [] });
});

describe("Config change approval drawer", () => {
  it("Verify a second admin can approve a pending config change", async () => {
    const user = userEvent.setup();
    const { onUpdated } = renderDrawer(makeRequest(), CHECKER, true);

    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(approveConfigRequestAction).toHaveBeenCalledWith("tenant-1", "req-1"),
    );
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("Verify requesting changes on a config change needs a comment", async () => {
    const user = userEvent.setup();
    renderDrawer(makeRequest(), CHECKER, true);

    await user.click(screen.getByRole("button", { name: "Request changes" }));
    await user.click(screen.getByRole("button", { name: "Submit comment" }));
    expect(requestConfigChangesAction).not.toHaveBeenCalled();
    expect(
      screen.getByText("A comment is required when requesting changes."),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText("Comment (required)"), "Rate is too high");
    await user.click(screen.getByRole("button", { name: "Submit comment" }));
    await waitFor(() =>
      expect(requestConfigChangesAction).toHaveBeenCalledWith(
        "tenant-1",
        "req-1",
        "Rate is too high",
      ),
    );
  });

  it("Verify a rejected approval attempt on a config change shows the reason", async () => {
    approveConfigRequestAction.mockResolvedValueOnce({
      ok: false,
      errorCode: "maker_checker_self_approval",
      message: "You proposed this change.",
    });
    const user = userEvent.setup();
    renderDrawer(makeRequest(), CHECKER, true);

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(
      await screen.findByText("maker_checker_self_approval: You proposed this change."),
    ).toBeInTheDocument();
  });

  it("Verify the maker can withdraw their own pending config change", async () => {
    const user = userEvent.setup();
    const { onUpdated } = renderDrawer(makeRequest(), MAKER, false);

    await user.click(screen.getByRole("button", { name: "Withdraw" }));

    await waitFor(() =>
      expect(withdrawConfigRequestAction).toHaveBeenCalledWith("tenant-1", "req-1"),
    );
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });
});
