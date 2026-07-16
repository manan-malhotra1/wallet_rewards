/**
 * Root layout for the mobile-simulator. No nav, no auth — this is a
 * dev tool that opens straight onto the wallet page.
 */
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sasai Mobile Simulator",
  description: "Local-dev simulator for the Sasai Wallet mobile app.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      {/* Sasai brand navy field; the wallet/header cards sit on top as white. */}
      <body style={{ backgroundColor: "#144989", minHeight: "100vh" }}>
        {children}
      </body>
    </html>
  );
}
