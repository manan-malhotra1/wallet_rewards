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
 * Where the viewer is a THIRD PARTY — a supervisor earning parent commission
 * from a transaction between two other people — a single name cannot express
 * what happened, so the cell renders sender → receiver instead.
 *
 * Never falls back to the service name — that is its own column, and repeating
 * it here would read as if the user transacted with the service.
 */
export function CounterpartyCell({ txn }: { txn: UserTransaction }) {
  // A transaction the viewer is not a party to cannot be described by one
  // name: a supervisor earns from their agent paying a customer, and is
  // neither side. The backend fills these only in that case.
  if (txn.sender_name || txn.receiver_name) {
    return (
      <div className="flex flex-col leading-tight">
        <span>
          {txn.sender_name ?? "—"}
          <span className="mx-1 text-muted-foreground" aria-label="to">
            →
          </span>
          {txn.receiver_name ?? "—"}
        </span>
        <span className="text-[11px] text-muted-foreground">
          You earned from this
        </span>
      </div>
    );
  }

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
