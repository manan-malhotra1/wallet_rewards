/**
 * First-paint placeholder for the dashboard, rendered by `loading.tsx` while
 * the server component's analytics fetch is in flight.
 *
 * Shaped like the real page — four KPI tiles then progressively shorter panels —
 * so the layout doesn't jump when the data lands. Note this is only the *first*
 * load: changing the range dims the existing content in place instead of
 * throwing it away for a skeleton, because the previous figures are still a
 * useful reference while the new ones arrive.
 */
import { Panel, TilePanel } from "./panel";

/** A shimmering placeholder bar. The sweep is defined in globals.css. */
function Bar({ className, style }: { className: string; style?: React.CSSProperties }) {
  return <div className={`skeleton-sweep rounded-md ${className}`} style={style} />;
}

export function DashboardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading dashboard" className="pt-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <TilePanel key={i} className="h-[168px] overflow-hidden">
            <Bar className="h-2.5 w-[72px]" />
            <Bar className="mt-3 h-6 w-[58%] rounded-lg" />
            <Bar className="mt-4 h-[38px] w-full rounded-lg" />
          </TilePanel>
        ))}
      </div>

      <div className="mt-3.5 flex flex-col gap-3.5">
        {[340, 260, 260].map((height, i) => (
          <Panel key={i} style={{ height }}>
            <Bar className="h-3 w-[140px]" />
            <Bar className="mt-3.5 w-full rounded-[14px]" style={{ height: height - 74 }} />
          </Panel>
        ))}
      </div>
    </div>
  );
}
