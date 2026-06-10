import type { Metadata } from "next";
import "mapbox-gl/dist/mapbox-gl.css";
import "./globals.css";
import { AppProviders } from "./providers";

export const metadata: Metadata = {
  title: "EconomicBridge — AI & Satellite Intelligence for Agriculture, Food Security & Aid Delivery",
  description:
    "Multi-tenant platform combining satellite imagery, AI, and economic data for agriculture, food security, farmland protection, and humanitarian aid delivery across West Africa.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/*
          App-Router root layout is the correct place for a global font <link>.
          We deliberately avoid next/font here: it fetches Google Fonts at BUILD
          time, which would couple the Docker/CI build to network access. The
          runtime <link> keeps the build hermetic.
        */}
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Playfair+Display:wght@400;700;900&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
