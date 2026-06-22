"use client";

/**
 * TenantCard — per-tenant identity card with inline editing.
 *
 * Editable: name (text), business_type (select Wallet/Rewards/Both).
 * Read-only: id, keycloak_realm, base_currency, status, created_at.
 *
 * On save, posts to the updateTenantAction server action and surfaces
 * the API error message in-card on failure (e.g. duplicate name → 409).
 */
import { useState, useTransition } from "react";

import type { BusinessType, Tenant } from "@/lib/api-types";
import { formatTimestamp } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { StatusPill } from "@/components/ui/status-pill";

import { updateTenantAction } from "../_actions";

const BUSINESS_TYPE_LABEL: Record<BusinessType, string> = {
  wallet: "Wallet",
  rewards: "Rewards",
  both: "Both",
};

export function TenantCard({ tenant }: { tenant: Tenant }) {
  const [name, setName] = useState(tenant.name);
  const [businessType, setBusinessType] = useState<BusinessType>(
    tenant.business_type,
  );
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const dirty = name !== tenant.name || businessType !== tenant.business_type;

  function handleSave() {
    setError(null);
    setSavedAt(null);
    startTransition(async () => {
      const payload: { name?: string; business_type?: BusinessType } = {};
      if (name !== tenant.name) payload.name = name;
      if (businessType !== tenant.business_type)
        payload.business_type = businessType;

      const result = await updateTenantAction(tenant.id, payload);
      if (!result.ok) {
        setError(`${result.errorCode}: ${result.message}`);
        return;
      }
      setSavedAt(new Date().toISOString());
    });
  }

  function handleReset() {
    setName(tenant.name);
    setBusinessType(tenant.business_type);
    setError(null);
  }

  return (
    <div className="rounded-lg border border-[--color-border] bg-[--color-surface-1] p-5">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div className="flex-1">
          <Label htmlFor={`name-${tenant.id}`}>Name</Label>
          <Input
            id={`name-${tenant.id}`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 max-w-md"
            disabled={pending}
          />
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wide text-[--color-text-3]">
            Status
          </div>
          <StatusPill status={tenant.status.toUpperCase()} variant="dense" />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div>
          <Label>Business type</Label>
          <Select
            value={businessType}
            onValueChange={(v) => setBusinessType(v as BusinessType)}
            disabled={pending}
          >
            <SelectTrigger className="mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="wallet">Wallet</SelectItem>
              <SelectItem value="rewards">Rewards</SelectItem>
              <SelectItem value="both">Both</SelectItem>
            </SelectContent>
          </Select>
          <p className="mt-1 text-[11px] text-[--color-text-3]">
            Determines which services this tenant has enabled.
          </p>
        </div>

        <div>
          <Label>Tenant ID</Label>
          <div className="mt-1 rounded-md border border-[--color-border] bg-[--color-surface-2] px-3 py-2 font-mono text-[12px] text-[--color-text-2]">
            {tenant.id}
          </div>
          <p className="mt-1 text-[11px] text-[--color-text-3]">
            Read-only — set at tenant creation.
          </p>
        </div>

        <div>
          <Label>Keycloak realm</Label>
          <div className="mt-1 rounded-md border border-[--color-border] bg-[--color-surface-2] px-3 py-2 font-mono text-[12px] text-[--color-text-2]">
            {tenant.keycloak_realm ?? "—"}
          </div>
          <p className="mt-1 text-[11px] text-[--color-text-3]">
            Read-only — managed in Keycloak.
          </p>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
        <div>
          <Label>Base currency</Label>
          <div className="mt-1 font-mono text-[12px]">
            {tenant.base_currency ?? "—"}
          </div>
        </div>
        <div>
          <Label>Current business</Label>
          <div className="mt-1">
            <Badge tone={tenant.business_type === "rewards" ? "accent" : "brand"}>
              {BUSINESS_TYPE_LABEL[tenant.business_type]}
            </Badge>
          </div>
        </div>
        <div>
          <Label>Created</Label>
          <div className="mt-1 text-[11px] text-[--color-text-3]">
            {formatTimestamp(tenant.created_at)}
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-[--color-danger]/40 bg-[--color-danger]/10 px-3 py-2 text-[12px] text-[--color-danger]">
          {error}
        </div>
      )}
      {savedAt && !error && (
        <div className="mt-4 text-[12px] text-[--color-text-3]">
          Saved {formatTimestamp(savedAt)}.
        </div>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <Button
          variant="ghost"
          onClick={handleReset}
          disabled={!dirty || pending}
        >
          Reset
        </Button>
        <Button onClick={handleSave} disabled={!dirty || pending}>
          {pending ? "Saving…" : "Save"}
        </Button>
      </div>
    </div>
  );
}
