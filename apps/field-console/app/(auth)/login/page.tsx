"use client";

import React, { useState } from "react";
import Link from "next/link";
import { LogIn, ShieldCheck, AlertCircle, ArrowRight } from "lucide-react";

export default function LoginPage() {
  const [errorMode, setErrorMode] = useState<string | null>(null);

  const handleCoreRedirect = () => {
    // In production, redirects to https://core.scmtips.internal/login?redirect_uri=...
    // In local dev, redirects to dashboard with session token
    window.location.href = "/";
  };

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col justify-center items-center p-4">
      <div className="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-8 shadow-2xl space-y-6">
        {/* Brand */}
        <div className="text-center space-y-2">
          <div className="w-12 h-12 bg-sky-600 rounded-xl flex items-center justify-center font-bold text-white text-xl mx-auto shadow-lg shadow-sky-600/30">
            F
          </div>
          <h1 className="text-xl font-bold text-white">SCMTIPS Field Console</h1>
          <p className="text-xs text-slate-400">
            Single Sign-On through SCMTips Core Identity Provider (SCR1.01 / D1.05)
          </p>
        </div>

        {/* Error Simulation Banners */}
        {errorMode === "MSG1.13" && (
          <div className="p-3 bg-red-950/60 border border-red-800/80 rounded-lg flex items-start gap-2.5 text-xs text-red-300">
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
            <span>
              We could not reach SCMTIPS sign-in. Check your connection and try again. (MSG1.13)
            </span>
          </div>
        )}
        {errorMode === "MSG1.14" && (
          <div className="p-3 bg-amber-950/60 border border-amber-800/80 rounded-lg flex items-start gap-2.5 text-xs text-amber-300">
            <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <span>
              Sign-in did not complete. Close this tab, sign in to SCMTIPS again, then reopen Field. (MSG1.14)
            </span>
          </div>
        )}

        {/* Sign In Action Button */}
        <div className="space-y-3">
          <button
            onClick={handleCoreRedirect}
            className="w-full py-3 px-4 bg-sky-600 hover:bg-sky-500 text-white text-sm font-semibold rounded-xl flex items-center justify-center gap-2 shadow-lg shadow-sky-600/20 transition-all hover:scale-[1.01]"
          >
            <LogIn className="w-4 h-4" />
            Sign In with SCMTips Core
            <ArrowRight className="w-4 h-4 ml-1" />
          </button>
          <div className="flex items-center justify-center gap-1.5 text-[11px] text-slate-500">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
            <span>Ed25519 Token Exchange • Zero Console Passwords</span>
          </div>
        </div>

        {/* Test Scenario Simulators */}
        <div className="pt-4 border-t border-slate-800 text-[11px] text-slate-500 space-y-1">
          <span className="block text-slate-400">Test Auth Failure Responses:</span>
          <div className="flex gap-2">
            <button
              onClick={() => setErrorMode("MSG1.13")}
              className="text-sky-400 hover:underline"
            >
              Simulate MSG1.13 (Unreachable)
            </button>
            <span>•</span>
            <button
              onClick={() => setErrorMode("MSG1.14")}
              className="text-sky-400 hover:underline"
            >
              Simulate MSG1.14 (Incomplete)
            </button>
            <span>•</span>
            <button
              onClick={() => setErrorMode(null)}
              className="text-slate-400 hover:underline"
            >
              Clear
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
