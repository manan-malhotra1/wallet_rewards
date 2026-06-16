/**
 * Pricing page — per-tenant fixed_fee + variable_fee_pct per transaction
 * type (Pay-PRD-0430). Backend module scaffolded; endpoints arrive with
 * Phase G alongside Limits.
 */
import { Coins } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

export default function PricingPage() {
  return (
    <div>
      <PageHeader
        title="Pricing"
        subtitle="Fee structure per transaction type — fixed + percentage components."
      />
      <div className="px-6 py-6">
        <EmptyState
          icon={Coins}
          title="Phase G — Money Controls"
          description="Pricing configuration ships alongside Limits. The page will be inline-editable; every save writes an audit_log entry per NFR-0250."
        />
      </div>
    </div>
  );
}
