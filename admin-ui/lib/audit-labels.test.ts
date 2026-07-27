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

describe("Audit log wording", () => {
  it("Verify a known admin action reads as plain language in the audit log", () => {
    expect(auditActionLabel(entry({ action: "pin.changed" }))).toBe("PIN changed");
  });

  it("Verify an unrecognised action still shows as readable words, never a raw code", () => {
    const label = auditActionLabel(entry({ action: "widget.frobnicated" }));
    expect(label).toBe("Widget frobnicated");
    expect(label).not.toContain(".");
    expect(label).not.toContain("_");
  });

  it("Verify suspending a user is recorded as 'Login locked' in the audit log", () => {
    const label = auditActionLabel(
      entry({
        action: "admin.user_access_changed",
        before_state: { status: "active" },
        after_state: { status: "suspended" },
      }),
    );
    expect(label).toBe("Login locked");
  });

  it("Verify restoring a suspended user is recorded as 'Login access restored'", () => {
    const label = auditActionLabel(
      entry({
        action: "admin.user_access_changed",
        before_state: { status: "suspended" },
        after_state: { status: "active" },
      }),
    );
    expect(label).toBe("Login access restored");
  });

  it("Verify blocking a user's transactions is recorded as 'Transactions locked'", () => {
    const label = auditActionLabel(
      entry({
        action: "admin.user_access_changed",
        before_state: { status: "active" },
        after_state: { status: "txn_locked" },
      }),
    );
    expect(label).toBe("Transactions locked");
  });

  it("Verify a general access change reads as 'User access changed' when the before and after are unknown", () => {
    const label = auditActionLabel(
      entry({
        action: "admin.user_access_changed",
        before_state: null,
        after_state: null,
      }),
    );
    expect(label).toBe("User access changed");
  });

  it("Verify a transaction-locked account is shown as 'Transactions locked'", () => {
    expect(humanizeStatus("txn_locked")).toBe("Transactions locked");
  });

  it("Verify an active account is shown as 'Active'", () => {
    expect(humanizeStatus("active")).toBe("Active");
  });

  it("Verify an unrecognised account status is still shown as readable words", () => {
    expect(humanizeStatus("pending_review")).toBe("Pending review");
  });

  it("Verify admin, user and system actors are named in plain language", () => {
    expect(actorRoleLabel("admin")).toBe("Admin");
    expect(actorRoleLabel("user")).toBe("User");
    expect(actorRoleLabel("system")).toBe("System");
  });

  it("Verify the audit log shows where an action came from (admin portal or mobile app)", () => {
    expect(actorLocationLabel("admin")).toBe("Admin portal");
    expect(actorLocationLabel("user")).toBe("Mobile app");
    expect(actorLocationLabel("system")).toBe("System");
  });

  it("Verify a change shows only the fields that actually changed", () => {
    const lines = diffStates(
      { first_name: "Bob", last_name: "Jones" },
      { first_name: "Bob", last_name: "Smith" },
    );
    expect(lines).toHaveLength(1);
    expect(lines[0].key).toBe("last_name");
    expect(lines[0].from).toBe("Jones");
    expect(lines[0].to).toBe("Smith");
  });

  it("Verify a status change is shown in plain words on both the old and new values", () => {
    const [line] = diffStates({ status: "active" }, { status: "txn_locked" });
    expect(line.from).toBe("Active");
    expect(line.to).toBe("Transactions locked");
  });

  it("Verify true/false values are shown as Yes and No", () => {
    const [line] = diffStates({ verified: false }, { verified: true });
    expect(line.from).toBe("No");
    expect(line.to).toBe("Yes");
  });

  it("Verify a previously empty value is shown as a dash next to its readable field name", () => {
    const [line] = diffStates(null, { first_name: "Bob" });
    expect(line.from).toBe("—");
    expect(line.to).toBe("Bob");
    expect(line.label).toBe("First name");
  });
});
