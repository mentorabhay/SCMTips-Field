"use client";

// T3.060 / SCR3.05: inventory count jobs on live GET /v1/tasks?type=count.
import { LiveBoardView } from "@/components/LiveBoardView";
import { WarehouseTabs } from "../tabs";

export default function WarehouseInventoryPage() {
  return (
    <>
      <WarehouseTabs />
      <LiveBoardView
        title="Inventory counts"
        lead="Blind counts: the counter never sees the book quantity. Differences beyond tolerance go to Discrepancies."
        types={["count"]}
        emptyBody="Run `stack count` on the dev stack to create a count job."
      />
    </>
  );
}
