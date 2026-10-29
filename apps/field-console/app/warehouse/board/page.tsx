"use client";

import React, { useState } from "react";
import { LayoutDashboard, CheckCircle2, Clock, AlertTriangle, Truck } from "lucide-react";

interface WarehouseTask {
  id: string;
  type: "inbound" | "picking" | "inventory";
  docNo: string;
  assignedOperator: string;
  status: "pending" | "in_progress" | "completed";
  linesCount: number;
}

const SAMPLE_TASKS: WarehouseTask[] = [
  { id: "TSK-01", type: "inbound", docNo: "IBD-18000100", assignedOperator: "operator.john", status: "in_progress", linesCount: 8 },
  { id: "TSK-02", type: "picking", docNo: "OBD-80000450", assignedOperator: "operator.alice", status: "pending", linesCount: 14 },
  { id: "TSK-03", type: "inventory", docNo: "PID-10000001", assignedOperator: "operator.bob", status: "completed", linesCount: 5 },
];

export default function WarehouseBoardPage() {
  const [filter, setFilter] = useState<string>("all");

  const filtered = SAMPLE_TASKS.filter(
    (t) => filter === "all" || t.type === filter || t.status === filter
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <LayoutDashboard className="h-6 w-6 text-sky-400" />
            Warehouse Operations Board (SCR3.01 / T3.056)
          </h1>
          <p className="text-sm text-slate-400">
            Real-time supervisor dispatch board for inbound receiving, wave picking, and cycle counts.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-slate-400 text-xs font-semibold uppercase">Active Inbound Waves</div>
          <div className="text-2xl font-bold text-white mt-1">4</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-slate-400 text-xs font-semibold uppercase">Open Pick Tours</div>
          <div className="text-2xl font-bold text-amber-400 mt-1">12</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-slate-400 text-xs font-semibold uppercase">Cycle Counts Due</div>
          <div className="text-2xl font-bold text-sky-400 mt-1">6</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <div className="text-slate-400 text-xs font-semibold uppercase">Lines Completed Today</div>
          <div className="text-2xl font-bold text-emerald-400 mt-1">342</div>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <span className="font-semibold text-white">Live Operations Queue</span>
          <div className="flex gap-2">
            <button
              onClick={() => setFilter("all")}
              className={`px-3 py-1 rounded text-xs ${filter === "all" ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-400"}`}
            >
              All
            </button>
            <button
              onClick={() => setFilter("inbound")}
              className={`px-3 py-1 rounded text-xs ${filter === "inbound" ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-400"}`}
            >
              Inbound
            </button>
            <button
              onClick={() => setFilter("picking")}
              className={`px-3 py-1 rounded text-xs ${filter === "picking" ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-400"}`}
            >
              Picking
            </button>
          </div>
        </div>

        <table className="w-full text-left text-sm text-slate-300">
          <thead className="bg-slate-950 text-slate-400 text-xs uppercase">
            <tr>
              <th className="px-4 py-3">Task ID</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Reference Doc</th>
              <th className="px-4 py-3">Operator</th>
              <th className="px-4 py-3">Lines</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {filtered.map((task) => (
              <tr key={task.id} className="hover:bg-slate-800/50">
                <td className="px-4 py-3 font-mono font-medium text-white">{task.id}</td>
                <td className="px-4 py-3 capitalize">{task.type}</td>
                <td className="px-4 py-3 font-mono text-sky-400">{task.docNo}</td>
                <td className="px-4 py-3">{task.assignedOperator}</td>
                <td className="px-4 py-3">{task.linesCount}</td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-0.5 rounded text-xs ${
                      task.status === "completed"
                        ? "bg-emerald-950 text-emerald-400 border border-emerald-800"
                        : task.status === "in_progress"
                        ? "bg-amber-950 text-amber-400 border border-amber-800"
                        : "bg-slate-800 text-slate-400 border border-slate-700"
                    }`}
                  >
                    {task.status}
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
