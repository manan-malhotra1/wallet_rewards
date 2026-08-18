/**
 * The Counterparty column of the user Transactions table — who was on the
 * other side of a transaction, never what service carried it.
 */
import type { UserTransaction } from "@/lib/api-endpoints";

/**
 * Names the system or provider account behind transaction types whose other
 * leg has no owning user, so the column reads as a real counterparty rather
 * than an empty cell. Types absent here (p2p, merchant_cashin, cash_in,
 * cashout) always transact user-to-user, so the backend resolves a real name
 * and no label is needed.
 */
const SYSTEM_COUNTERPARTY_LABEL: Record<string, string> = {
  withdraw: "Operator float",
  airtime_recharge: "Airtime merchant",
  redemption: "Redemption provider",
  reward_issuance: "Rewards engine",
  fund: "System cash inflow",
  treasury_adjust: "Operator adjustment",
};

/**
 * Render the other party in a transaction: their name on the primary line and
 * their phone number beneath it.
 *
 * Falls back to a label naming the system/provider account when there is no
 * owning user (a fund comes from the cash float, a redemption from a
 * provider). Never falls back to the service name — that is its own column,
 * and repeating it here would read as if the user transacted with the service.
 */
export function CounterpartyCell({ txn }: { txn: UserTransaction }) {
  const name = txn.counterparty_name ?? SYSTEM_COUNTERPARTY_LABEL[txn.transaction_type];
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
