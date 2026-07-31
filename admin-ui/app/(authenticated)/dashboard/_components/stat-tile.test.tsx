import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StatTile } from "./stat-tile";

describe("StatTile", () => {
  it("renders label, value, and an up delta chip", () => {
    render(
      <StatTile
        id="txns"
        label="Transactions"
        value="1,204"
        current="120"
        previous="100"
        selected={false}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText("Transactions")).toBeInTheDocument();
    expect(screen.getByText("1,204")).toBeInTheDocument();
    expect(screen.getByText("+20.0%")).toBeInTheDocument();
  });

  it("calls onSelect with its id when clicked", async () => {
    const onSelect = vi.fn();
    render(
      <StatTile
        id="volume"
        label="Volume"
        value="R 5,000"
        current="100"
        previous="100"
        selected={false}
        onSelect={onSelect}
      />,
    );
    screen.getByRole("button").click();
    expect(onSelect).toHaveBeenCalledWith("volume");
  });
});
