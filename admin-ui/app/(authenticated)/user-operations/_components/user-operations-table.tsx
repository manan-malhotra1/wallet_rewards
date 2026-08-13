/**
 * User-operations table (Epic 3). Lists proposed user create / edit requests
 * and opens a detail drawer on view — loading the full operation (incl. its
 * review thread) via a server action before opening. The progress column shows
 * the N-eyes rule ("1 of 2 approved").
 */
"use client";

import { Eye, Loader2 } from "lucide-react";
import * as React from "react";

import { loadUserOperationAction } from "@/app/(authenticated)/user-operations/_actions";
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
import type { UserOperation } from "@/lib/api-types";
import {
  userOperationLabel,
  userOperationSummary,
} from "@/lib/user-operation-label";
import { formatTimestamp, shortId } from "@/lib/utils";

import {
  ApprovalProgress,
  UserOperationDetailDrawer,
} from "./user-operation-detail-drawer";

export function UserOperationsTable({
  operations,
  tenantId,
  canApprove,
  currentAdminId,
}: {
  operations: UserOperation[];
  tenantId: string;
  canApprove: boolean;
  currentAdminId: string;
}) {
  const { toast } = useToast();
  const [detail, setDetail] = React.useState<UserOperation | null>(null);
  const [open, setOpen] = React.useState(false);
  const [loadingId, setLoadingId] = React.useState<string | null>(null);

  const openDetail = async (id: string) => {
    setLoadingId(id);
    const result = await loadUserOperationAction(tenantId, id);
    setLoadingId(null);
    if (!result.ok) {
      toast({
        title: "Couldn't load operation",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
      return;
    }
    setDetail(result.operation);
    setOpen(true);
  };

  return (
    <>
      <div className="glass-panel overflow-hidden rounded-lg">
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell>Operation</TableHeaderCell>
              <TableHeaderCell>Summary</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell>Progress</TableHeaderCell>
              <TableHeaderCell>Maker</TableHeaderCell>
              <TableHeaderCell>Created</TableHeaderCell>
              <TableHeaderCell className="w-[80px]"> </TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {operations.map((op) => (
              <TableRow key={op.id}>
                <TableCell>
                  <Badge variant="info">{userOperationLabel(op.operation)}</Badge>
                </TableCell>
                <TableCell className="max-w-[280px] truncate text-sm text-foreground">
                  {userOperationSummary(op)}
                </TableCell>
                <TableCell>
                  <StatusPill status={op.status} variant="full" />
                </TableCell>
                <TableCell>
                  <ApprovalProgress operation={op} />
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {op.maker_admin_name ?? shortId(op.maker_admin_id)}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatTimestamp(op.created_at)}
                </TableCell>
                <TableCell>
                  <Tooltip content="View">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label="View"
                      disabled={loadingId === op.id}
                      onClick={() => openDetail(op.id)}
                    >
                      {loadingId === op.id ? (
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
        <UserOperationDetailDrawer
          operation={detail}
          tenantId={tenantId}
          canApprove={canApprove}
          currentAdminId={currentAdminId}
          open={open}
          onOpenChange={setOpen}
          onUpdated={(updated) => setDetail(updated)}
        />
      )}
    </>
  );
}
