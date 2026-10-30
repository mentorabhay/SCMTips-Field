import type { Metadata, Viewport } from "next";
import React from "react";
import "./globals.css";
import { SessionProvider } from "@/components/session";

export const metadata: Metadata = {
  title: "SCMTips Field console",
  description: "Supervisor console for SCMTips Field: live work, decisions, postings to SAP, devices and safety.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-page font-sans text-ink antialiased">
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
