"use client";

import React from "react";
import { AlertTriangle, RotateCcw } from "lucide-react";

export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center p-6 text-center space-y-4">
      <div className="w-12 h-12 rounded-full bg-rose-950/80 border border-rose-700 flex items-center justify-center text-rose-400">
        <AlertTriangle className="w-6 h-6" />
      </div>
      <h2 className="text-xl font-bold text-white">Application Exception</h2>
      <p className="text-xs text-slate-400 max-w-md font-mono bg-slate-900 p-3 rounded border border-slate-800">
        {error.message || "An unexpected error occurred while rendering the console."}
      </p>
      <button
        onClick={() => reset()}
        className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg border border-slate-700"
      >
        <RotateCcw className="w-3.5 h-3.5" />
        Retry View
      </button>
    </div>
  );
}
