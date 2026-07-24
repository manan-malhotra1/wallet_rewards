/**
 * Tests for the audit-log humanization helpers — the plain-language phrasing
 * shared by the audit table row and detail drawer.
 */
import { describe, expect, it } from "vitest";

import {
  actorLocationLabel,
  actorRoleLabel,
  auditActionLabel,
  diffStates,
  humanizeStatus,
} from "@/lib/audit-labels";
import type { AuditEntry } from "@/lib/api-types";

/** Minimal AuditEntry factory — only the fields these helpers read. */
function entry(overrides: Partial<AuditEntry>): AuditEntry {
  return {
    id: "a1",
    tenant_id: "t1",
    actor_id: "admin-1",
    actor_type: "admin",
    actor_name: "Alice",
    action: "user.updated",
    entity_type: "user",
    entity_id: "u1",
    entity_name: "Bob",
    before_state: null,
    after_state: null,
    ip_address: null,
    note: null,
    created_at: "2026-07-25T00:00:00Z",
    ...overrides,
  };
}

describe("auditActionLabel maps known codes and access transitions", () => {
  it("returns the friendly label for a known action code", () => {
    expect(auditActionLabel(entry({ action: "pin.changed" }))).toBe("PIN changed");
  });

  it("humanizes an unknown code instead of leaking the raw dotted code", () => {
    const label = auditActionLabel(entry({ action: "widget.frobnicated" }));
    expect(label).toBe("Widget frobnicated");
    expect(label).not.toContain(".");
    expect(label).not.toContain("_");
  });

  it("reads active→suspended as 'Login locked'", () => {
    const label = auditActionLabel(
      entry({
        action: "admin.user_access_changed",
        before_state: { status: "active" },
        after_state: { status: "suspended" },
      }),
    );
    expect(label).toBe("Login locked");
  });

  it("reads suspended→active as 'Login access restored'", () => {
    const label = auditActionLabel(
      entry({
        action: "admin.user_access_changed",
        before_state: { status: "suspended" },
        after_state: { status: "active" },
      }),
    );
    expect(label).toBe("Login access restored");
  });

  it("reads any →txn_locked as 'Transactions locked'", () => {
    const label = auditActionLabel(
      entry({
        action: "admin.user_access_changed",
        before_state: { status: "active" },
        after_state: { status: "txn_locked" },
      }),
    );
    expect(label).toBe("Transactions locked");
  });

  it("falls back to the base access label when no transition can be derived", () => {
    const label = auditActionLabel(
      entry({
        action: "admin.user_access_changed",
        before_state: null,
        after_state: null,
      }),
    );
    expect(label).toBe("User access changed");
  });
});

describe("humanizeStatus renders raw status codes", () => {
  it("maps txn_locked to 'Transactions locked'", () => {
    expect(humanizeStatus("txn_locked")).toBe("Transactions locked");
  });

  it("maps active to 'Active'", () => {
    expect(humanizeStatus("active")).toBe("Active");
  });

  it("humanizes an unknown status token", () => {
    expect(humanizeStatus("pending_review")).toBe("Pending review");
  });
});

describe("actor role and location labels", () => {
  it("labels admin/user/system roles", () => {
    expect(actorRoleLabel("admin")).toBe("Admin");
    expect(actorRoleLabel("user")).toBe("User");
    expect(actorRoleLabel("system")).toBe("System");
  });

  it("labels where the action originated", () => {
    expect(actorLocationLabel("admin")).toBe("Admin portal");
    expect(actorLocationLabel("user")).toBe("Mobile app");
    expect(actorLocationLabel("system")).toBe("System");
  });
});

describe("diffStates emits one line per changed key only", () => {
  it("skips unchanged keys and keeps only what differs", () => {
    const lines = diffStates(
      { first_name: "Bob", last_name: "Jones" },
      { first_name: "Bob", last_name: "Smith" },
    );
    expect(lines).toHaveLength(1);
    expect(lines[0].key).toBe("last_name");
    expect(lines[0].from).toBe("Jones");
    expect(lines[0].to).toBe("Smith");
  });

  it("humanizes a status value on both sides of the diff", () => {
    const [line] = diffStates({ status: "active" }, { status: "txn_locked" });
    expect(line.from).toBe("Active");
    expect(line.to).toBe("Transactions locked");
  });

  it("renders booleans as Yes/No", () => {
    const [line] = diffStates({ verified: false }, { verified: true });
    expect(line.from).toBe("No");
    expect(line.to).toBe("Yes");
  });

  it("labels a nullish previous value as an em dash", () => {
    const [line] = diffStates(null, { first_name: "Bob" });
    expect(line.from).toBe("—");
    expect(line.to).toBe("Bob");
    expect(line.label).toBe("First name");
  });
});
