import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Pin Turbopack's workspace root to this package — the user's $HOME has a
  // stray package-lock.json that Next would otherwise pick up.
  turbopack: { root: __dirname },
  experimental: { serverActions: { bodySizeLimit: "1mb" } },
};

export default nextConfig;
