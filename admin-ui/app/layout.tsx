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
      <body className="min-h-screen font-sans antialiased">
        {/* No bg-background here: globals.css's `body` rule paints the glass
            atmosphere (gradient over --glass-atmosphere-base); a Tailwind
            utility class here would only win the cascade by accident and
            contradict that atmosphere. */}
        {/* next-themes injects `.dark` on <html>; globals.css token block
            overrides on that class. Dark is the product default (deep navy);
            `enableSystem` is off so a viewer's OS preference never silently
            forces light. `<html suppressHydrationWarning>` above absorbs the
            class next-themes stamps pre-hydration, so there's no theme flash. */}
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
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
