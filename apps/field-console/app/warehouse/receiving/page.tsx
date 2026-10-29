"use client";

import React from "react";
import { Package, Truck, ArrowDownLeft } from "lucide-react";

export default function ReceivingConsolePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <Truck className="h-6 w-6 text-emerald-400" />
          Inbound Receiving Console (SCR3.03 / T3.058)
        </h1>
        <p className="text-sm text-slate-400">
          Inbound delivery staging, dock scheduling, handling unit check-in, and 101 Goods Receipt status.
        </p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Dock Receiving Staging</h2>
        <p className="text-sm text-slate-300">
          Dock-to-stock tracking active for Plant 1010. SSCC validation (GS1 Mod-10) enforced at point of capture.
        </p>
      </div>
    </div>
  );
}
