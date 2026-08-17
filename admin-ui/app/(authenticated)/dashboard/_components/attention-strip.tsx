/**
 * Operations "needs attention" section — pending reconciliation and manual
 * review counts for the active tenant, each linking to its queue.
 *
 * Server component: it fetches its own two counts rather than riding along with
 * the client shell's refetch, because these are queue depths that don't depend
 * on the selected range or currencies. Retains the ops-cockpit value of the
 * pre-redesign dashboard, now as a labelled section rather than a loose strip.
 */
import Link from "next/link";

import { listManualReview, listPendingRedemptions } from "@/lib/api-endpoints";
import { TilePanel, SectionHeading } from "./panel";

/** One queue: its copy, its count and the tone of its icon chip. */
interface AttentionItem {
  label: string;
  hint: string;
  count: number;
  /** A `--warn`/`--neg` token — severity, paired with a distinct glyph. */
  color: string;
  icon: string;
}

export async function AttentionStrip({ tenantId }: { tenantId: string }) {
  const [pending, manual] = await Promise.all([
    listPendingRedemptions(tenantId, 5).catch(() => []),
    listManualReview(tenantId).catch(() => []),
  ]);
  if (pending.length === 0 && manual.length === 0) return null;

  const items: AttentionItem[] = [
    {
      label: "Pending reconciliation",
      hint: "Open items across all currencies",
      count: pending.length,
      color: "var(--warn)",
      icon: "M3 12a9 9 0 1015.6-6.2M21 3v6h-6",
    },
    {
      label: "Manual review",
      hint: "Flagged for operator action",
      count: manual.length,
      color: "var(--neg)",
      icon: "M12 9v4M12 17h.01M10.3 3.9L2.6 17a2 2 0 001.7 3h15.4a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z",
    },
  ];

  return (
    <section className="mb-10">
      <SectionHeading title="Attention" />
      <div className="grid gap-3 sm:grid-cols-2">
        {items.map((item) => (
          <Link key={item.label} href="/reconciliation" className="block">
            <TilePanel className="flex items-center gap-3.5 px-4 py-4 transition-[border-color,transform] duration-[120ms] hover:-translate-y-px hover:border-primary-line">
              <span
                className="flex size-[30px] shrink-0 items-center justify-center rounded-[9px]"
                style={{
                  color: item.color,
                  background: `color-mix(in oklab, ${item.color} 15%, transparent)`,
                }}
              >
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.9"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d={item.icon} />
                </svg>
              </span>
              <span className="mr-auto flex flex-col gap-0.5">
                <span className="text-[12.5px] font-medium text-foreground">{item.label}</span>
                <span className="text-[11px] text-muted-foreground">{item.hint}</span>
              </span>
              <span className="text-[21px] font-semibold tracking-[-0.02em] text-foreground tabular-nums">
                {item.count}
              </span>
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.9"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-muted-foreground"
                aria-hidden="true"
              >
                <path d="M9 6l6 6-6 6" />
              </svg>
            </TilePanel>
          </Link>
        ))}
      </div>
    </section>
  );
}
