import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MoneyStatTile } from "./money-stat-tile";
import type { CurrencyInfo, CurrencyScalar } from "@/lib/api-types";

const DATA: CurrencyScalar[] = [
  { currency: "ZAR", current: "100", previous: "80" },
  { currency: "MGA", current: "50", previous: "50" },
];

const META: Record<string, CurrencyInfo> = {
  ZAR: { code: "ZAR", symbol: "R", display_name: "Rand" },
  MGA: { code: "MGA", symbol: "Ar", display_name: "Ariary" },
};

describe("MoneyStatTile", () => {
  it("Verify each selected currency renders its own line and delta, never summed", () => {
    render(
      <MoneyStatTile
        id="volume"
        label="Volume"
        data={DATA}
        selectedCurrencies={["ZAR", "MGA"]}
        currencyMeta={META}
        selected={false}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
    expect(screen.queryByText("150")).not.toBeInTheDocument();
    expect(screen.getByText("+25.0%")).toBeInTheDocument();
  });

  it("Verify clicking the tile selects its metric for the trend chart", () => {
    const onSelect = vi.fn();
    render(
      <MoneyStatTile
        id="volume"
        label="Volume"
        data={DATA}
        selectedCurrencies={["ZAR", "MGA"]}
        currencyMeta={META}
        selected={false}
        onSelect={onSelect}
      />,
    );
    screen.getByRole("button").click();
    expect(onSelect).toHaveBeenCalledWith("volume");
  });
});
