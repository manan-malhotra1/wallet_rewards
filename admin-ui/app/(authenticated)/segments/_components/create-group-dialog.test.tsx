/**
 * Interaction tests for <CreateGroupDialog> — the admin "New segment group"
 * form.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateGroupDialog } from "@/app/(authenticated)/segments/_components/create-group-dialog";

const createSegmentGroupAction = vi.fn();
vi.mock("@/app/(authenticated)/segments/_actions", () => ({
  createSegmentGroupAction: (...args: unknown[]) => createSegmentGroupAction(...args),
}));

const toast = vi.fn();
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  createSegmentGroupAction.mockResolvedValue({ ok: true });
});

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  render(
    <CreateGroupDialog tenantId="tenant-1" trigger={<button type="button">New group</button>} />,
  );
  await user.click(screen.getByRole("button", { name: "New group" }));
  return screen.findByRole("dialog");
}

describe("Managing segment groups — creating a group", () => {
  it("Verify an admin can create a group with a name and description", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Name"), "Loyalty");
    await user.type(
      within(dialog).getByLabelText("Description (optional)"),
      "Tenure-based loyalty tiers.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(createSegmentGroupAction).toHaveBeenCalledTimes(1));
    expect(createSegmentGroupAction).toHaveBeenCalledWith({
      tenant_id: "tenant-1",
      name: "Loyalty",
      description: "Tenure-based loyalty tiers.",
    });
    expect(toast).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Group created" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("Verify a group cannot be created without a name", async () => {
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Name is required.")).toBeInTheDocument();
    expect(createSegmentGroupAction).not.toHaveBeenCalled();
  });

  it("Verify a rejected group create shows the reason and keeps the dialog open", async () => {
    createSegmentGroupAction.mockResolvedValue({
      ok: false,
      errorCode: "segment_group_name_taken",
      message: "A group with that name already exists.",
    });
    const user = userEvent.setup();
    const dialog = await openDialog(user);

    await user.type(within(dialog).getByLabelText("Name"), "Loyalty");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText(/A group with that name already exists\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
