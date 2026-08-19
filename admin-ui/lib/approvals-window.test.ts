/**
 * Tests for the approvals server-window helpers (Story B7.1) — parsing the
 * server-driven status/page URL params and mapping the backend /counts shape
 * into the toolbar's segment counts.
 */
import { describe, expect, it } from "vitest";

import {
  APPROVALS_PAGE_SIZE,
  pageCount,
  readPage,
  readServerQ,
  readServerStatus,
  serverStatusParam,
  statusCountsWithAll,
  windowOffset,
} from "./approvals-window";

describe("readServerQ", () => {
  it("trims the query and defaults to empty", () => {
    expect(readServerQ("  alpha ")).toBe("alpha");
    expect(readServerQ(undefined)).toBe("");
    expect(readServerQ("   ")).toBe("");
  });
});

describe("readServerStatus", () => {
  it("accepts each lifecycle status and ALL", () => {
    expect(readServerStatus("PENDING")).toBe("PENDING");
    expect(readServerStatus("CHANGES_REQUESTED")).toBe("CHANGES_REQUESTED");
    expect(readServerStatus("APPLIED")).toBe("APPLIED");
    expect(readServerStatus("WITHDRAWN")).toBe("WITHDRAWN");
    expect(readServerStatus("ALL")).toBe("ALL");
  });

  it("defaults to PENDING for missing or junk values", () => {
    expect(readServerStatus(undefined)).toBe("PENDING");
    expect(readServerStatus("nonsense")).toBe("PENDING");
    expect(readServerStatus("pending")).toBe("PENDING");
  });
});

describe("serverStatusParam", () => {
  it("passes a specific status through and drops ALL", () => {
    expect(serverStatusParam("APPLIED")).toBe("APPLIED");
    expect(serverStatusParam("ALL")).toBeUndefined();
  });
});

describe("readPage / windowOffset", () => {
  it("parses a positive integer page and defaults to 1", () => {
    expect(readPage("3")).toBe(3);
    expect(readPage(undefined)).toBe(1);
    expect(readPage("0")).toBe(1);
    expect(readPage("-2")).toBe(1);
    expect(readPage("2.5")).toBe(1);
    expect(readPage("junk")).toBe(1);
  });

  it("computes the offset for a 1-based page", () => {
    expect(windowOffset(1, 200)).toBe(0);
    expect(windowOffset(3, 200)).toBe(400);
  });
});

describe("statusCountsWithAll", () => {
  it("maps the backend by_status shape and adds ALL as the total", () => {
    expect(
      statusCountsWithAll({
        total: 7,
        by_status: { PENDING: 4, CHANGES_REQUESTED: 1, APPLIED: 2, WITHDRAWN: 0 },
      }),
    ).toEqual({ PENDING: 4, CHANGES_REQUESTED: 1, APPLIED: 2, WITHDRAWN: 0, ALL: 7 });
  });

  it("zero-fills statuses the backend omits", () => {
    expect(statusCountsWithAll({ total: 1, by_status: { PENDING: 1 } })).toEqual({
      PENDING: 1,
      CHANGES_REQUESTED: 0,
      APPLIED: 0,
      WITHDRAWN: 0,
      ALL: 1,
    });
  });
});

describe("pageCount", () => {
  it("rounds up and never drops below one page", () => {
    expect(pageCount(0, 200)).toBe(1);
    expect(pageCount(200, 200)).toBe(1);
    expect(pageCount(201, 200)).toBe(2);
  });
});

describe("APPROVALS_PAGE_SIZE", () => {
  it("stays within the backend's limit cap of 500", () => {
    expect(APPROVALS_PAGE_SIZE).toBeGreaterThan(0);
    expect(APPROVALS_PAGE_SIZE).toBeLessThanOrEqual(500);
  });
});
