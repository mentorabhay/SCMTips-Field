import React from "react";
import { ConsoleShell } from "@/components/ConsoleShell";

/** Warehouse console pages (SCR3.01-SCR3.05) share the console shell and live data. */
export default function WarehouseLayout({ children }: { children: React.ReactNode }) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
