/**
 * Tests for the Services table's base/derived presentation.
 *
 * The ordering rule itself is unit-tested in `lib/service-catalog.test.ts`.
 * What is left here is the one affordance that must NOT appear: delete on a
 * platform base, which the backend refuses anyway (409
 * base_service_protected), so offering it would only produce a dead end.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ServicesTable } from "@/app/(authenticated)/services/_components/services-table";
import type { Service } from "@/lib/api-types";

vi.mock("@/app/(authenticated)/services/_actions", () => ({
  deleteServiceAction: vi.fn(),
  updateServiceAction: vi.fn(),
}));

vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

function makeService(overrides: Partial<Service> = {}): Service {
  return {
    id: "svc-1",
    tenant_id: "tenant-1",
    code: "p2p",
    display_name: "P2P Transfer",
    description: null,
    status: "active",
    kind: "base",
    base_service_code: null,
    derivable: true,
    readiness: null,
    allowed_user_types: null,
    allowed_channels: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const P2P = makeService();
const CASHOUT = makeService({ id: "svc-2", code: "cashout", display_name: "Cash Out" });
const DIASPORA = makeService({
  id: "svc-3",
  code: "p2p_diaspora",
  display_name: "Diaspora Transfer",
  kind: "derived",
  base_service_code: "p2p",
  derivable: false,
});
const ATM = makeService({
  id: "svc-4",
  code: "cashout_atm",
  display_name: "Cash Out (ATM)",
  kind: "derived",
  base_service_code: "cashout",
  derivable: false,
});

describe("Services table", () => {
  it("Verify a platform base offers no delete, while a derived service does", () => {
    render(<ServicesTable services={[P2P, DIASPORA]} tenantId="tenant-1" />);

    // One delete button in total — the derived row's, not the base's.
    expect(screen.getAllByRole("button", { name: "Delete service" })).toHaveLength(1);
    expect(screen.getByText("Platform")).toBeInTheDocument();
    expect(screen.getByText("Derived")).toBeInTheDocument();
  });
});
