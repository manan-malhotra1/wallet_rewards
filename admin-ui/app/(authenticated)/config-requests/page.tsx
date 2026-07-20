/**
 * Legacy Configuration-approvals route. The three approval queues were unified
 * into `/approvals` (role-gated tabs). This route is kept as a thin redirect so
 * old links / bookmarks land on the Configuration tab.
 */
import { redirect } from "next/navigation";

export default function ConfigRequestsRedirect() {
  redirect("/approvals?tab=configuration");
}
