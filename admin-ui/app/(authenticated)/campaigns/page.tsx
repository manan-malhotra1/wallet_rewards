/**
 * Campaigns page — list every campaign (rule) in the active tenant and
 * create new ones via the wizard.
 *
 * "Campaign" is the operator-facing label for what the backend models
 * as a Rule (PRD §6.9). The URL changed from /rules to /campaigns in
 * the rename; the resource path on the API is still /api/v1/rules.
 *
 * For each campaign we fetch performance metrics from the backend
 * (`reward_events` aggregation) and surface Fires + Unique users
 * columns. Failures on a single campaign degrade gracefully — that
 * row shows em-dashes rather than failing the whole page.
 */
import { Megaphone, Plus } from "lucide-react";

import { getActiveTenantId } from "@/lib/active-tenant";
import {
  getRulePerformance,
  listInstruments,
  listRules,
  listSegmentGroups,
  listSegments,
  listServices,
} from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";
import type {
  Instrument,
  RulePerformance,
  Segment,
  SegmentGroup,
  Service,
} from "@/lib/api-types";

import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";

import { CampaignsTable } from "./_components/campaigns-table";
import { CreateCampaignDialog } from "./_components/create-campaign-dialog";

export const dynamic = "force-dynamic";

export default async function CampaignsPage() {
  const activeTenantId = await getActiveTenantId();
  if (!activeTenantId) {
    return (
      <div className="px-6 py-8">
        <EmptyState
          icon={Megaphone}
          title="No active tenant"
          description="Switch to a tenant to see its campaigns."
        />
      </div>
    );
  }

  let rules: Awaited<ReturnType<typeof listRules>> = [];
  let services: Service[] = [];
  let instruments: Instrument[] = [];
  let segments: Segment[] = [];
  let segmentGroups: SegmentGroup[] = [];
  let error: ApiError | null = null;
  try {
    [rules, services, instruments, segments, segmentGroups] = await Promise.all([
      listRules(activeTenantId),
      listServices(activeTenantId, "active"),
      listInstruments(activeTenantId, "active"),
      listSegments(activeTenantId),
      listSegmentGroups(activeTenantId),
    ]);
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  // A cashback reward pays in one of the tenant's financial currencies;
  // points always pay in the tenant's points instrument (PTS). We hand
  // the wizard both so its reward-currency dropdown and the derived
  // inline-budget currency stay tenant-accurate.
  const financialCurrencies = instruments
    .filter((i) => i.account_type === "financial_wallet")
    .map((i) => i.code);
  const pointsCurrency =
    instruments.find((i) => i.account_type === "points_account")?.code ?? "PTS";

  // Fetch performance for every campaign in parallel. A single failure
  // becomes `null` for that row so the page still renders the rest.
  const performance: Record<string, RulePerformance | null> = {};
  await Promise.all(
    rules.map(async (rule) => {
      try {
        performance[rule.id] = await getRulePerformance(
          rule.id,
          activeTenantId,
        );
      } catch {
        performance[rule.id] = null;
      }
    }),
  );

  return (
    <div>
      <PageHeader
        title="Campaigns"
        subtitle="Campaigns define when users earn rewards. Each active campaign fires on every matching event and reports unique reach and total fires."
        actions={
          <CreateCampaignDialog
            tenantId={activeTenantId}
            services={services}
            segments={segments}
            segmentGroups={segmentGroups}
            financialCurrencies={financialCurrencies}
            pointsCurrency={pointsCurrency}
            trigger={
              <button
                type="button"
                className="inline-flex h-8 items-center gap-2 rounded-md bg-[--color-brand] px-3 text-[13px] font-medium text-[--color-brand-foreground] hover:opacity-90"
              >
                <Plus className="h-3.5 w-3.5" />
                New campaign
              </button>
            }
          />
        }
      />
      <div className="px-6 py-6">
        {error && (
          <ErrorBanner
            className="mb-4"
            title="Couldn't load campaigns"
            description={error.message}
          />
        )}
        {!error && rules.length === 0 ? (
          <EmptyState
            icon={Megaphone}
            title="No campaigns yet"
            description="Campaigns trigger rewards when users meet configured conditions. Create the first one to start earning points or cashback."
          />
        ) : (
          <CampaignsTable
            rules={rules}
            performance={performance}
            tenantId={activeTenantId}
            segments={segments}
            segmentGroups={segmentGroups}
          />
        )}
      </div>
    </div>
  );
}
