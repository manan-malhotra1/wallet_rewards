/**
 * Tests for the "Not yet usable" notice.
 *
 * The selection rules are unit-tested in `lib/service-catalog.test.ts`; these
 * cover what the operator actually sees, including the deliberate absence of a
 * link for the one prerequisite with no admin screen behind it.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReadinessNotice } from "@/app/(authenticated)/services/_components/readiness-notice";

describe("ReadinessNotice", () => {
  it("Verify a usable service shows no notice at all", () => {
    const { container } = render(
      <ReadinessNotice readiness={{ pricing: true, limits: true, role: true }} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("Verify the missing pieces are named, and the fixable ones link out", () => {
    render(
      <ReadinessNotice readiness={{ pricing: false, limits: true, role: false }} />,
    );

    expect(screen.getByText("Not yet usable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "pricing" })).toHaveAttribute(
      "href",
      "/pricing",
    );
    // Limits is satisfied, so it is not listed.
    expect(screen.queryByRole("link", { name: "limits" })).not.toBeInTheDocument();
    // The role grant has no admin screen yet, so it is named but not linked.
    expect(screen.getByText("role grant")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "role grant" })).not.toBeInTheDocument();
  });
});
