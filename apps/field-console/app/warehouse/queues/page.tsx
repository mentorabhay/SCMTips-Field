"use client";

// T3.060 / SCR3.05: posting queues on live GET /v1/posting-queues.
import { PostingsView } from "@/components/PostingsView";
import { WarehouseTabs } from "../tabs";

export default function WarehouseQueuesPage() {
  return (
    <>
      <WarehouseTabs />
      <PostingsView
        title="Posting queues"
        lead="Goods receipts (101), issues (601) and count postings (701/702) go to SAP once each, in order."
      />
    </>
  );
}
