/**
 * <UserDetailCard> — renders the full user-detail payload.
 *
 * Three sections, in the FinOps Studio style:
 *   - Header strip: user_id, status pill, primary identifier
 *   - Identifiers + profile in a side-by-side card
 *   - Accounts table with balances
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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import type { UserDetail } from "@/lib/api-types";
import type { UserTransaction } from "@/lib/api-endpoints";
import { formatTimestamp, shortId } from "@/lib/utils";

import { ResetPinButton } from "./reset-pin-button";

const TRANSACTION_TYPE_LABEL: Record<string, string> = {
  p2p: "Peer-to-Peer",
  fund: "Fund",
  withdraw: "Withdraw",
  redemption: "Redemption",
  airtime_recharge: "Airtime Recharge",
  reward_issuance: "Reward",
  top_up: "Top up",
  treasury_adjust: "Treasury adjust",
};

const SYSTEM_COUNTERPARTY_LABEL: Record<string, string> = {
  fund: "Operator float",
  withdraw: "Operator float",
  airtime_recharge: "Airtime merchant",
  redemption: "Redemption provider",
  reward_issuance: "Rewards engine",
  top_up: "System cash inflow",
  treasury_adjust: "Operator adjustment",
};

function counterpartyDisplay(txn: UserTransaction): string {
  if (txn.counterparty_name) return txn.counterparty_name;
  return SYSTEM_COUNTERPARTY_LABEL[txn.transaction_type] ?? "—";
}

function serviceDisplay(transaction_type: string): string {
  return TRANSACTION_TYPE_LABEL[transaction_type] ?? transaction_type;
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

export interface UserDetailCardProps {
  detail: UserDetail;
  transactions: UserTransaction[];
  resolvedIdentifierValue: string | null;
  resolvedIdentifierType: string;
}

export function UserDetailCard({
  detail,
  transactions,
  resolvedIdentifierValue,
  resolvedIdentifierType,
}: UserDetailCardProps) {
  const name = fullName(detail);
  const ResolvedIcon = IDENTIFIER_ICON[resolvedIdentifierType] ?? UserCircle;

  return (
    <div className="space-y-4">
      {/* Header card */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-sky-500 text-white shadow-sm">
                <UserCircle className="h-6 w-6" />
              </div>
              <div>
                <CardTitle className="font-mono text-base">
                  {shortId(detail.id, "usr")}
                </CardTitle>
                <CardDescription>
                  {name ?? "No profile name on file"}
                </CardDescription>
              </div>
            </div>
            <div className="flex flex-col items-end gap-2">
              <StatusPill status={detail.status.toUpperCase()} variant="full" />
              <span className="text-[11px] text-muted-foreground">
                Created {formatTimestamp(detail.created_at)}
              </span>
              <ResetPinButton userId={detail.id} tenantId={detail.tenant_id} />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 rounded-md border border-primary/20 bg-primary/5 px-3 py-2">
            <ResolvedIcon className="h-4 w-4 text-primary" />
            <div className="flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Resolved by {resolvedIdentifierType}
              </p>
              <p className="font-mono text-sm text-foreground">
                {resolvedIdentifierValue ?? "—"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Identifiers + profile side-by-side */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Identifiers</CardTitle>
            <CardDescription>
              Every way this user can be referenced inside the tenant.
            </CardDescription>
          </CardHeader>
          <CardContent>
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
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Profile</CardTitle>
            <CardDescription>
              KYC fields captured during registration.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {detail.profile ? (
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    First name
                  </dt>
                  <dd className="text-foreground">
                    {detail.profile.first_name ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Last name
                  </dt>
                  <dd className="text-foreground">
                    {detail.profile.last_name ?? "—"}
                  </dd>
                </div>
                <div className="col-span-2">
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
          </CardContent>
        </Card>
      </div>

      {/* Accounts with balances */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Accounts</CardTitle>
          <CardDescription>
            Derived balances live from the ledger — no snapshot caching.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {detail.accounts.length === 0 ? (
            <p className="px-6 text-sm text-muted-foreground">
              This user has no accounts.
            </p>
          ) : (
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
                          <Money amount={acct.reserved_balance} currency={acct.currency} />
                        )}
                      </TableCell>
                      <TableCell className="text-right font-semibold">
                        {isPoints ? (
                          <Points amount={acct.available_balance} />
                        ) : (
                          <Money amount={acct.available_balance} currency={acct.currency} />
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
          )}
        </CardContent>
      </Card>

      {/* Transactions — latest 50 ledger events touching this user */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Transactions</CardTitle>
          <CardDescription>
            Latest 50 movements on this user's wallets. Service tells you what
            happened; Counterparty is who they paid or received from.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {transactions.length === 0 ? (
            <p className="px-6 text-sm text-muted-foreground">
              No transactions yet on this user's wallets.
            </p>
          ) : (
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
                        {serviceDisplay(t.transaction_type)}
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
                        {shortId(t.id, "txn")}
                      </TableCell>
                      <TableCell>
                        <StatusPill status={t.status.toUpperCase()} variant="dense" />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
