/**
 * Interaction tests for ManualReviewTable from the admin operator's chair.
 *
 * NOTE ON SCOPE: this component is, as built, a read-only queue of redemptions
 * held for manual review — it renders no per-row approve/fail controls, and no
 * approve/fail server action or backend endpoint exists yet. So rather than
 * fabricate controls that aren't there, these tests assert what an admin
 * actually sees when triaging the queue: each stuck redemption with its amount,
 * retry count, failure reason and review status, and a graceful fallback to a
 * short id when the user's display name is unavailable.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ManualReviewTable } from "@/app/(authenticated)/redemption/_components/manual-review-table";
import type { ManualReviewItem } from "@/lib/api-types";

const named: ManualReviewItem = {
  redemption_id: "11111111-2222-3333-4444-555555555555",
  tenant_id: "tenant-1",
  user_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  user_name: "Jane Doe",
  amount: "1200",
  retry_count: 4,
  failure_reason: "Provider timeout",
};

const anonymous: ManualReviewItem = {
  redemption_id: "99999999-8888-7777-6666-555555555555",
  tenant_id: "tenant-1",
  user_id: "12345678-aaaa-bbbb-cccc-dddddddddddd",
  user_name: null,
  amount: "500",
  retry_count: 2,
  failure_reason: null,
};

describe("Review the manual-review queue", () => {
  it("Verify an admin sees a stuck redemption held for review with its details", () => {
    render(<ManualReviewTable items={[named]} />);

    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("1,200 pts")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Provider timeout")).toBeInTheDocument();
    // The status is shown as an explicit "needs review" pill, never colour alone.
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });

  it("Verify an admin still sees a redemption when the user's name is unavailable", () => {
    render(<ManualReviewTable items={[anonymous]} />);

    // Falls back to a short, prefixed user id rather than showing nothing.
    expect(screen.getByText(/^usr_12345678/)).toBeInTheDocument();
    // No failure reason renders as an em dash, not a blank cell.
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("Verify an admin sees every queued redemption listed for review", () => {
    render(<ManualReviewTable items={[named, anonymous]} />);

    expect(screen.getAllByText("Needs review")).toHaveLength(2);
  });
});
