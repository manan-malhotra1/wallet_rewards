/**
 * Legacy User-approvals route. The three approval queues were unified into
 * `/approvals` (role-gated tabs). This route is kept as a thin redirect so old
 * links / bookmarks land on the Users tab.
 */
import { redirect } from "next/navigation";

export default function UserOperationsRedirect() {
  redirect("/approvals?tab=users");
}
