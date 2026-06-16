/**
 * <KbdHint> — renders a keyboard shortcut chip like `⌘K` or `Esc`.
 * Used in the command palette and inline next to actions.
 */
import { cn } from "@/lib/utils";

export interface KbdHintProps {
  children: React.ReactNode;
  className?: string;
}

export function KbdHint({ children, className }: KbdHintProps) {
  return (
    <kbd
      className={cn(
        "inline-flex h-5 min-w-[20px] items-center justify-center rounded border border-[--color-border] bg-[--color-surface-2] px-1.5 text-[11px] font-mono font-medium text-[--color-text-2]",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
