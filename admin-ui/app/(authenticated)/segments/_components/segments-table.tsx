/**
 * <SegmentsTable> — list every segment with name + description + assign-user button.
 */
"use client";

import { UserPlus } from "lucide-react";
import * as React from "react";

import { addUserToSegmentAction } from "@/app/(authenticated)/segments/_actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import type { Segment } from "@/lib/api-types";
import { formatTimestamp, shortId } from "@/lib/utils";

export function SegmentsTable({ segments }: { segments: Segment[] }) {
  const { toast } = useToast();
  const [pending, setPending] = React.useState<string | null>(null);
  const [userIdPrompt, setUserIdPrompt] = React.useState<{
    segmentId: string;
    tenantId: string;
    value: string;
  } | null>(null);

  const onAddUser = async (
    segmentId: string,
    tenantId: string,
    userId: string,
  ) => {
    if (!userId.trim()) return;
    setPending(segmentId);
    const res = await addUserToSegmentAction(segmentId, tenantId, userId.trim());
    setPending(null);
    setUserIdPrompt(null);
    if (res.ok) {
      toast({ title: "User added to segment" });
    } else {
      toast({
        title: "Couldn't add",
        description: `${res.errorCode}: ${res.message}`,
        variant: "danger",
      });
    }
  };

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Name</TableHeaderCell>
            <TableHeaderCell>Description</TableHeaderCell>
            <TableHeaderCell>Created</TableHeaderCell>
            <TableHeaderCell className="text-right">Segment ID</TableHeaderCell>
            <TableHeaderCell className="w-[50px]"> </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {segments.map((s) => (
            <React.Fragment key={s.id}>
              <TableRow>
                <TableCell className="font-medium">{s.name}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {s.description ?? "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {formatTimestamp(s.created_at)}
                </TableCell>
                <TableCell className="text-right font-mono text-[11px] text-muted-foreground">
                  {shortId(s.id, "seg")}
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Assign user"
                    disabled={pending === s.id}
                    onClick={() =>
                      setUserIdPrompt({
                        segmentId: s.id,
                        tenantId: s.tenant_id,
                        value: "",
                      })
                    }
                  >
                    <UserPlus className="h-3.5 w-3.5 text-primary" />
                  </Button>
                </TableCell>
              </TableRow>
              {userIdPrompt?.segmentId === s.id && (
                <TableRow>
                  <TableCell colSpan={5} className="bg-muted/30">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">User ID:</span>
                      <Input
                        autoFocus
                        value={userIdPrompt.value}
                        onChange={(e) =>
                          setUserIdPrompt({
                            ...userIdPrompt,
                            value: e.target.value,
                          })
                        }
                        onKeyDown={(e) => {
                          if (e.key === "Enter")
                            onAddUser(s.id, s.tenant_id, userIdPrompt.value);
                          if (e.key === "Escape") setUserIdPrompt(null);
                        }}
                        placeholder="00000000-…"
                        className="max-w-sm font-mono text-xs"
                      />
                      <Button
                        size="sm"
                        onClick={() =>
                          onAddUser(s.id, s.tenant_id, userIdPrompt.value)
                        }
                        disabled={pending === s.id}
                      >
                        Assign
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setUserIdPrompt(null)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )}
            </React.Fragment>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
