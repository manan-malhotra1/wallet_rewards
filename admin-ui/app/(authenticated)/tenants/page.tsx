/**
 * Tenants page — list every tenant and surface its deployment mode and
 * status. Detail tabs (config keys / roles / event sources / API keys) land
 * in Phase G.
 */
import { Settings2 } from "lucide-react";

import { listTenants } from "@/lib/api-endpoints";
import { ApiError } from "@/lib/api";

import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorBanner } from "@/components/ui/error-banner";
import { PageHeader } from "@/components/ui/page-header";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { formatTimestamp } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function TenantsPage() {
  let tenants: Awaited<ReturnType<typeof listTenants>> = [];
  let error: ApiError | null = null;
  try {
    tenants = await listTenants();
  } catch (err) {
    if (err instanceof ApiError) error = err;
    else throw err;
  }

  return (
    <div>
      <PageHeader
        title="Tenants"
        subtitle="Every isolated workspace on the platform. Switch tenants via the topbar."
      />
      <div className="px-6 py-6">
        {error && (
          <ErrorBanner
            className="mb-4"
            title="Couldn't load tenants"
            description={`${error.errorCode}: ${error.message}`}
          />
        )}
        {!error && tenants.length === 0 ? (
          <EmptyState
            icon={Settings2}
            title="No tenants yet"
            description="Run the backend seed script to create the first tenant."
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-[--color-border] bg-[--color-surface-1]">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Name</TableHeaderCell>
                  <TableHeaderCell>Mode</TableHeaderCell>
                  <TableHeaderCell>Currency</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell>Created</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {tenants.map((tenant) => (
                  <TableRow key={tenant.id}>
                    <TableCell className="font-medium">{tenant.name}</TableCell>
                    <TableCell>
                      <Badge tone={tenant.deployment_mode === "wallet" ? "brand" : "accent"}>
                        {tenant.deployment_mode}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-[12px]">
                      {tenant.base_currency ?? "—"}
                    </TableCell>
                    <TableCell>
                      <StatusPill
                        status={tenant.status.toUpperCase()}
                        variant="dense"
                      />
                    </TableCell>
                    <TableCell className="text-[11px] text-[--color-text-3]">
                      {formatTimestamp(tenant.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
