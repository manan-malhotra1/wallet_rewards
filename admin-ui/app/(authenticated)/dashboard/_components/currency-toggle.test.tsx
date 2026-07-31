import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CurrencyToggle } from "./currency-toggle";
import type { CurrencyInfo } from "@/lib/api-types";

const CURRENCIES: CurrencyInfo[] = [
  { code: "ZAR", symbol: "R", display_name: "Rand" },
  { code: "MGA", symbol: "Ar", display_name: "Ariary" },
];

describe("CurrencyToggle", () => {
  it("Verify deselecting a currency reports the remaining selection to the parent", () => {
    const onChange = vi.fn();
    render(<CurrencyToggle currencies={CURRENCIES} selected={["ZAR", "MGA"]} onChange={onChange} />);
    screen.getByRole("button", { name: "MGA" }).click();
    expect(onChange).toHaveBeenCalledWith(["ZAR"]);
  });

  it("Verify the last remaining currency cannot be deselected", () => {
    const onChange = vi.fn();
    render(<CurrencyToggle currencies={CURRENCIES} selected={["ZAR"]} onChange={onChange} />);
    screen.getByRole("button", { name: "ZAR" }).click();
    expect(onChange).not.toHaveBeenCalled();
  });
});
