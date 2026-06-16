/**
 * <AuditFilters> — narrow the audit list by entity_type / entity_id.
 * Submits as a navigation; the page server-component re-fetches.
 */
"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AuditFilters({
  initialEntityType,
  initialEntityId,
}: {
  initialEntityType: string;
  initialEntityId: string;
}) {
  const router = useRouter();
  const [entityType, setEntityType] = React.useState(initialEntityType);
  const [entityId, setEntityId] = React.useState(initialEntityId);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const params = new URLSearchParams();
    if (entityType) params.set("entity_type", entityType);
    if (entityId) params.set("entity_id", entityId);
    router.push(`/audit?${params.toString()}`);
  };

  const onClear = () => {
    setEntityType("");
    setEntityId("");
    router.push("/audit");
  };

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-wrap items-end gap-3 rounded-lg border border-[--color-border] bg-[--color-surface-1] p-3"
    >
      <div className="w-[200px]">
        <Label htmlFor="entity-type">Entity type</Label>
        <Input
          id="entity-type"
          placeholder="redemption"
          value={entityType}
          onChange={(e) => setEntityType(e.target.value)}
          className="mt-1"
        />
      </div>
      <div className="flex-1 min-w-[260px]">
        <Label htmlFor="entity-id">Entity ID</Label>
        <Input
          id="entity-id"
          placeholder="UUID"
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
          className="mt-1"
        />
      </div>
      <Button type="submit" size="md">
        Filter
      </Button>
      <Button type="button" variant="ghost" onClick={onClear}>
        Clear
      </Button>
    </form>
  );
}
