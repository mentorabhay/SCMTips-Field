"use client";

// T3.056 / SCR3.01: Warehouse Operations Board on live GET /v1/tasks (receive, put away, pick, count).
import { LiveBoardView } from "@/components/LiveBoardView";
import { WarehouseTabs } from "../tabs";

export default function WarehouseBoardPage() {
  return (
    <>
      <WarehouseTabs />
      <LiveBoardView
        title="Warehouse Operations Board"
        lead="Receipts, put-aways, picks and counts as people scan them. Blocked cards say why."
        types={["receive", "putaway", "pick", "count"]}
        emptyBody="Run `stack delivery`, `stack outbound` or `stack count` on the dev stack to create warehouse jobs."
      />
    </>
  );
}
