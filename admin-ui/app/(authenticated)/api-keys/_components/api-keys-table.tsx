"use client";

import { Ban } from "lucide-react";
import * as React from "react";

import { revokeApiKeyAction } from "@/app/(authenticated)/api-keys/_actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import type { ApiKey } from "@/lib/api-types";

export function ApiKeysTable({ keys, tenantId }: { keys: ApiKey[]; tenantId: string }) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);

  const onRevoke = async (id: string) => {
    if (
      !window.confirm(
        "Revoke this key? Any partner using it will immediately stop being able to call the API.",
      )
    ) {
      return;
    }
    setPending(id);
    const result = await revokeApiKeyAction(id, tenantId);
    setPending(null);
    if (result.ok) {
      toast({ title: "API key revoked" });
    } else {
      toast({
        title: "Couldn't revoke",
        description: `${result.errorCode}: ${result.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Key ID</TableHeaderCell>
            <TableHeaderCell>Label</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Last used</TableHeaderCell>
            <TableHeaderCell className="w-[40px]"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {keys.map((k) => (
            <TableRow key={k.id}>
              <TableCell className="font-mono text-xs">{k.key_id}</TableCell>
              <TableCell>{k.label ?? "—"}</TableCell>
              <TableCell>
                <Badge>{k.status}</Badge>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}
              </TableCell>
              <TableCell>
                {k.status === "active" && (
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Revoke API key"
                    disabled={pending === k.id}
                    onClick={() => onRevoke(k.id)}
                  >
                    <Ban className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
