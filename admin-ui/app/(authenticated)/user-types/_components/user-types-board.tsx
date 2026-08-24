/**
 * <UserTypesBoard> — the tenant's user-type catalog, one section per category.
 *
 * Retail and Business render two-level: each top-level type with its children
 * indented beneath it. Consumers is flat, because the category does not support
 * a hierarchy at all.
 *
 * System types carry no edit or retire affordance — the buttons are ABSENT
 * rather than disabled. They are platform-wide rows no tenant owns, so an
 * affordance that could only ever fail is worse than no affordance.
 */
"use client";

import { Pencil } from "lucide-react";
import * as React from "react";

import {
  proposeUserTypeUpdateAction,
  type ProposeUserTypeInput,
} from "@/app/(authenticated)/user-types/_actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import type { UserTypeCatalog, UserTypeOption } from "@/lib/api-types";
import { groupTypesByCategory } from "@/lib/user-type-catalog";
import { cn } from "@/lib/utils";

import { CreateUserTypeDialog } from "./create-user-type-dialog";

/** The full desired row for a status-only proposal (nothing else changes). */
function statusChangePayload(
  tenantId: string,
  type: UserTypeOption,
  status: "active" | "retired",
): ProposeUserTypeInput {
  return {
    tenant_id: tenantId,
    code: type.code,
    label: type.label,
    category_code: type.category_code,
    parent_type_code: type.parent_type_code,
    status,
  };
}

/**
 * Retire / reactivate affordance for a tenant-owned type.
 *
 * Retiring is proposed, not applied, and it is reversible — but it stops the
 * type being assignable to anyone new, so it asks first.
 *
 * @param type The row being changed.
 * @param tenantId The active tenant.
 */
function StatusChangeButton({
  type,
  tenantId,
}: {
  type: UserTypeOption;
  tenantId: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const { toast } = useToast();
  const retiring = type.status === "active";
  const verb = retiring ? "Retire" : "Reactivate";

  const onConfirm = async () => {
    if (!type.id) return;
    setSubmitting(true);
    const result = await proposeUserTypeUpdateAction(
      tenantId,
      type.id,
      statusChangePayload(tenantId, type, retiring ? "retired" : "active"),
    );
    setSubmitting(false);
    if (result.ok) {
      toast({ title: `${verb} proposed — pending approval`, description: type.label });
      setOpen(false);
      return;
    }
    toast({
      title: `Couldn't propose ${verb.toLowerCase()}`,
      description: `${result.errorCode}: ${result.message}`,
      variant: "danger",
    });
  };

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        aria-label={`${verb} ${type.label}`}
      >
        {verb}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              {verb} {type.label}?
            </DialogTitle>
            <DialogDescription>
              {retiring
                ? "Retiring stops the type being assigned to anyone new. Existing users and config rows keep it — a user type is never deleted. Takes effect once a second admin approves."
                : "Reactivating makes the type assignable again. Takes effect once a second admin approves."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={onConfirm} disabled={submitting}>
              {submitting ? "Proposing…" : `Propose ${verb.toLowerCase()}`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** Per-row Edit affordance — opens the dialog in edit mode (proposes `update`). */
function EditTypeButton({
  type,
  tenantId,
  catalog,
}: {
  type: UserTypeOption;
  tenantId: string;
  catalog: UserTypeCatalog;
}) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={`Edit ${type.label}`}
        onClick={() => setOpen(true)}
      >
        <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
      </Button>
      <CreateUserTypeDialog
        tenantId={tenantId}
        catalog={catalog}
        editType={type}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}

/**
 * One catalog row: label, status, badges and (tenant types only) actions.
 *
 * The `code` is deliberately not shown. It is a machine identifier derived from
 * the label — the join key on `users.user_type` — and an administrator has no
 * decision to make about it.
 */
function TypeRow({
  type,
  tenantId,
  catalog,
  canPropose,
  indented,
}: {
  type: UserTypeOption;
  tenantId: string;
  catalog: UserTypeCatalog;
  canPropose: boolean;
  /** A child type — indented under its parent to show the two-level hierarchy. */
  indented: boolean;
}) {
  return (
    <TableRow>
      <TableCell>
        <div className={cn("flex items-center gap-2", indented && "pl-6")}>
          <span className="text-sm font-medium">{type.label}</span>
          {type.is_system && <Badge tone="neutral">System</Badge>}
        </div>
      </TableCell>
      <TableCell>
        <StatusPill status={type.status.toUpperCase()} />
      </TableCell>
      <TableCell>
        <div className="flex items-center justify-end gap-1">
          {/* System types are platform-wide and immutable: no affordance at all. */}
          {canPropose && !type.is_system && (
            <>
              <EditTypeButton type={type} tenantId={tenantId} catalog={catalog} />
              <StatusChangeButton type={type} tenantId={tenantId} />
            </>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

/**
 * The whole catalog, grouped by category.
 *
 * @param catalog The tenant's catalog, retired types included.
 * @param tenantId The active tenant.
 * @param canPropose platform-admin gate — hides every mutation affordance for
 *   other admins (the backend also 403s).
 */
export function UserTypesBoard({
  catalog,
  tenantId,
  canPropose,
}: {
  catalog: UserTypeCatalog;
  tenantId: string;
  canPropose: boolean;
}) {
  const groups = React.useMemo(() => groupTypesByCategory(catalog), [catalog]);

  return (
    <div className="space-y-6">
      {groups.map(({ category, types }) => {
        // A flat category has no parents to nest under, so every type is a row
        // at the top level. A hierarchical one renders each parent followed by
        // the children that hang off it.
        const parents = category.supports_hierarchy
          ? types.filter((t) => !t.parent_type_code)
          : types;
        const orphans = category.supports_hierarchy
          ? types.filter(
              (t) =>
                t.parent_type_code &&
                !types.some((p) => p.code === t.parent_type_code),
            )
          : [];

        return (
          <section key={category.code} aria-labelledby={`category-${category.code}`}>
            <h2
              id={`category-${category.code}`}
              className="mb-2 text-sm font-semibold text-foreground"
            >
              {category.label}
            </h2>
            <div className="glass-panel overflow-hidden rounded-lg">
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Type</TableHeaderCell>
                    <TableHeaderCell>Status</TableHeaderCell>
                    <TableHeaderCell className="w-[180px] text-right"> </TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {types.length === 0 && (
                    <TableEmpty message="No types in this category yet." colSpan={3} />
                  )}
                  {parents.map((parent) => (
                    <React.Fragment key={parent.code}>
                      <TypeRow
                        type={parent}
                        tenantId={tenantId}
                        catalog={catalog}
                        canPropose={canPropose}
                        indented={false}
                      />
                      {types
                        .filter((t) => t.parent_type_code === parent.code)
                        .map((child) => (
                          <TypeRow
                            key={child.code}
                            type={child}
                            tenantId={tenantId}
                            catalog={catalog}
                            canPropose={canPropose}
                            indented
                          />
                        ))}
                    </React.Fragment>
                  ))}
                  {/* A child whose parent is not in the visible set still has to
                      be listed, or it would vanish from the page entirely. */}
                  {orphans.map((child) => (
                    <TypeRow
                      key={child.code}
                      type={child}
                      tenantId={tenantId}
                      catalog={catalog}
                      canPropose={canPropose}
                      indented
                    />
                  ))}
                </TableBody>
              </Table>
            </div>
          </section>
        );
      })}
    </div>
  );
}
