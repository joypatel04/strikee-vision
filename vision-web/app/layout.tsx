import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import "./globals.css";

export const metadata: Metadata = {
  title: "Strikee Vision — Reconciliation",
  robots: { index: false, follow: false, nocache: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${GeistSans.className}`} suppressHydrationWarning>
      <head>
        <meta name="robots" content="noindex, nofollow, noarchive" />
      </head>
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
