"use client";

// T3.057 / SCR3.02: Warehouse Discrepancies workbench on live GET /v1/approval-requests?status=pending.
import { DecisionsView } from "@/components/DecisionsView";
import { WarehouseTabs } from "../tabs";

export default function WarehouseDiscrepanciesPage() {
  return (
    <>
      <WarehouseTabs />
      <DecisionsView
        title="Warehouse Discrepancies"
        lead="Count differences beyond tolerance. Recount, approve the difference, or reject. Whoever counted a bin cannot approve it."
        only="approvals"
      />
    </>
  );
}
