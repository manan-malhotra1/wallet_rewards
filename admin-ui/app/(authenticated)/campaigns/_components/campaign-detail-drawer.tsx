/**
 * <CampaignDetailDrawer> — view-only side drawer that renders every
 * field on a campaign plus its live performance + budget scope.
 */
"use client";

import * as React from "react";

import {
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { StatusPill } from "@/components/ui/status-pill";
import type { Rule, RulePerformance, Segment, SegmentGroup } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/utils";

import {
  describeBudgetScope,
  describeTrigger,
} from "../_lib/describe-campaign";

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-3 border-b py-2 last:border-b-0">
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </dt>
      <dd className="col-span-2 text-sm text-foreground">{value ?? "—"}</dd>
    </div>
  );
}

export function CampaignDetailDrawer({
  rule,
  performance,
  segments,
  segmentGroups,
  open,
  onOpenChange,
}: {
  rule: Rule;
  performance: RulePerformance | null;
  segments: Segment[];
  segmentGroups: SegmentGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // WAL-79 — resolve the segment binding to "Group → Segment" for display.
  // A binding whose segment was deleted out from under the rule still shows
  // the raw id rather than lying with "All users".
  const targetSegment = rule.segment_id
    ? segments.find((s) => s.id === rule.segment_id)
    : undefined;
  const targetGroup = targetSegment
    ? segmentGroups.find((g) => g.id === targetSegment.group_id)
    : undefined;
  const audience = !rule.segment_id
    ? "All users"
    : targetSegment
      ? `${targetGroup?.name ?? "Unknown group"} → ${targetSegment.name}`
      : `Unknown segment (${rule.segment_id})`;

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent>
        <DrawerHeader>
          <div className="flex items-center justify-between gap-2 pr-8">
            <DrawerTitle>{rule.name}</DrawerTitle>
            <StatusPill status={rule.status.toUpperCase()} variant="dense" />
          </div>
          <DrawerDescription>{describeTrigger(rule)}</DrawerDescription>
        </DrawerHeader>
        <DrawerBody>
          <section>
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Configuration
            </h3>
            <dl>
              <Row label="Type" value={<Badge tone="brand">{rule.rule_type}</Badge>} />
              <Row label="Transaction" value={rule.transaction_type} />
              <Row label="Audience" value={audience} />
              <Row
                label="Reward"
                value={
                  <span className="font-mono">
                    {rule.reward_value} {rule.reward_type}
                  </span>
                }
              />
              {rule.count_threshold !== null && (
                <Row label="Count threshold" value={rule.count_threshold} />
              )}
              {rule.min_amount && <Row label="Min amount" value={rule.min_amount} />}
              {rule.streak_units && (
                <Row
                  label="Streak"
                  value={`${rule.streak_units} ${rule.streak_unit_window}s`}
                />
              )}
              {rule.campaign_start_date && (
                <Row
                  label="Active window"
                  value={`${rule.campaign_start_date} → ${rule.campaign_end_date}`}
                />
              )}
              {rule.stop_after_n_triggers && (
                <Row
                  label="Cap per user"
                  value={`${rule.stop_after_n_triggers} fires`}
                />
              )}
              {(rule.rule_type === "milestone" ||
                rule.rule_type === "streak") && (
                <Row
                  label="Resets after fire"
                  value={rule.resets_after_trigger ? "Yes" : "No"}
                />
              )}
            </dl>
          </section>

          <section className="mt-6">
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Budget
            </h3>
            <p className="text-sm text-foreground">
              {performance
                ? describeBudgetScope(performance.budget_scope)
                : "—"}
            </p>
          </section>

          {performance && (
            <section className="mt-6">
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Performance
              </h3>
              <dl>
                <Row
                  label="Total fires"
                  value={
                    <span className="font-mono tabular-nums">
                      {performance.total_fires.toLocaleString()}
                    </span>
                  }
                />
                <Row
                  label="Unique users"
                  value={
                    <span className="font-mono tabular-nums">
                      {performance.unique_users_rewarded.toLocaleString()}
                    </span>
                  }
                />
                <Row
                  label="Total reward issued"
                  value={
                    <span className="font-mono">
                      {performance.total_reward_value} {rule.reward_type}
                    </span>
                  }
                />
                <Row
                  label="First fired"
                  value={
                    performance.first_fired_at
                      ? formatTimestamp(performance.first_fired_at)
                      : "never"
                  }
                />
                <Row
                  label="Last fired"
                  value={
                    performance.last_fired_at
                      ? formatTimestamp(performance.last_fired_at)
                      : "never"
                  }
                />
              </dl>
            </section>
          )}
        </DrawerBody>
      </DrawerContent>
    </Drawer>
  );
}
