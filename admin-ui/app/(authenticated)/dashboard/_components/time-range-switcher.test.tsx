import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TimeRangeSwitcher } from "./time-range-switcher";

describe("TimeRangeSwitcher", () => {
  it("fires onRangeChange with the chosen range", () => {
    const onRangeChange = vi.fn();
    render(
      <TimeRangeSwitcher
        range="7d"
        granularity="day"
        onRangeChange={onRangeChange}
        onGranularityChange={() => {}}
      />,
    );
    screen.getByRole("button", { name: "30d" }).click();
    expect(onRangeChange).toHaveBeenCalledWith("30d");
  });
});
