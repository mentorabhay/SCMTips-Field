"use client";

// T3.059 / SCR3.04: Inventory Accuracy from live count jobs and pending count approvals.
import React from "react";
import { EmptyState, Freshness, PageHeader, PollView } from "@/components/ui";
import { NEEDS, useLive } from "@/components/session";
import { dataOf } from "@/components/usePoll";
import { buildAccuracy, percent } from "@/lib/views/accuracy";
import { WarehouseTabs } from "../tabs";

export default function WarehouseAccuracyPage() {
  const live = useLive();
  const approvals = dataOf(live.approvals) ?? [];
  return (
    <>
      <WarehouseTabs />
      <PageHeader
        title="Inventory Accuracy"
        lead="Counted bins against differences waiting for a decision. Small differences inside tolerance post straight to SAP and are not shown here."
      >
        <Freshness state={live.tasks} />
      </PageHeader>
      <PollView
        state={live.tasks}
        role={NEEDS.tasks.role}
        onRetry={live.refresh.tasks}
        isEmpty={(d) => buildAccuracy(d, approvals).countJobs === 0}
        empty={<EmptyState title="No counts yet" body="Run `stack count` on the dev stack to create a count job." />}
      >
        {(tasks) => {
          const s = buildAccuracy(tasks, approvals);
          const tiles: [string, string][] = [
            ["Bins with no open difference", percent(s.matchRate)],
            ["Bins counted", `${s.linesCounted} of ${s.linesTotal}`],
            ["Differences waiting", String(s.differencesWaiting)],
            ["Count jobs", String(s.countJobs)],
          ];
          return (
            <div className="flex flex-col gap-4">
              <dl className="m-0 grid grid-cols-2 gap-3 lg:grid-cols-4">
                {tiles.map(([k, v]) => (
                  <div key={k} className="rounded-card border border-line bg-card px-4 py-3">
                    <dt className="text-[13px] text-muted">{k}</dt>
                    <dd className="m-0 text-2xl font-bold">{v}</dd>
                  </div>
                ))}
              </dl>
              <table className="w-full border-collapse rounded-card bg-card text-left text-[15px]">
                <thead>
                  <tr className="border-b border-line">
                    <th className="px-3 py-2">Bin</th>
                    <th className="px-3 py-2">Item</th>
                    <th className="px-3 py-2">State</th>
                    <th className="px-3 py-2 text-right">Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {s.rows.map((r) => (
                    <tr key={`${r.taskId}|${r.bin}|${r.material}`} className="border-b border-line last:border-0">
                      <td className="px-3 py-2 font-bold">{r.bin}</td>
                      <td className="px-3 py-2">{r.material}</td>
                      <td className={`px-3 py-2 ${r.state === "difference waiting" || r.state === "flagged" ? "font-bold text-warn-ink" : ""}`}>
                        {r.state}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {r.difference === null ? "" : `${r.difference > 0 ? "+" : ""}${r.difference}${r.uom ? ` ${r.uom}` : ""}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </PollView>
    </>
  );
}
