/**
 * <CreateUserTypeDialog> — propose a new user type, or edit a live one.
 *
 * Every mutation is a maker-checker proposal (config_type "user_type"); there
 * is no direct write endpoint. In EDIT mode the category locks — it is an
 * immutable join key on the backend — and submitting proposes an `update`
 * against the live row instead of a `create`.
 *
 * The operator never sees the `code`. It is a machine identifier — the join key
 * on `users.user_type` and the maker-checker scope key — so it is derived from
 * the Label by `deriveUserTypeCode` at submit time and sent in the payload
 * exactly as a typed one used to be. On the EDIT path it is NOT re-derived: a
 * code is immutable once created (spec D5), and re-deriving it on a relabel
 * would orphan every config row scoped to the old one.
 *
 * The parent dropdown is populated from `topLevelTypes`, which never offers a
 * child type, so a third level cannot be constructed here even before the
 * service refuses it.
 *
 * There is no merchant-capability control: the category IS the capability. A
 * type filed under Business may carry a merchant-bound API key, one under
 * Retail may take cash-outs, and the backend reads that off `category_code`.
 */
"use client";

import * as React from "react";

import {
  proposeUserTypeChangeAction,
  proposeUserTypeUpdateAction,
} from "@/app/(authenticated)/user-types/_actions";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import type { UserTypeCatalog, UserTypeOption } from "@/lib/api-types";
import { deriveUserTypeCode, topLevelTypes } from "@/lib/user-type-catalog";

interface FormState {
  label: string;
  categoryCode: string;
  hasParent: boolean;
  parentTypeCode: string;
}

/** The blank create form, or the live row's current state in edit mode. */
function initialForm(editType?: UserTypeOption): FormState {
  if (editType) {
    return {
      label: editType.label,
      categoryCode: editType.category_code,
      hasParent: editType.parent_type_code !== null,
      parentTypeCode: editType.parent_type_code ?? "",
    };
  }
  return {
    label: "",
    categoryCode: "",
    hasParent: false,
    parentTypeCode: "",
  };
}

/**
 * Propose a new user type, or an edit to an existing one.
 *
 * @param tenantId The active tenant — the catalog is tenant-scoped.
 * @param catalog The tenant's user-type catalog. Retired types are included:
 *   their codes are still taken, so code derivation must de-duplicate against
 *   them too.
 * @param editType A live type to edit in place; omit for the create path.
 * @param trigger Trigger element; omit when driving via `open`/`onOpenChange`.
 * @param open Controlled open state (the per-row Edit affordance drives this).
 * @param onOpenChange Controlled open setter.
 */
export function CreateUserTypeDialog({
  tenantId,
  catalog,
  editType,
  trigger,
  open: controlledOpen,
  onOpenChange,
}: {
  tenantId: string;
  catalog: UserTypeCatalog;
  editType?: UserTypeOption;
  trigger?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [internalOpen, setInternalOpen] = React.useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = onOpenChange ?? setInternalOpen;
  const editMode = Boolean(editType);

  const [form, setForm] = React.useState<FormState>(() => initialForm(editType));
  const [submitting, setSubmitting] = React.useState(false);
  const [errorBanner, setErrorBanner] = React.useState<string | null>(null);
  const { toast } = useToast();

  React.useEffect(() => {
    if (!open) {
      setForm(initialForm(editType));
      setErrorBanner(null);
    }
  }, [open, editType]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const categories = React.useMemo(
    () => [...catalog.categories].sort((a, b) => a.display_order - b.display_order),
    [catalog.categories],
  );
  const category = categories.find((c) => c.code === form.categoryCode) ?? null;
  const supportsHierarchy = category?.supports_hierarchy ?? false;
  const parentOptions = React.useMemo(
    () =>
      topLevelTypes(catalog, form.categoryCode).filter(
        // A type can never be its own parent.
        (t) => t.code !== editType?.code,
      ),
    [catalog, form.categoryCode, editType?.code],
  );

  const onCategoryChange = (next: string) => {
    setForm((prev) => ({
      ...prev,
      categoryCode: next,
      // A parent from the old category cannot be legal under the new one.
      hasParent: false,
      parentTypeCode: "",
    }));
  };

  const onSubmit = async () => {
    setErrorBanner(null);
    const label = form.label.trim();
    if (!label) {
      setErrorBanner("Enter a label — this is the name operators will see.");
      return;
    }
    if (!form.categoryCode) {
      setErrorBanner("Pick a category.");
      return;
    }
    if (supportsHierarchy && form.hasParent && !form.parentTypeCode) {
      setErrorBanner("Pick the parent type this one sits under.");
      return;
    }

    // An existing row keeps the code it was created with, always. Only a brand
    // new type gets one derived from its label.
    const code = editType ? editType.code : deriveUserTypeCode(label, catalog);
    const payload = {
      tenant_id: tenantId,
      code,
      label,
      category_code: form.categoryCode,
      parent_type_code:
        supportsHierarchy && form.hasParent ? form.parentTypeCode : null,
      ...(editType ? { status: editType.status } : {}),
    };

    setSubmitting(true);
    const result =
      editType && editType.id
        ? await proposeUserTypeUpdateAction(tenantId, editType.id, payload)
        : await proposeUserTypeChangeAction(payload);
    setSubmitting(false);

    if (!result.ok) {
      setErrorBanner(`${result.errorCode}: ${result.message}`);
      return;
    }
    toast({
      title: "Change proposed — pending approval",
      description: label,
    });
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {trigger && <DialogTrigger asChild>{trigger}</DialogTrigger>}
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{editMode ? "Edit user type" : "New user type"}</DialogTitle>
          <DialogDescription>
            {editMode
              ? "The category is permanent — it is written onto every user and config row. Goes live after a second admin approves."
              : "A new kind of customer, priced and capped like any other. Goes live after a second admin approves."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label htmlFor="user-type-label">Label</Label>
            <Input
              id="user-type-label"
              value={form.label}
              onChange={(e) => update("label", e.target.value)}
              placeholder="Junior agent"
              className="mt-1"
            />
          </div>

          <div>
            <Label htmlFor="user-type-category">Category</Label>
            <Select
              value={form.categoryCode}
              onValueChange={onCategoryChange}
              disabled={editMode}
            >
              <SelectTrigger id="user-type-category" aria-label="Category" className="mt-1">
                <SelectValue placeholder="Select a category" />
              </SelectTrigger>
              <SelectContent>
                {categories.map((c) => (
                  <SelectItem key={c.code} value={c.code}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {supportsHierarchy && (
            <div className="space-y-2">
              <Checkbox
                id="user-type-has-parent"
                checked={form.hasParent}
                onChange={(e) => {
                  update("hasParent", e.target.checked);
                  if (!e.target.checked) update("parentTypeCode", "");
                }}
                label="This type sits under a parent"
              />
              {form.hasParent && (
                <div>
                  <Label htmlFor="user-type-parent">Parent type</Label>
                  <Select
                    value={form.parentTypeCode}
                    onValueChange={(v) => update("parentTypeCode", v)}
                    disabled={parentOptions.length === 0}
                  >
                    <SelectTrigger
                      id="user-type-parent"
                      aria-label="Parent type"
                      className="mt-1"
                    >
                      <SelectValue placeholder="Select a parent" />
                    </SelectTrigger>
                    <SelectContent>
                      {parentOptions.map((t) => (
                        <SelectItem key={t.code} value={t.code}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {parentOptions.length === 0 && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      This category has no active top-level type to sit under yet.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {errorBanner && (
            <ErrorBanner title="Couldn't propose" description={errorBanner} />
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting}>
            {submitting ? "Proposing…" : "Propose change"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
