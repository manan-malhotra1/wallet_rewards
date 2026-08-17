"use client";

/**
 * A segmented control whose active pill slides between options.
 *
 * The options share an equal-width grid track, which is what lets the pill be
 * positioned as `translateX(index * 100%)` of its own width — no per-option
 * width table to keep in sync with the labels, and no DOM measurement, so the
 * pill is already in the right place on first paint.
 *
 * Only `transform` and `width` animate (both compositor-friendly); colour
 * crossfades. The reduced-motion rule in globals.css collapses all three, so
 * the pill jumps straight to the selected option.
 */
import { cn } from "@/lib/utils";

interface Props<T extends string> {
  options: readonly T[];
  value: T;
  onChange: (value: T) => void;
  /** Accessible name for the group, e.g. "Time range". */
  label: string;
}

export function SegmentedControl<T extends string>({ options, value, onChange, label }: Props<T>) {
  const index = Math.max(0, options.indexOf(value));
  const share = 100 / options.length;

  return (
    <div
      role="group"
      aria-label={label}
      className="relative grid"
      style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}
    >
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-0 rounded-lg border bg-segment-pill shadow-[inset_0_1px_0_var(--hairline-top)] transition-transform duration-150 ease-[cubic-bezier(0.32,0.72,0,1)]"
        style={{ width: `${share}%`, transform: `translateX(${index * 100}%)` }}
      />
      {options.map((option) => {
        const active = option === value;
        return (
          <button
            key={option}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option)}
            className={cn(
              "relative z-[1] h-[26px] rounded-lg px-3 text-xs whitespace-nowrap capitalize transition-colors duration-150",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
              active ? "font-semibold text-foreground" : "font-medium text-muted-foreground hover:text-foreground",
            )}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}
