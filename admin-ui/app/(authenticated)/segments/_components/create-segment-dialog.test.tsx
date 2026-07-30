/**
 * Interaction tests for <CreateSegmentDialog> — the admin "New segment" form.
 *
 * These drive the dialog the way an admin does — open it, name the cohort, add
 * an optional description, submit — and assert the outcome the admin cares
 * about: the create-segment action receives exactly the payload typed, a
 * nameless segment is refused before anything is sent, and a backend rejection
 * is shown without closing the form. The server action is mocked; no backend is
 * touched.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateSegmentDialog } from "@/app/(authenticated)/segments/_components/create-segment-dialog";

const createSegmentAction = vi.fn();
vi.mock("@/app/(authenticated)/segments/_actions", () => ({
  createSegmentAction: (...args: unknown[]) => createSegmentAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  createSegmentAction.mockResolvedValue({ ok: true });
});

/** Open the dialog and return its content node. */
async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  render(
    <CreateSegmentDialog
      tenantId="tenant-1"
      trigger={<button type="button">New segment</button>}
    />,
  );
  await user.click(screen.getByRole("button", { name: "New segment" }));
  return screen.findByRole("dialog");
}

describe("Managing reward segments — creating a segment", () => {
  it("Verify an admin can create a customer segment", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Name"), "vip-users");
    await user.type(
      within(dialog).getByLabelText("Description (optional)"),
      "Top 1% by lifetime spend.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createSegmentAction).toHaveBeenCalledTimes(1));
    expect(createSegmentAction.mock.calls[0][0]).toEqual({
      tenant_id: "tenant-1",
      name: "vip-users",
      description: "Top 1% by lifetime spend.",
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Segment created" }),
    );
    // A successful create closes the dialog.
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a segment cannot be created without a name", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Name is required.")).toBeInTheDocument();
    expect(createSegmentAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected segment shows the reason and keeps the form open", async () => {
    createSegmentAction.mockResolvedValue({
      ok: false,
      errorCode: "segment_name_taken",
      message: "A segment with that name already exists.",
    });
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Name"), "vip-users");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/A segment with that name already exists\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
