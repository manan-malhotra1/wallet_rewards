/**
 * <CriteriaBuilder> — controlled editor for a dynamic segment's criteria
 * document (DSL v1): an AND/OR combinator over 1-10 flat metric conditions.
 *
 * Each condition's available filters (txn_type, window_days) are driven by
 * the metric vocabulary in `metrics` (`GET /segments/metrics`); switching a
 * condition to a metric that doesn't support a filter clears it, so the
 * payload never carries a stale filter the backend would reject. The footer
 * mirrors `validateCriteria`'s errors, or `summarizeCriteria`'s human
 * summary once the document is valid.
 */
"use client";

import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  CriteriaCondition,
  SegmentCriteriaDoc,
  SegmentMetricInfo,
  Service,
} from "@/lib/api-types";
import { summarizeCriteria, validateCriteria } from "@/lib/segment-criteria";

// Radix Select items can't carry an empty-string value; sentinel for "no
// txn_type filter" (the condition's txn_type stays undefined on the wire).
const ANY_TXN_TYPE = "__any__";

/** Look up a metric's vocabulary entry, defaulting to "supports nothing" if it's somehow not in the list. */
function findMetric(metrics: SegmentMetricInfo[], name: string): SegmentMetricInfo {
  return (
    metrics.find((m) => m.name === name) ?? {
      name,
      supports_txn_type: false,
      supports_window: false,
    }
  );
}

/** Parse a numeric input's raw text into a threshold — an empty string clears the field (undefined), never coerces to 0. */
function parseThreshold(raw: string): number | undefined {
  if (raw.trim() === "") return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

interface ConditionRowProps {
  index: number;
  condition: CriteriaCondition;
  metrics: SegmentMetricInfo[];
  services: Service[];
  onUpdate: (patch: Partial<CriteriaCondition>) => void;
  onRemove: () => void;
}

/** One condition's fields: metric, its conditional filters, the three comparators, and a remove button. */
function ConditionRow({ index, condition, metrics, services, onUpdate, onRemove }: ConditionRowProps) {
  const info = findMetric(metrics, condition.metric);

  const setMetric = (metric: string) => {
    const info2 = findMetric(metrics, metric);
    // Switching metric clears filters the new one doesn't support — never
    // carry a stale txn_type/window_days into a metric that would 422 on it.
    onUpdate({
      metric,
      txn_type: info2.supports_txn_type ? condition.txn_type : undefined,
      window_days: info2.supports_window ? condition.window_days : undefined,
    });
  };

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-md border p-2">
      <div className="w-40">
        <Label htmlFor={`cond-metric-${index}`}>Metric</Label>
        <div className="mt-1">
          <Select value={condition.metric} onValueChange={setMetric}>
            <SelectTrigger id={`cond-metric-${index}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {metrics.map((m) => (
                <SelectItem key={m.name} value={m.name}>
                  {m.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {info.supports_txn_type && (
        <div className="w-36">
          <Label htmlFor={`cond-txntype-${index}`}>Txn type</Label>
          <div className="mt-1">
            <Select
              value={condition.txn_type ?? ANY_TXN_TYPE}
              onValueChange={(v) => onUpdate({ txn_type: v === ANY_TXN_TYPE ? undefined : v })}
            >
              <SelectTrigger id={`cond-txntype-${index}`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY_TXN_TYPE}>Any</SelectItem>
                {services.map((s) => (
                  <SelectItem key={s.code} value={s.code}>
                    {s.display_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}

      {info.supports_window && (
        <div className="w-28">
          <Label htmlFor={`cond-window-${index}`}>Window (days)</Label>
          <Input
            id={`cond-window-${index}`}
            type="number"
            min="1"
            max="365"
            value={condition.window_days ?? ""}
            onChange={(e) => onUpdate({ window_days: parseThreshold(e.target.value) })}
            className="mt-1 font-mono tabular-nums"
          />
        </div>
      )}

      <div className="w-24">
        <Label htmlFor={`cond-gte-${index}`}>≥</Label>
        <Input
          id={`cond-gte-${index}`}
          type="number"
          value={condition.gte ?? ""}
          onChange={(e) => onUpdate({ gte: parseThreshold(e.target.value) })}
          className="mt-1 font-mono tabular-nums"
        />
      </div>
      <div className="w-24">
        <Label htmlFor={`cond-lte-${index}`}>≤</Label>
        <Input
          id={`cond-lte-${index}`}
          type="number"
          value={condition.lte ?? ""}
          onChange={(e) => onUpdate({ lte: parseThreshold(e.target.value) })}
          className="mt-1 font-mono tabular-nums"
        />
      </div>
      <div className="w-24">
        <Label htmlFor={`cond-eq-${index}`}>=</Label>
        <Input
          id={`cond-eq-${index}`}
          type="number"
          value={condition.eq ?? ""}
          onChange={(e) => onUpdate({ eq: parseThreshold(e.target.value) })}
          className="mt-1 font-mono tabular-nums"
        />
      </div>

      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        aria-label="Remove condition"
        onClick={onRemove}
      >
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

interface CriteriaBuilderProps {
  value: SegmentCriteriaDoc;
  metrics: SegmentMetricInfo[];
  services: Service[];
  onChange: (value: SegmentCriteriaDoc) => void;
}

export function CriteriaBuilder({ value, metrics, services, onChange }: CriteriaBuilderProps) {
  const errors = validateCriteria(value);
  const summary = errors.length === 0 ? summarizeCriteria(value) : null;

  const updateCondition = (index: number, patch: Partial<CriteriaCondition>) => {
    const conditions = value.conditions.map((c, i) => (i === index ? { ...c, ...patch } : c));
    onChange({ ...value, conditions });
  };

  const addCondition = () => {
    onChange({
      ...value,
      conditions: [...value.conditions, { metric: metrics[0]?.name ?? "" }],
    });
  };

  const removeCondition = (index: number) => {
    onChange({ ...value, conditions: value.conditions.filter((_, i) => i !== index) });
  };

  return (
    <div className="space-y-3">
      <div className="w-28">
        <Label htmlFor="criteria-op">Combine with</Label>
        <div className="mt-1">
          <Select
            value={value.op}
            onValueChange={(v) => onChange({ ...value, op: v as SegmentCriteriaDoc["op"] })}
          >
            <SelectTrigger id="criteria-op">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="AND">AND</SelectItem>
              <SelectItem value="OR">OR</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="space-y-2">
        {value.conditions.map((condition, index) => (
          <ConditionRow
            key={index}
            index={index}
            condition={condition}
            metrics={metrics}
            services={services}
            onUpdate={(patch) => updateCondition(index, patch)}
            onRemove={() => removeCondition(index)}
          />
        ))}
      </div>

      <Button type="button" variant="outline" size="sm" onClick={addCondition}>
        Add condition
      </Button>

      <div className="rounded-md border bg-muted/30 p-3 text-xs">
        {errors.length > 0 ? (
          <ul className="space-y-1 text-destructive">
            {errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        ) : (
          <span className="text-muted-foreground">{summary}</span>
        )}
      </div>
    </div>
  );
}
