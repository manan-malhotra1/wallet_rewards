/**
 * Root route — just redirect into the dashboard. Middleware will route
 * unauthenticated browsers to /login.
 */
import { redirect } from "next/navigation";

export default function RootPage() {
  redirect("/dashboard");
}
