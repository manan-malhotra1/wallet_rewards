/**
 * Root layout — fonts, theme provider, toast viewport. Wraps every route.
 */
import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { Suspense } from "react";

import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
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
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans antialiased">
        {/* next-themes injects `.dark` on <html>; globals.css token block
            overrides on that class. `system` follows the OS preference;
            users can override per-session via a toggle (future). */}
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          <Toaster>
            <Suspense>{children}</Suspense>
          </Toaster>
        </ThemeProvider>
      </body>
    </html>
  );
}
