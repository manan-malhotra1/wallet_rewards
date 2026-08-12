/**
 * Interaction tests for <RecomputeButton> — the manual batch-evaluator
 * recompute trigger.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecomputeButton } from "@/app/(authenticated)/segments/_components/recompute-button";

const recomputeSegmentsAction = vi.fn();
vi.mock("@/app/(authenticated)/segments/_actions", () => ({
  recomputeSegmentsAction: (...args: unknown[]) => recomputeSegmentsAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  recomputeSegmentsAction.mockResolvedValue({ ok: true });
});

describe("Segments — manual recompute trigger", () => {
  it("Verify clicking Recompute now calls the action with the tenant id and toasts success", async () => {
    const user = userEvent.setup();
    render(<RecomputeButton tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: /Recompute now/ }));

    await waitFor(() => expect(recomputeSegmentsAction).toHaveBeenCalledTimes(1));
    expect(recomputeSegmentsAction).toHaveBeenCalledWith("tenant-1");
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Recompute enqueued — memberships refresh shortly",
      }),
    );
  });

  it("Verify a failed recompute surfaces the backend message in a danger toast", async () => {
    recomputeSegmentsAction.mockResolvedValue({
      ok: false,
      errorCode: "tenant_not_found",
      message: "Unknown tenant.",
    });
    const user = userEvent.setup();
    render(<RecomputeButton tenantId="tenant-1" />);

    await user.click(screen.getByRole("button", { name: /Recompute now/ }));

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.objectContaining({
          title: "Couldn't enqueue recompute",
          description: "tenant_not_found: Unknown tenant.",
          variant: "danger",
        }),
      ),
    );
  });
});
