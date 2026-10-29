"use client";

import React, { useState } from "react";
import { AlertCircle, CheckCircle, ShieldAlert, FileText } from "lucide-react";

interface DiscrepancyRecord {
  id: string;
  docNo: string;
  materialId: string;
  expectedQty: number;
  actualQty: number;
  reasonCode: string;
  varianceVal: number;
  status: "open" | "approved" | "investigating";
}

const SAMPLE_DISCREPANCIES: DiscrepancyRecord[] = [
  {
    id: "DISC-001",
    docNo: "IBD-18000100",
    materialId: "MAT-BOLT-HEX",
    expectedQty: 100,
    actualQty: 80,
    reasonCode: "short_shipped",
    varianceVal: 450.0,
    status: "open",
  },
  {
    id: "DISC-002",
    docNo: "PID-10000002",
    materialId: "MAT-CABLE-FIBER",
    expectedQty: 20,
    actualQty: 18,
    reasonCode: "inventory_loss",
    varianceVal: 1800.0,
    status: "investigating",
  },
];

export default function DiscrepanciesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <ShieldAlert className="h-6 w-6 text-amber-400" />
          Warehouse Discrepancies & Variances (SCR3.02 / T3.057)
        </h1>
        <p className="text-sm text-slate-400">
          Root-cause discrepancy investigations, over/under delivery cases, and late-receipt signals.
        </p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-left text-sm text-slate-300">
          <thead className="bg-slate-950 text-slate-400 text-xs uppercase">
            <tr>
              <th className="px-4 py-3">Case ID</th>
              <th className="px-4 py-3">Document</th>
              <th className="px-4 py-3">Material</th>
              <th className="px-4 py-3">Expected</th>
              <th className="px-4 py-3">Actual</th>
              <th className="px-4 py-3">Reason Code</th>
              <th className="px-4 py-3">Variance Value</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {SAMPLE_DISCREPANCIES.map((row) => (
              <tr key={row.id} className="hover:bg-slate-800/50">
                <td className="px-4 py-3 font-mono font-medium text-white">{row.id}</td>
                <td className="px-4 py-3 font-mono text-sky-400">{row.docNo}</td>
                <td className="px-4 py-3">{row.materialId}</td>
                <td className="px-4 py-3">{row.expectedQty}</td>
                <td className="px-4 py-3">{row.actualQty}</td>
                <td className="px-4 py-3 font-mono text-xs text-amber-300">{row.reasonCode}</td>
                <td className="px-4 py-3">${row.varianceVal.toFixed(2)}</td>
                <td className="px-4 py-3">
                  <span className="px-2 py-0.5 rounded text-xs bg-amber-950 text-amber-400 border border-amber-800">
                    {row.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
