import React from "react";
import Link from "next/link";
import { HelpCircle, ArrowLeft } from "lucide-react";

export default function NotFound() {
  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center p-6 text-center space-y-4">
      <div className="w-12 h-12 rounded-full bg-slate-800 flex items-center justify-center text-slate-400">
        <HelpCircle className="w-6 h-6" />
      </div>
      <h2 className="text-xl font-bold text-white">404 - Resource Not Found</h2>
      <p className="text-xs text-slate-400 max-w-sm">
        The requested screen or document does not exist in this field operations site.
      </p>
      <Link
        href="/"
        className="inline-flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold rounded-lg shadow"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Return to Overview
      </Link>
    </div>
  );
}
