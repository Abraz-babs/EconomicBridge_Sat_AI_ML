import type { NextConfig } from "next";
import path from "path";
import dotenv from "dotenv";

// Load the project-root .env (single source of truth across all services).
// This runs BEFORE Next.js reads `process.env.NEXT_PUBLIC_*`, so the vars
// are available to both the build and the dev server.
dotenv.config({ path: path.resolve(__dirname, "../../.env"), quiet: true });

const nextConfig: NextConfig = {
  // Emit a self-contained `.next/standalone` server bundle. The Dockerfile's
  // runner stage copies that directory + `.next/static` + `public/` and runs
  // `node server.js`, so no `node_modules` ship to production.
  output: "standalone",

  // ─── SECURITY HEADERS ───
  // Production-grade headers: CSP, HSTS, frame protection, XSS protection
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "X-DNS-Prefetch-Control",
            value: "on",
          },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          {
            key: "X-Frame-Options",
            value: "SAMEORIGIN",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(self), interest-cohort=()",
          },
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "worker-src 'self' blob:",
              "child-src 'self' blob:",
              "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://api.mapbox.com",
              "font-src 'self' https://fonts.gstatic.com",
              "img-src 'self' data: blob: https:",
              [
                "connect-src 'self'",
                // Backend API (dev — uvicorn on localhost:8000). In production
                // this becomes the deployed API origin via NEXT_PUBLIC_API_BASE_URL.
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "https://api.mapbox.com",
                "https://events.mapbox.com",
                "https://*.tiles.mapbox.com",
                "https://scihub.copernicus.eu",
                "https://firms.modaps.eosdis.nasa.gov",
                "https://api.n2yo.com",
              ].join(" "),
              "frame-ancestors 'self'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },

  // ─── PERFORMANCE ───
  poweredByHeader: false, // Remove X-Powered-By header
  compress: true,

  // ─── IMAGE OPTIMIZATION ───
  images: {
    formats: ["image/avif", "image/webp"],
    remotePatterns: [
      { protocol: "https", hostname: "scihub.copernicus.eu" },
      { protocol: "https", hostname: "firms.modaps.eosdis.nasa.gov" },
    ],
  },
};

export default nextConfig;
