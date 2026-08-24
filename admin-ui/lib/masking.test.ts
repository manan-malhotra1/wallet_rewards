/**
 * Tests for the PII masking helpers (NFR-0240).
 *
 * These guard the one thing that matters: a value that leaves a server action
 * for the browser must never carry the middle of a phone number.
 */
import { describe, expect, it } from "vitest";

import { maskPhone } from "@/lib/masking";

describe("maskPhone", () => {
  it("keeps only the first and last four digits", () => {
    expect(maskPhone("+27825550142")).toBe("+2782 *** 0142");
  });

  it("masks the same regardless of separators", () => {
    expect(maskPhone("+27 82 555 0142")).toBe(maskPhone("+27825550142"));
    expect(maskPhone("+27-82-555-0142")).toBe(maskPhone("+27825550142"));
  });

  it("refuses to half-mask a number too short to hide anything", () => {
    expect(maskPhone("5550142")).toBe("***");
    expect(maskPhone("")).toBe("***");
  });
});
