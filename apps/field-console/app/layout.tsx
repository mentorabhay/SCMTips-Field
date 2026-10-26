import type { Metadata } from "next";
import React from "react";

export const metadata: Metadata = {
  title: "SCMTIPS Field Console",
  description: "Operations & Governance Console for SCMTIPS Field",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-900 text-slate-100 antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
