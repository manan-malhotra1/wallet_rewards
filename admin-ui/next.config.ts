/**
 * Next.js 16 configuration for the Sasai Wallet admin UI.
 *
 * `serverActions` is on by default in App Router. We don't expose
 * `BACKEND_URL` to the browser — only server components and route handlers
 * can reach it.
 */
import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  experimental: {
    serverActions: {
      // 1MB is plenty for our admin forms; rejects accidental payloads earlier.
      bodySizeLimit: "1mb",
    },
  },
};

export default config;
