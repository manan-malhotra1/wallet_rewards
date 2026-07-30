/**
 * Interaction tests for <VerifyIdentifierButton> — the admin affordance to
 * manually mark an unverified account_number identifier verified
 * (Epic 27, Story 27.3).
 *
 * These tests drive the button as an admin (click Verify) and assert the action
 * args + refresh on success, and that a backend rejection (e.g. phone/email are
 * not manually verifiable) surfaces inline without refreshing.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VerifyIdentifierButton } from "@/app/(authenticated)/users/_components/verify-identifier-button";

const verifyIdentifierAction = vi.fn();
vi.mock("@/app/(authenticated)/users/_actions", () => ({
  verifyIdentifierAction: (...args: unknown[]) => verifyIdentifierAction(...args),
}));

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  verifyIdentifierAction.mockResolvedValue({ ok: true, verified: true });
});

describe("Managing customers — verifying an account number", () => {
  it("Verify an admin can mark an account number verified", async () => {
    const user = userEvent.setup();
    render(
      <VerifyIdentifierButton
        userId="user-1"
        identifierId="ident-1"
        tenantId="tenant-1"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Verify" }));

    await waitFor(() =>
      expect(verifyIdentifierAction).toHaveBeenCalledWith("user-1", "ident-1", "tenant-1"),
    );
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Identifier verified" }),
    );
    // The server-rendered detail card is refreshed so the badge flips to Verified.
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("Verify a rejected verification shows the reason", async () => {
    verifyIdentifierAction.mockResolvedValue({
      ok: false,
      errorCode: "identifier_not_manually_verifiable",
      message: "Only account numbers can be verified this way.",
    });
    const user = userEvent.setup();
    render(
      <VerifyIdentifierButton
        userId="user-1"
        identifierId="ident-1"
        tenantId="tenant-1"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Verify" }));

    expect(
      await screen.findByText("Only account numbers can be verified this way."),
    ).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });
});
