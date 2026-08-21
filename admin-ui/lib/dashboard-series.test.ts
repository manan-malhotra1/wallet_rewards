import { describe, expect, it } from "vitest";

import {
  buildTrendData,
  netFlowFor,
  treasuryFlowFor,
  registrationValues,
  revenueByCurrency,
  rewardsFlow,
  sparkValues,
  statusTotals,
} from "./dashboard-series";
import type {
  MetricsTimeseries,
  NetFlowPoint,
  RevenueServiceSlice,
  StatusBucket,
} from "./api-types";

const TIMESERIES: MetricsTimeseries = {
  count: {
    current: [
      { bucket: "2026-08-01", count: 10 },
      { bucket: "2026-08-02", count: 20 },
    ],
    previous: [
      { bucket: "2026-07-01", count: 8 },
      { bucket: "2026-07-02", count: 9 },
    ],
  },
  volume: [
    {
      currency: "ZAR",
      current: [
        { bucket: "2026-08-01", value: "100.50" },
        { bucket: "2026-08-02", value: "200" },
      ],
      previous: [
        { bucket: "2026-07-01", value: "90" },
        { bucket: "2026-07-02", value: "95" },
      ],
    },
    {
      currency: "USD",
      current: [
        { bucket: "2026-08-01", value: "5" },
        { bucket: "2026-08-02", value: "6" },
      ],
      previous: [
        { bucket: "2026-07-01", value: "4" },
        { bucket: "2026-07-02", value: "4" },
      ],
    },
  ],
  revenue: [],
};

describe("buildTrendData", () => {
  it("Verify a null payload yields an empty chart rather than throwing", () => {
    expect(buildTrendData(null, "count", ["ZAR"])).toEqual({
      labels: [],
      series: [],
      previous: null,
    });
  });

  it("Verify the count metric plots one currency-agnostic series with its previous period", () => {
    const trend = buildTrendData(TIMESERIES, "count", ["ZAR"]);
    expect(trend.series).toHaveLength(1);
    expect(trend.series[0].values).toEqual([10, 20]);
    expect(trend.previous).toEqual([8, 9]);
    expect(trend.labels).toEqual(["2026-08-01", "2026-08-02"]);
  });

  it("Verify money metrics render one series per selected currency, never summed", () => {
    const trend = buildTrendData(TIMESERIES, "volume", ["ZAR", "USD"]);
    expect(trend.series.map((s) => s.key)).toEqual(["ZAR", "USD"]);
    expect(trend.series[0].values).toEqual([100.5, 200]);
    expect(trend.series[1].values).toEqual([5, 6]);
  });

  it("Verify series order follows the selection, not the payload order", () => {
    const trend = buildTrendData(TIMESERIES, "volume", ["USD", "ZAR"]);
    expect(trend.series.map((s) => s.key)).toEqual(["USD", "ZAR"]);
  });

  it("Verify the previous-period overlay is dropped once two currencies are charted", () => {
    // One dotted line can't say which currency it belongs to, so it is omitted
    // rather than shown against an arbitrary series.
    expect(buildTrendData(TIMESERIES, "volume", ["ZAR", "USD"]).previous).toBeNull();
    expect(buildTrendData(TIMESERIES, "volume", ["ZAR"]).previous).toEqual([90, 95]);
  });

  it("Verify a currency with no data in the payload is skipped", () => {
    expect(buildTrendData(TIMESERIES, "volume", ["MGA"]).series).toEqual([]);
  });

  it("Verify currency symbols are attached for tooltip formatting", () => {
    const trend = buildTrendData(TIMESERIES, "volume", ["ZAR"], { ZAR: "R" });
    expect(trend.series[0].symbol).toBe("R");
  });

  it("Verify an unparseable amount is treated as zero rather than NaN", () => {
    const broken: MetricsTimeseries = {
      ...TIMESERIES,
      volume: [{ currency: "ZAR", current: [{ bucket: "b", value: "oops" }], previous: [] }],
    };
    expect(buildTrendData(broken, "volume", ["ZAR"]).series[0].values).toEqual([0]);
  });
});

describe("sparkValues", () => {
  it("Verify a money tile sparks on the first selected currency only", () => {
    expect(sparkValues(TIMESERIES, "volume", ["USD", "ZAR"])).toEqual([5, 6]);
  });

  it("Verify a missing payload yields no sparkline instead of an error", () => {
    expect(sparkValues(null, "count", [])).toEqual([]);
  });
});

describe("registrationValues", () => {
  it("Verify a null payload yields an empty series", () => {
    expect(registrationValues(null)).toEqual([]);
  });

  it("Verify current-period counts are returned oldest bucket first", () => {
    expect(
      registrationValues({
        current: [
          { bucket: "a", count: 3 },
          { bucket: "b", count: 4 },
        ],
        previous: [],
      }),
    ).toEqual([3, 4]);
  });
});

describe("statusTotals", () => {
  const BUCKETS: StatusBucket[] = [
    { bucket: "a", completed: 10, failed: 1, pending: 2 },
    { bucket: "b", completed: 20, failed: 0, pending: 3 },
  ];

  it("Verify per-bucket statuses roll up into range totals", () => {
    expect(statusTotals(BUCKETS)).toEqual({
      completed: 30,
      failed: 1,
      pending: 5,
      total: 36,
    });
  });

  it("Verify a null payload totals zero so the panel can report empty", () => {
    expect(statusTotals(null).total).toBe(0);
  });
});

describe("revenueByCurrency", () => {
  const SLICES: RevenueServiceSlice[] = [
    { service_type: "cash_in", currency: "ZAR", fee: "1", tax: "0", commission: "0", total: "40" },
    { service_type: "airtime", currency: "ZAR", fee: "1", tax: "0", commission: "0", total: "60" },
    { service_type: "cash_in", currency: "USD", fee: "1", tax: "0", commission: "0", total: "7" },
  ];

  it("Verify each currency is subtotalled separately, never across currencies", () => {
    const groups = revenueByCurrency(SLICES, ["ZAR", "USD"]);
    expect(groups.map((g) => [g.currency, g.total])).toEqual([
      ["ZAR", 100],
      ["USD", 7],
    ]);
  });

  it("Verify services are ranked by contribution within a currency", () => {
    expect(revenueByCurrency(SLICES, ["ZAR"])[0].rows.map((r) => r.serviceType)).toEqual([
      "airtime",
      "cash_in",
    ]);
  });

  it("Verify a currency with no revenue produces no empty block", () => {
    expect(revenueByCurrency(SLICES, ["MGA"])).toEqual([]);
  });
});

describe("netFlowFor", () => {
  const POINTS: NetFlowPoint[] = [
    {
      bucket: "a",
      currency: "ZAR",
      inflow: "10",
      outflow: "4",
      treasury_inflow: "500",
      treasury_outflow: "700",
    },
    {
      bucket: "a",
      currency: "USD",
      inflow: "1",
      outflow: "2",
      treasury_inflow: "0",
      treasury_outflow: "0",
    },
  ];

  it("Verify only the requested currency's movement is returned", () => {
    expect(netFlowFor(POINTS, "ZAR")).toEqual([{ bucket: "a", inflow: 10, outflow: 4 }]);
  });

  it("Verify a null payload yields no points", () => {
    expect(netFlowFor(null, "ZAR")).toEqual([]);
  });

  it("Verify treasury movement is excluded from the wallet series", () => {
    // The two series must never be conflated: an operator top-up is not customer
    // inflow, so the wallet mapper reads only the wallet fields.
    expect(netFlowFor(POINTS, "ZAR")).toEqual([{ bucket: "a", inflow: 10, outflow: 4 }]);
  });
});

describe("treasuryFlowFor", () => {
  const POINTS: NetFlowPoint[] = [
    {
      bucket: "a",
      currency: "ZAR",
      inflow: "10",
      outflow: "4",
      treasury_inflow: "500",
      treasury_outflow: "700",
    },
    {
      bucket: "a",
      currency: "USD",
      inflow: "1",
      outflow: "2",
      treasury_inflow: "9",
      treasury_outflow: "8",
    },
  ];

  it("Verify operator movement is read from the treasury fields only", () => {
    expect(treasuryFlowFor(POINTS, "ZAR")).toEqual([
      { bucket: "a", inflow: 500, outflow: 700 },
    ]);
  });

  it("Verify a float withdrawal surfaces as outflow", () => {
    // The regression this series exists for: an operator withdrawal touches no
    // user wallet, so it was previously invisible on the dashboard.
    expect(
      treasuryFlowFor(
        [
          {
            bucket: "a",
            currency: "ZAR",
            inflow: "0",
            outflow: "0",
            treasury_inflow: "0",
            treasury_outflow: "1000000",
          },
        ],
        "ZAR",
      ),
    ).toEqual([{ bucket: "a", inflow: 0, outflow: 1000000 }]);
  });

  it("Verify a null payload yields no points", () => {
    expect(treasuryFlowFor(null, "ZAR")).toEqual([]);
  });
});

describe("rewardsFlow", () => {
  it("Verify issued and redeemed points are parsed per bucket", () => {
    expect(
      rewardsFlow({
        points: [{ bucket: "a", issued: "100", redeemed: "40" }],
        outstanding_liability: "60",
      }),
    ).toEqual([{ bucket: "a", issued: 100, redeemed: 40 }]);
  });

  it("Verify a null payload yields no points", () => {
    expect(rewardsFlow(null)).toEqual([]);
  });
});
