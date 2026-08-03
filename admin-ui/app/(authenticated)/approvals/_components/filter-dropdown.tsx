/**
 * Small popover dropdowns for the Approvals toolbar — a multi-select (OR) facet
 * and a single-select preset facet. Built directly on `@radix-ui/react-popover`
 * (already a dependency) since the repo ships no shared Popover wrapper, and the
 * commit scope for this feature is the approvals route + the filter helper only.
 */
"use client";

import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Check, ChevronDown } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** A selectable option: a stable `value` plus its human `label`. */
export interface FilterOption {
  value: string;
  label: string;
}

/** Shared popover content shell — themed panel, portalled, keyboard-dismissable. */
function DropdownPanel({ children }: { children: React.ReactNode }) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align="start"
        sideOffset={6}
        className={cn(
          "z-50 min-w-[12rem] max-h-[20rem] overflow-y-auto rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md",
          "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
        )}
      >
        {children}
      </PopoverPrimitive.Content>
    </PopoverPrimitive.Portal>
  );
}

/** A single clickable option row with a leading check when selected. */
function OptionRow({
  selected,
  label,
  onSelect,
}: {
  selected: boolean;
  label: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={selected}
      onClick={onSelect}
      className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm outline-none hover:bg-accent hover:text-accent-foreground focus-visible:bg-accent"
    >
      <span className="flex size-4 shrink-0 items-center justify-center">
        {selected && <Check className="size-4" aria-hidden="true" />}
      </span>
      <span className="truncate">{label}</span>
    </button>
  );
}

/**
 * Multi-select facet. Clicking an option toggles it in/out of `selected`
 * (OR semantics upstream). The trigger label summarises the current choice.
 */
export function MultiSelectDropdown({
  label,
  options,
  selected,
  onChange,
}: {
  /** Facet name shown when nothing is chosen (e.g. "Type"). */
  label: string;
  options: FilterOption[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const toggle = (value: string) => {
    onChange(
      selected.includes(value)
        ? selected.filter((v) => v !== value)
        : [...selected, value],
    );
  };

  // Trigger text: the single chosen label, "N selected", or the bare facet name.
  const triggerText =
    selected.length === 0
      ? label
      : selected.length === 1
        ? (options.find((o) => o.value === selected[0])?.label ?? label)
        : `${selected.length} selected`;

  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger asChild>
        <Button variant="outline" size="md" className="gap-2">
          <span className={cn(selected.length === 0 && "text-muted-foreground")}>
            {triggerText}
          </span>
          <ChevronDown className="size-4 opacity-60" aria-hidden="true" />
        </Button>
      </PopoverPrimitive.Trigger>
      <DropdownPanel>
        {options.map((opt) => (
          <OptionRow
            key={opt.value}
            selected={selected.includes(opt.value)}
            label={opt.label}
            onSelect={() => toggle(opt.value)}
          />
        ))}
      </DropdownPanel>
    </PopoverPrimitive.Root>
  );
}

/**
 * Single-select preset facet (e.g. the date range). Choosing an option closes
 * the popover. The trigger always shows the active option's label.
 */
export function SingleSelectDropdown({
  options,
  value,
  onChange,
}: {
  options: FilterOption[];
  value: string;
  onChange: (next: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const activeLabel = options.find((o) => o.value === value)?.label ?? value;

  const choose = (next: string) => {
    onChange(next);
    setOpen(false);
  };

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <PopoverPrimitive.Trigger asChild>
        <Button variant="outline" size="md" className="gap-2">
          <span>{activeLabel}</span>
          <ChevronDown className="size-4 opacity-60" aria-hidden="true" />
        </Button>
      </PopoverPrimitive.Trigger>
      <DropdownPanel>
        {options.map((opt) => (
          <OptionRow
            key={opt.value}
            selected={opt.value === value}
            label={opt.label}
            onSelect={() => choose(opt.value)}
          />
        ))}
      </DropdownPanel>
    </PopoverPrimitive.Root>
  );
}
