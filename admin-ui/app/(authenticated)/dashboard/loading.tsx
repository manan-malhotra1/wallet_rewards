/**
 * Route-level loading UI for the dashboard.
 *
 * `page.tsx` is `force-dynamic` and awaits twelve analytics fetches, so without
 * this Next.js would hold the previous route on screen with no feedback. Renders
 * the same panel geometry the real page settles into.
 */
import { DashboardSkeleton } from "./_components/dashboard-skeleton";

export default function Loading() {
  return (
    <div className="h-full overflow-y-auto px-6 pb-14">
      <DashboardSkeleton />
    </div>
  );
}
