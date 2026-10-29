"use client";

import React from "react";
import { BarChart3, TrendingUp, Target } from "lucide-react";

export default function AccuracyPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <BarChart3 className="h-6 w-6 text-sky-400" />
          Inventory Accuracy & Telemetry (SCR3.04 / T3.059)
        </h1>
        <p className="text-sm text-slate-400">
          IRA (Inventory Record Accuracy), cycle count compliance, and shrinkage trends.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
          <div className="text-slate-400 text-xs font-semibold uppercase">Overall IRA %</div>
          <div className="text-3xl font-bold text-emerald-400 mt-2">99.2%</div>
          <div className="text-xs text-slate-500 mt-1">Target: &gt; 98.5%</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
          <div className="text-slate-400 text-xs font-semibold uppercase">Cycle Counts On-Time</div>
          <div className="text-3xl font-bold text-sky-400 mt-2">97.8%</div>
          <div className="text-xs text-slate-500 mt-1">Target: 95.0%</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
          <div className="text-slate-400 text-xs font-semibold uppercase">Shrinkage Rate</div>
          <div className="text-3xl font-bold text-amber-400 mt-2">0.08%</div>
          <div className="text-xs text-slate-500 mt-1">Year-to-date net variance</div>
        </div>
      </div>
    </div>
  );
}
