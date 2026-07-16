/**
 * Config-requests table (Epic 24 / Story 24.3). Lists change requests and
 * opens a detail drawer on row click — loading the full request (incl. its
 * review thread) via a server action before opening.
 */
"use client";

import { Eye, Loader2 } from "lucide-react";
import * as React from "react";

import { loadConfigRequestAction } from "@/app/(authenticated)/config-requests/_actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { Tooltip } from "@/components/ui/tooltip";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import type { ConfigChangeRequest } from "@/lib/api-types";
import { configTypeLabel } from "@/lib/config-type-label";
import { formatTimestamp, shortId } from "@/lib/utils";

import { RequestDetailDrawer } from "./request-detail-drawer";

export function ConfigRequestsTable({
  requests,
  tenantId,
  canApprove,
  currentAdminId,
  serviceNames,
}: {
  requests: ConfigChangeRequest[];
  tenantId: string;
  canApprove: boolean;
  currentAdminId: string;
  /** `{ code: display_name }` so the detail drawer shows friendly service names. */
  serviceNames?: Record<string, string>;
}) {
  const { toast } = useToast();
  const [detail, setDetail] = React.useState<ConfigChangeRequest | null>(null);
  const [open, setOpen] = React.useState(false);
  const [loadingId, setLoadingId] = React.useState<string | null>(null);

  const openDetail = async (id: string) => {
    setLoadingId(id);
    const result = await loadConfigRequestAction(tenantId, id);
    setLoadingId(null);
    if (!result.ok) {
      toast({
        title: "Couldn't load request",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
      return;
    }
    setDetail(result.request);
    setOpen(true);
  };

  return (
    <>
      <div className="overflow-hidden rounded-lg border bg-card">
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell>Type</TableHeaderCell>
              <TableHeaderCell>Operation</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell className="text-right">Rev</TableHeaderCell>
              <TableHeaderCell>Maker</TableHeaderCell>
              <TableHeaderCell>Created</TableHeaderCell>
              <TableHeaderCell className="w-[80px]"> </TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {requests.map((req) => (
              <TableRow key={req.id}>
                <TableCell>
                  <Badge variant="info">{configTypeLabel(req.config_type)}</Badge>
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{req.operation}</Badge>
                </TableCell>
                <TableCell>
                  <StatusPill status={req.status} variant="full" />
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {req.revision}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {req.maker_admin_name ?? shortId(req.maker_admin_id)}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatTimestamp(req.created_at)}
                </TableCell>
                <TableCell>
                  <Tooltip content="View">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="View"
                      disabled={loadingId === req.id}
                      onClick={() => openDetail(req.id)}
                    >
                      {loadingId === req.id ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Eye className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {detail && (
        <RequestDetailDrawer
          request={detail}
          tenantId={tenantId}
          canApprove={canApprove}
          currentAdminId={currentAdminId}
          open={open}
          onOpenChange={setOpen}
          onUpdated={(updated) => setDetail(updated)}
          serviceNames={serviceNames}
        />
      )}
    </>
  );
}
