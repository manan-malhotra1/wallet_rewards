/**
 * Segments page — placeholder.
 *
 * Segments (Module 15) — both uploaded lists and behavioural builders —
 * are on the roadmap. Backend module folder exists; no endpoints yet.
 */
import { Layers } from "lucide-react";

import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

export default function SegmentsPage() {
  return (
    <div>
      <PageHeader
        title="Segments"
        subtitle="User cohorts — upload a CSV list or build behavioural conditions."
      />
      <div className="px-6 py-6">
        <EmptyState
          icon={Layers}
          title="Segments module deferred"
          description="Module 15 — Segments — lands after Phase G. The page will host both the segment list and the behavioural builder canvas; rules can be bound to a segment to restrict who progresses."
        />
      </div>
    </div>
  );
}
