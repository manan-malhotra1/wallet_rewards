/**
 * The Counterparty column of the user Transactions table — who was on the
 * other side of a transaction, never what service carried it.
 */
import type { UserTransaction } from "@/lib/api-endpoints";

/**
 * Render the other party in a transaction: their name on the primary line and
 * their phone number beneath it.
 *
 * The BACKEND resolves the label now — a person's name, else what the other
 * account IS ("Cash float", "Bank mirror · Primary", "Commission wallet").
 * This component used to keep its own per-transaction-type label map, which
 * meant every new type needed a new entry and any type nobody remembered fell
 * back to an empty cell — exactly how the commission rows regressed to "—".
 * Deriving it from the actual account removes that maintenance trap.
 *
 * Never falls back to the service name — that is its own column, and repeating
 * it here would read as if the user transacted with the service.
 */
export function CounterpartyCell({ txn }: { txn: UserTransaction }) {
  const name = txn.counterparty_name;
  // A user with no profile name resolves to their identifier, which is the
  // phone — showing it twice reads as a rendering bug.
  const phone =
    txn.counterparty_phone && txn.counterparty_phone !== name ? txn.counterparty_phone : null;

  if (!name && !phone) return <span className="text-muted-foreground">—</span>;

  return (
    <div className="flex flex-col leading-tight">
      {name ? <span>{name}</span> : null}
      {phone ? <span className="font-mono text-[11px] text-muted-foreground">{phone}</span> : null}
    </div>
  );
}
