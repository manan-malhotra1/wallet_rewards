/**
 * Root layout. Wraps every route. Loads fonts, sets html lang, mounts the
 * AppShell at this level so navigation persists across route transitions.
 */
import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { Suspense } from "react";

import "./globals.css";
import { Toaster } from "@/components/ui/toast";

export const metadata: Metadata = {
  title: "Sasai Wallet · Admin",
  description: "Operations console for the Sasai Wallet & Rewards Platform",
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      // Dark by default; light only when the user's OS opts in (media query
      // in globals.css handles the actual variable swap).
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <body>
        {/* Toaster owns the React context provider for `useToast()` and
            also renders the floating viewport. It MUST wrap children so
            descendants find the provider in the tree. */}
        <Toaster>
          <Suspense>{children}</Suspense>
        </Toaster>
      </body>
    </html>
  );
}
