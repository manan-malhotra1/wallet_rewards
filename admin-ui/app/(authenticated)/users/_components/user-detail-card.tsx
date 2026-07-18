/**
 * <UserDetailCard> — the redesigned single-user detail view ("1b" layout).
 *
 * Server component. A navy hero header (name / type / status / primary
 * identifier + Edit), a KPI band of stat cards, then collapsible sections
 * (Personal & KYC, Address & country, KYC documents, Accounts & balances,
 * Transactions). Interactivity lives in client islands: <EditUserDrawer>
 * (routes edits through Epic 3 propose) and <ResetPinButton>. Money renders via
 * <Money>, points via <Points>, statuses via <StatusPill>.
 */
import {
  CreditCard,
  Mail,
  Phone,
  ScanLine,
  ShieldCheck,
  UserCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Money, Points } from "@/components/ui/money";
import { StatusPill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@/components/ui/table";
import type { UserDetail, UserType } from "@/lib/api-types";
import type { UserTransaction } from "@/lib/api-endpoints";
import { transactionTypeLabel } from "@/lib/transaction-type-label";
import { formatTimestamp, shortId } from "@/lib/utils";

import { AccessLevelPill } from "./access-level-pill";
import { AccessLockControl } from "./access-lock-control";
import { AddIdentifierDialog } from "./add-identifier-dialog";
import { EditUserDrawer, type OpenUpdateRequest } from "./edit-user-drawer";
import { LockoutBadge } from "./lockout-badge";
import { ResetPinButton } from "./reset-pin-button";
import { UnlockButton } from "./unlock-button";
import { UserTypeBadge } from "./user-type-badge";

const SYSTEM_COUNTERPARTY_LABEL: Record<string, string> = {
  withdraw: "Operator float",
  airtime_recharge: "Airtime merchant",
  redemption: "Redemption provider",
  reward_issuance: "Rewards engine",
  fund: "System cash inflow",
  treasury_adjust: "Operator adjustment",
};

function counterpartyDisplay(txn: UserTransaction): string {
  if (txn.counterparty_name) return txn.counterparty_name;
  return SYSTEM_COUNTERPARTY_LABEL[txn.transaction_type] ?? "—";
}

const IDENTIFIER_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  phone: Phone,
  email: Mail,
  account_number: ScanLine,
  card_number: CreditCard,
};

const ACCOUNT_TYPE_LABEL: Record<string, string> = {
  financial_wallet: "Financial wallet",
  points_account: "Points",
  system_points_issuance: "System points issuance",
  provider_redemption_wallet: "Provider redemption wallet",
  system_cash_inflow: "System cash inflow",
};

function fullName(detail: UserDetail): string | null {
  if (!detail.profile) return null;
  const { first_name, last_name } = detail.profile;
  if (!first_name && !last_name) return null;
  return [first_name, last_name].filter(Boolean).join(" ");
}

/** A single KPI stat card in the band under the hero. */
function StatCard({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 text-lg font-semibold tabular-nums">{children}</div>
    </div>
  );
}

/** A collapsible section using native <details> — no client JS needed. */
function Section({
  title,
  description,
  defaultOpen = false,
  children,
}: {
  title: string;
  description?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <details
      open={defaultOpen}
      className="group overflow-hidden rounded-lg border bg-card"
    >
      <summary className="flex cursor-pointer items-center justify-between px-5 py-3.5 text-sm font-medium marker:content-none hover:bg-muted/40">
        <span className="flex flex-col">
          {title}
          {description && (
            <span className="text-xs font-normal text-muted-foreground">
              {description}
            </span>
          )}
        </span>
        <span className="text-xs text-muted-foreground transition-transform group-open:rotate-90">
          ▶
        </span>
      </summary>
      <div className="border-t px-5 py-4">{children}</div>
    </details>
  );
}

export interface UserDetailCardProps {
  detail: UserDetail;
  transactions: UserTransaction[];
  resolvedIdentifierValue: string | null;
  resolvedIdentifierType: string;
  /** An update request already awaiting review, so Edit can surface it. */
  openUpdate: OpenUpdateRequest | null;
  /** True for platform-admins — gates the Unlock affordance (backend also 403s). */
  canManageLockout: boolean;
}

export function UserDetailCard({
  detail,
  transactions,
  resolvedIdentifierValue,
  resolvedIdentifierType,
  openUpdate,
  canManageLockout,
}: UserDetailCardProps) {
  const name = fullName(detail);
  const primaryIdentifier =
    resolvedIdentifierValue ?? detail.identifiers[0]?.identifier_value ?? "—";
  const financialWallets = detail.accounts.filter(
    (a) => a.account_type === "financial_wallet",
  );
  const pointsAccount = detail.accounts.find(
    (a) => a.account_type === "points_account",
  );
  const primaryWallet = financialWallets[0];
  // The backend exposes status lowercased ("active"/"suspended").
  const editStatus: "active" | "suspended" =
    detail.status === "suspended" ? "suspended" : "active";

  return (
    <div className="space-y-4">
      {/* Navy hero header (Sasai navy #144989) */}
      <div className="rounded-xl bg-[#144989] p-6 text-white shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-white/15">
              <UserCircle className="h-7 w-7" />
            </div>
            <div>
              <h2 className="text-xl font-semibold">
                {name ?? primaryIdentifier ?? "Unnamed user"}
              </h2>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <UserTypeBadge type={detail.user_type} />
                <StatusPill status={detail.status.toUpperCase()} variant="full" />
                {detail.is_locked && (
                  <LockoutBadge unlocksInSeconds={detail.unlocks_in_seconds} />
                )}
                <AccessLevelPill level={detail.access_level} />
              </div>
              <p className="mt-2 font-mono text-sm text-white/80">
                {primaryIdentifier}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <EditUserDrawer
              userId={detail.id}
              tenantId={detail.tenant_id}
              current={{
                firstName: detail.profile?.first_name ?? "",
                lastName: detail.profile?.last_name ?? "",
                status: editStatus,
                userType: detail.user_type as UserType,
              }}
              identifiers={detail.identifiers}
              openUpdate={openUpdate}
            />
            <ResetPinButton userId={detail.id} tenantId={detail.tenant_id} />
            {detail.is_locked && canManageLockout && (
              <UnlockButton userId={detail.id} tenantId={detail.tenant_id} />
            )}
            {canManageLockout && (
              <AccessLockControl
                userId={detail.id}
                tenantId={detail.tenant_id}
                level={detail.access_level}
              />
            )}
          </div>
        </div>
      </div>

      {/* KPI band */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Wallet balance">
          {primaryWallet ? (
            <Money
              amount={primaryWallet.available_balance}
              currency={primaryWallet.currency}
            />
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
          {financialWallets.length > 1 && (
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              +{financialWallets.length - 1} more
            </span>
          )}
        </StatCard>
        <StatCard label="Points">
          {pointsAccount ? (
            <Points amount={pointsAccount.available_balance} />
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </StatCard>
        <StatCard label="Transactions">
          {transactions.length}
          {transactions.length === 50 && (
            <span className="ml-1 text-xs font-normal text-muted-foreground">
              (latest)
            </span>
          )}
        </StatCard>
        <StatCard label="Member since">
          <span className="text-sm font-medium">
            {formatTimestamp(detail.created_at)}
          </span>
        </StatCard>
      </div>

      {/* Personal & KYC */}
      <Section
        title="Personal & KYC"
        description="Profile fields captured during registration."
        defaultOpen
      >
        {detail.profile ? (
          <dl className="grid grid-cols-2 gap-4 text-sm md:grid-cols-3">
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                First name
              </dt>
              <dd className="text-foreground">{detail.profile.first_name ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Last name
              </dt>
              <dd className="text-foreground">{detail.profile.last_name ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Date of birth
              </dt>
              <dd className="text-foreground">
                {detail.profile.date_of_birth ?? "—"}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">
            No profile data captured yet.
          </p>
        )}
        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Identifiers
            </p>
            {canManageLockout && (
              <AddIdentifierDialog
                userId={detail.id}
                tenantId={detail.tenant_id}
              />
            )}
          </div>
          {detail.identifiers.length === 0 ? (
            <p className="text-sm text-muted-foreground">No identifiers.</p>
          ) : (
            <ul className="space-y-2">
              {detail.identifiers.map((ident) => {
                const Icon = IDENTIFIER_ICON[ident.identifier_type] ?? UserCircle;
                return (
                  <li
                    key={`${ident.identifier_type}-${ident.identifier_value}`}
                    className="flex items-center gap-3 rounded-md border bg-muted/30 px-3 py-2"
                  >
                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10">
                      <Icon className="h-3.5 w-3.5 text-primary" />
                    </div>
                    <div className="flex-1">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                        {ident.identifier_type}
                      </p>
                      <p className="font-mono text-sm text-foreground">
                        {ident.identifier_value}
                      </p>
                    </div>
                    {ident.verified ? (
                      <Badge variant="success">
                        <ShieldCheck className="h-3 w-3" />
                        Verified
                      </Badge>
                    ) : (
                      <Badge variant="secondary">Unverified</Badge>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </Section>

      {/* Address & country — not exposed by the API yet; shown gracefully. */}
      <Section
        title="Address & country"
        description="Residential address and country of residence."
      >
        {detail.parent_user_id ? (
          <p className="mb-2 text-sm text-muted-foreground">
            Reports to{" "}
            <span className="font-mono">
              {detail.parent_name ?? shortId(detail.parent_user_id, "usr")}
            </span>
          </p>
        ) : null}
        <p className="text-sm text-muted-foreground">
          No address on file — address capture is not part of registration yet.
        </p>
      </Section>

      {/* KYC documents — not exposed by the API yet; shown gracefully. */}
      <Section
        title="KYC documents"
        description="Uploaded identity documents and verification state."
      >
        <p className="text-sm text-muted-foreground">
          No documents on file — document upload arrives in a later phase.
        </p>
      </Section>

      {/* Accounts & balances */}
      <Section
        title="Accounts & balances"
        description="Derived balances live from the ledger — no snapshot caching."
        defaultOpen
      >
        {detail.accounts.length === 0 ? (
          <p className="text-sm text-muted-foreground">This user has no accounts.</p>
        ) : (
          <div className="-mx-5 overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Type</TableHeaderCell>
                  <TableHeaderCell>Currency</TableHeaderCell>
                  <TableHeaderCell className="text-right">Balance</TableHeaderCell>
                  <TableHeaderCell className="text-right">Reserved</TableHeaderCell>
                  <TableHeaderCell className="text-right">Available</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {detail.accounts.map((acct) => {
                  const isPoints = acct.currency === "PTS";
                  return (
                    <TableRow key={acct.id}>
                      <TableCell className="font-medium">
                        {ACCOUNT_TYPE_LABEL[acct.account_type] ?? acct.account_type}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {acct.currency}
                      </TableCell>
                      <TableCell className="text-right">
                        {isPoints ? (
                          <Points amount={acct.balance} />
                        ) : (
                          <Money amount={acct.balance} currency={acct.currency} />
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        {isPoints ? (
                          <Points amount={acct.reserved_balance} />
                        ) : (
                          <Money
                            amount={acct.reserved_balance}
                            currency={acct.currency}
                          />
                        )}
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {isPoints ? (
                          <Points amount={acct.available_balance} />
                        ) : (
                          <Money
                            amount={acct.available_balance}
                            currency={acct.currency}
                          />
                        )}
                      </TableCell>
                      <TableCell>
                        <StatusPill status={acct.status.toUpperCase()} variant="dense" />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </Section>

      {/* Transactions — latest 50 ledger events touching this user */}
      <Section
        title="Transactions"
        description="Latest 50 movements on this user's wallets."
      >
        {transactions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No transactions yet on this user's wallets.
          </p>
        ) : (
          <div className="-mx-5 overflow-x-auto">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>When</TableHeaderCell>
                  <TableHeaderCell>Service</TableHeaderCell>
                  <TableHeaderCell>Direction</TableHeaderCell>
                  <TableHeaderCell>Counterparty</TableHeaderCell>
                  <TableHeaderCell className="text-right">Amount</TableHeaderCell>
                  <TableHeaderCell className="text-right">Service charge</TableHeaderCell>
                  <TableHeaderCell>Currency</TableHeaderCell>
                  <TableHeaderCell>Txn ID</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {transactions.map((t) => {
                  const isIn = t.direction === "in";
                  const isPoints = t.currency === "PTS";
                  return (
                    <TableRow key={t.id}>
                      <TableCell className="whitespace-nowrap text-[11px] text-muted-foreground">
                        {formatTimestamp(t.created_at)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-medium">
                        {transactionTypeLabel(t.transaction_type)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        <span
                          className={
                            "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold " +
                            (isIn
                              ? "bg-emerald-500/15 text-emerald-700"
                              : "bg-rose-500/15 text-rose-700")
                          }
                        >
                          {isIn ? "IN" : "OUT"}
                        </span>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {counterpartyDisplay(t)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right font-mono tabular-nums">
                        {isIn ? "+" : "−"}
                        {isPoints ? (
                          <Points amount={t.amount} />
                        ) : (
                          <Money amount={t.amount} currency={t.currency} />
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right font-mono tabular-nums text-muted-foreground">
                        {/* Service charge only applies to financial (non-points) debits. */}
                        {!isPoints && parseFloat(t.fee_amount) > 0 ? (
                          <Money amount={t.fee_amount} currency={t.currency} />
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {t.currency}
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-[11px] text-muted-foreground">
                        {t.reference ?? shortId(t.id, "txn")}
                      </TableCell>
                      <TableCell>
                        <StatusPill status={t.status.toUpperCase()} variant="dense" />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </Section>
    </div>
  );
}
