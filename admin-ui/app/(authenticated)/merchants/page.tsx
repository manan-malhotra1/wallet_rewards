/**
 * Merchants page — placeholder.
 *
 * Merchant onboarding (Module 17) is on the roadmap but no backend
 * surface exists yet. This page exists so the sidebar entry doesn't
 * 404 and the operator gets context about what lands when.
 */
import { Box } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

export default function MerchantsPage() {
  return (
    <div>
      <PageHeader
        title="Merchants"
        subtitle="Onboard and configure merchants that participate in the rewards programme."
      />
      <div className="px-6 py-6">
        <EmptyState
          icon={Box}
          title="Merchants module deferred"
          description="Module 17 — Merchant Onboarding — lands after Phase G. The page will host the merchant directory, KYB status, and reward attribution rules."
        />
      </div>
    </div>
  );
}
