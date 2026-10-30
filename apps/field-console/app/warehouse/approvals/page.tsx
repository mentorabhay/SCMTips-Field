"use client";

// T3.060 / SCR3.05: count approvals (same live source as Discrepancies, approve/recount/reject).
import { DecisionsView } from "@/components/DecisionsView";
import { WarehouseTabs } from "../tabs";

export default function WarehouseApprovalsPage() {
  return (
    <>
      <WarehouseTabs />
      <DecisionsView
        title="Count approvals"
        lead="Differences waiting for a supervisor. Approving posts 701 or 702 to SAP."
        only="approvals"
      />
    </>
  );
}
