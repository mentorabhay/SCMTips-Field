import type { Metadata } from "next";
import React from "react";
import Link from "next/link";
import "./globals.css";
import {
  Layers,
  FileText,
  Boxes,
  Lock,
  Zap,
  Activity,
  Glasses,
  LogOut,
  Building2,
  User,
} from "lucide-react";

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
      <body className="bg-slate-950 text-slate-100 antialiased min-h-screen flex">
        {/* Left Navigation Sidebar */}
        <aside className="w-64 border-r border-slate-800 bg-slate-900/90 flex flex-col justify-between shrink-0">
          <div>
            {/* Brand Header */}
            <div className="h-16 flex items-center px-6 border-b border-slate-800 gap-3">
              <div className="w-8 h-8 rounded-lg bg-sky-600 flex items-center justify-center font-bold text-white shadow-lg shadow-sky-600/30">
                F
              </div>
              <div>
                <span className="font-bold tracking-tight text-white block text-sm leading-tight">
                  SCMTIPS Field
                </span>
                <span className="text-[10px] text-sky-400 font-mono">Console Phase 1</span>
              </div>
            </div>

            {/* Navigation Links */}
            <nav className="p-4 space-y-1 text-sm">
              <Link
                href="/"
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <Layers className="w-4 h-4 text-sky-400" />
                <span>Overview (SCR1.02)</span>
              </Link>
              <Link
                href="/documents"
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <FileText className="w-4 h-4 text-emerald-400" />
                <span>Documents (SCR1.06)</span>
              </Link>
              <Link
                href="/stock"
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <Boxes className="w-4 h-4 text-purple-400" />
                <span>Stock Ledger (SCR1.10)</span>
              </Link>
              <Link
                href="/locks"
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <Lock className="w-4 h-4 text-amber-400" />
                <span>Locks & Numbers (SCR1.09)</span>
              </Link>
              <Link
                href="/faults"
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <Zap className="w-4 h-4 text-rose-400" />
                <span>Fault Rules (SCR1.08)</span>
              </Link>
              <Link
                href="/status"
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-300 hover:text-white hover:bg-slate-800 transition-colors"
              >
                <Activity className="w-4 h-4 text-teal-400" />
                <span>System Status (SCR1.05)</span>
              </Link>
              <Link
                href="/hud"
                className="flex items-center gap-3 px-3 py-2 rounded-lg text-emerald-400 bg-emerald-950/40 border border-emerald-800/50 hover:bg-emerald-900/50 transition-colors mt-2"
              >
                <Glasses className="w-4 h-4 text-emerald-300" />
                <span className="font-medium">HUD Simulator</span>
              </Link>
            </nav>
          </div>

          {/* Footer User & Tenant Info */}
          <div className="p-4 border-t border-slate-800 space-y-3 text-xs">
            <div className="flex items-center gap-2 text-slate-400">
              <Building2 className="w-3.5 h-3.5 text-slate-500" />
              <span className="truncate">Corp Logistics (WH1)</span>
            </div>
            <div className="flex items-center justify-between text-slate-400">
              <div className="flex items-center gap-2">
                <User className="w-3.5 h-3.5 text-slate-500" />
                <span>operator-1</span>
              </div>
              <Link
                href="/login"
                className="text-slate-400 hover:text-rose-400 transition-colors"
                title="Sign out"
              >
                <LogOut className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
        </aside>

        {/* Main Content Pane */}
        <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
          {/* Header Bar */}
          <header className="h-16 border-b border-slate-800 bg-slate-900/50 px-8 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3 text-xs text-slate-400">
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-950 border border-emerald-700/60 text-emerald-300">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                Add-on Enabled
              </span>
              <span>•</span>
              <span>Core P13 Auth Active</span>
              <span>•</span>
              <span>RLS Fail-Closed</span>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-slate-400">Target ERP:</span>
              <span className="font-mono text-sky-400 bg-slate-800 px-2 py-1 rounded">
                erp-sim :8002
              </span>
            </div>
          </header>

          <main className="flex-1 p-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
