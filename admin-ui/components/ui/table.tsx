/**
 * Bare HTML <table> primitives styled to our density tokens. The DataTable
 * client component (TanStack Table) renders into these.
 */
import * as React from "react";

import { cn } from "@/lib/utils";

export const Table = React.forwardRef<HTMLTableElement, React.HTMLAttributes<HTMLTableElement>>(
  ({ className, ...props }, ref) => (
    <div className="w-full overflow-x-auto">
      <table
        ref={ref}
        className={cn("w-full caption-bottom border-collapse text-[13px]", className)}
        {...props}
      />
    </div>
  ),
);
Table.displayName = "Table";

export const TableHead = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <thead
      ref={ref}
      className={cn(
        "border-b border-[--color-border] bg-[--color-surface-1] text-[12px] text-[--color-text-2]",
        className,
      )}
      {...props}
    />
  ),
);
TableHead.displayName = "TableHead";

export const TableBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <tbody
      ref={ref}
      className={cn("divide-y divide-[--color-border]", className)}
      {...props}
    />
  ),
);
TableBody.displayName = "TableBody";

export const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr
      ref={ref}
      className={cn(
        "transition-colors hover:bg-[--color-surface-2] data-[selected=true]:bg-[--color-surface-3]",
        className,
      )}
      {...props}
    />
  ),
);
TableRow.displayName = "TableRow";

export const TableHeaderCell = React.forwardRef<HTMLTableCellElement, React.ThHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <th
      ref={ref}
      className={cn(
        "h-9 px-3 text-left font-medium uppercase tracking-wide text-[11px]",
        className,
      )}
      {...props}
    />
  ),
);
TableHeaderCell.displayName = "TableHeaderCell";

export const TableCell = React.forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement>>(
  ({ className, ...props }, ref) => (
    <td
      ref={ref}
      className={cn("h-9 px-3 align-middle text-[--color-text-1]", className)}
      {...props}
    />
  ),
);
TableCell.displayName = "TableCell";

export const TableEmpty = ({ message, colSpan }: { message: string; colSpan: number }) => (
  <tr>
    <td
      colSpan={colSpan}
      className="px-3 py-6 text-center text-[--color-text-3]"
    >
      {message}
    </td>
  </tr>
);
