/**
 * Interaction tests for <CriteriaBuilder> — the dynamic-segment condition
 * editor. Drives it the way an admin does: add a condition, fill it in,
 * switch metrics, remove a row — and asserts the emitted `SegmentCriteriaDoc`
 * and the footer's validation/summary text. No backend is touched; this is
 * a pure controlled component.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CriteriaBuilder } from "@/app/(authenticated)/segments/_components/criteria-builder";
import type { SegmentCriteriaDoc, SegmentMetricInfo, Service } from "@/lib/api-types";
import { emptyCriteria, summarizeCriteria } from "@/lib/segment-criteria";

const METRICS: SegmentMetricInfo[] = [
  { name: "txn_sum", supports_txn_type: true, supports_window: true },
  { name: "account_age_days", supports_txn_type: false, supports_window: false },
];

const SERVICES: Service[] = [
  {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "p2p",
    display_name: "P2P transfer",
    description: null,
    status: "active",
    allowed_user_types: null,
    allowed_channels: null,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  },
];

/** Render the builder with a fresh spy for onChange and return both. */
function renderBuilder(value: SegmentCriteriaDoc, metrics: SegmentMetricInfo[] = METRICS) {
  const onChange = vi.fn();
  render(
    <CriteriaBuilder value={value} metrics={metrics} services={SERVICES} onChange={onChange} />,
  );
  return { onChange };
}

describe("CriteriaBuilder — building a dynamic segment's conditions", () => {
  it("Verify an empty document shows the validation message, not a summary", () => {
    renderBuilder(emptyCriteria());
    expect(screen.getByText("Add at least one condition.")).toBeInTheDocument();
  });

  it("Verify adding a condition emits a document with one condition on the first metric", async () => {
    const user = userEvent.setup();
    const { onChange } = renderBuilder(emptyCriteria());

    await user.click(screen.getByRole("button", { name: "Add condition" }));

    expect(onChange).toHaveBeenCalledWith({
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum" }],
    });
  });

  it("Verify a metric that supports filters shows the txn-type and window inputs", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", gte: 100 }],
    };
    renderBuilder(doc);

    expect(screen.getByLabelText("Condition 1 transaction type")).toBeInTheDocument();
    expect(screen.getByLabelText("Condition 1 window in days")).toBeInTheDocument();
  });

  it("Verify a metric with no supported filters hides the txn-type and window inputs", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "account_age_days", gte: 30 }],
    };
    renderBuilder(doc);

    expect(screen.queryByLabelText("Condition 1 transaction type")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Condition 1 window in days")).not.toBeInTheDocument();
  });

  it("Verify switching to a metric without filter support clears txn_type and window_days", async () => {
    const user = userEvent.setup();
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", txn_type: "p2p", window_days: 90, gte: 100 }],
    };
    const { onChange } = renderBuilder(doc);

    await user.click(screen.getByRole("combobox", { name: "Metric" }));
    await user.click(await screen.findByRole("option", { name: "account_age_days" }));

    expect(onChange).toHaveBeenCalledWith({
      v: 1,
      op: "AND",
      conditions: [{ metric: "account_age_days", txn_type: undefined, window_days: undefined, gte: 100 }],
    });
  });

  it("Verify removing a condition emits the document with just that row dropped", async () => {
    const user = userEvent.setup();
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [
        { metric: "txn_sum", gte: 100 },
        { metric: "account_age_days", gte: 30 },
      ],
    };
    const { onChange } = renderBuilder(doc);

    await user.click(screen.getByRole("button", { name: "Remove condition 1" }));

    expect(onChange).toHaveBeenCalledWith({
      v: 1,
      op: "AND",
      conditions: [{ metric: "account_age_days", gte: 30 }],
    });
  });

  it("Verify a valid document's footer renders the summarizeCriteria text as a live status region", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", gte: 100 }],
    };
    renderBuilder(doc);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(summarizeCriteria(doc));
  });

  it("Verify clearing a threshold field back to empty emits undefined, not 0", async () => {
    const user = userEvent.setup();
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", gte: 100 }],
    };
    const { onChange } = renderBuilder(doc);

    await user.clear(screen.getByLabelText("Condition 1 minimum"));

    expect(onChange).toHaveBeenLastCalledWith({
      v: 1,
      op: "AND",
      conditions: [{ metric: "txn_sum", gte: undefined }],
    });
  });

  it("Verify Add condition is disabled once the document already has 10 conditions", () => {
    const doc: SegmentCriteriaDoc = {
      v: 1,
      op: "AND",
      conditions: Array.from({ length: 10 }, () => ({ metric: "account_age_days", gte: 1 })),
    };
    renderBuilder(doc);

    expect(screen.getByRole("button", { name: "Add condition" })).toBeDisabled();
  });

  it("Verify Add condition is disabled when there is no metric vocabulary to add from", () => {
    renderBuilder(emptyCriteria(), []);

    expect(screen.getByRole("button", { name: "Add condition" })).toBeDisabled();
  });
});
