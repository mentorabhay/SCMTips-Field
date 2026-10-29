"use client";

import React from "react";
import { ShieldCheck } from "lucide-react";

export default function ApprovalsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <ShieldCheck className="h-6 w-6 text-emerald-400" />
          Variance Approvals Gate (SCR3.05 / T3.060)
        </h1>
        <p className="text-sm text-slate-400">
          Dual approval workflow for physical inventory discrepancies exceeding threshold (PR3.05).
        </p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-2">Pending Supervisor Decisions</h2>
        <p className="text-sm text-slate-400">
          Enforces strict segregation of duties: counters cannot approve their own counted variances.
        </p>
      </div>
    </div>
  );
}
