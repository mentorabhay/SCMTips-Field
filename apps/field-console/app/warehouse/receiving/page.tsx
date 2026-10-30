"use client";

// T3.058 / SCR3.03: Inbound Receiving Console on live GET /v1/tasks (receive and the put-aways it creates).
import { LiveBoardView } from "@/components/LiveBoardView";
import { WarehouseTabs } from "../tabs";

export default function WarehouseReceivingPage() {
  return (
    <>
      <WarehouseTabs />
      <LiveBoardView
        title="Inbound Receiving Console"
        lead="Each delivery posts goods receipt 101 to SAP when the last item is confirmed, then a put-away job appears."
        types={["receive", "putaway"]}
        emptyBody="Run `stack delivery` on the dev stack to send an inbound delivery."
      />
    </>
  );
}
