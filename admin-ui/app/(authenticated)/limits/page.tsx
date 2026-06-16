/**
 * Limits page — per-tenant transaction min/max/daily-count/daily-value
 * caps (Pay-PRD-0380). The backend module exists as a scaffold but doesn't
 * expose endpoints yet — that lands with Phase G (Money Controls).
 *
 * For now we render an explanatory empty state so the navigation entry
 * isn't a dead link.
 */
import { ListChecks } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

export default function LimitsPage() {
  return (
    <div>
      <PageHeader
        title="Limits"
        subtitle="Min / max amounts + daily count + daily value caps per transaction type."
      />
      <div className="px-6 py-6">
        <EmptyState
          icon={ListChecks}
          title="Phase G — Money Controls"
          description="Limits configuration ships with WAL-50 to WAL-53. The page will render an inline-editable table of per-(transaction_type, account_type) limits scoped to the active tenant."
        />
      </div>
    </div>
  );
}
