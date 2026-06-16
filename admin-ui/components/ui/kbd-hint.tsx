/**
 * <KbdHint> — keyboard shortcut chip (⌘K / Esc / etc).
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
        "inline-flex h-5 min-w-[20px] items-center justify-center rounded border bg-muted px-1.5 text-[10px] font-mono font-medium text-muted-foreground",
        className,
      )}
    >
      {children}
    </kbd>
  );
}
