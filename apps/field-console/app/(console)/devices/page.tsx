"use client";

import React, { useState } from "react";
import { ApiError } from "@/lib/api";
import { api } from "@/lib/client";
import { buildDeviceRows, MSG2_19, type DeviceRow, type SeenTone } from "@/lib/views/devices";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { NEEDS, useLive, useSession } from "@/components/session";
import { useNow } from "@/components/usePoll";
import { EmptyState, Freshness, PageHeader, PollView } from "@/components/ui";

const SEEN_TONE: Record<SeenTone, string> = { ok: "text-ok-ink", stale: "font-bold text-warn-ink", off: "text-muted" };

export default function DevicesPage() {
  const live = useLive();
  const { can } = useSession();
  const now = useNow(15000);
  const [target, setTarget] = useState<DeviceRow | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const canRevoke = can("field.device.revoke");

  async function revoke() {
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await api.revokeDevice(target.id, reason.trim() || "Revoked in the console");
      setDone(`${target.name}: ${MSG2_19}`);
      setTarget(null);
      void live.refresh.devices();
    } catch (e) {
      setError(e instanceof ApiError ? e.title : "The device was not revoked.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Phones and glasses" lead="Lost or broken? Revoke it and it stops working at once.">
        <Freshness state={live.devices} />
      </PageHeader>
      {done ? (
        <p role="status" className="m-0 rounded-card border border-line bg-ok-bg px-4 py-3 font-bold text-ok-ink">
          {done}
        </p>
      ) : null}
      <PollView
        state={live.devices}
        role={NEEDS.devices.role}
        onRetry={live.refresh.devices}
        isEmpty={(d) => d.length === 0}
        empty={<EmptyState title="No phones or glasses yet" body="A phone appears here after it is paired with the QR code from the dev stack." />}
      >
        {(devices) => {
          const rows = buildDeviceRows(devices, now);
          return (
            <div className="overflow-x-auto rounded-card border border-line bg-card">
              <table className="w-full min-w-[760px] border-collapse text-left text-[15px]">
                <caption className="sr-only">Registered phones and glasses</caption>
                <thead className="bg-soft text-[13px] text-muted">
                  <tr className="border-b border-line">
                    <th scope="col" className="px-3.5 py-2.5">Device</th>
                    <th scope="col" className="px-3.5 py-2.5">Paired with</th>
                    <th scope="col" className="px-3.5 py-2.5">Last seen</th>
                    <th scope="col" className="px-3.5 py-2.5">Battery</th>
                    <th scope="col" className="px-3.5 py-2.5">Waiting to send</th>
                    <th scope="col" className="px-3.5 py-2.5"><span className="sr-only">Action</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => (
                    <tr key={d.id} className="border-b border-line-soft last:border-b-0">
                      <td className="px-3.5 py-2.5">
                        <b>{d.name}</b>
                        <div className="text-[13px] text-muted">
                          {d.serial}
                          {d.versions ? ` · ${d.versions}` : ""}
                        </div>
                      </td>
                      <td className="px-3.5 py-2.5">{d.paired}</td>
                      <td className={`px-3.5 py-2.5 ${SEEN_TONE[d.seenTone]}`}>
                        {d.seen}
                        {d.seenTone === "stale" ? <span className="block text-[13px] font-normal">Not seen for 15 min</span> : null}
                      </td>
                      <td className="px-3.5 py-2.5">{d.battery}</td>
                      <td className="px-3.5 py-2.5">{d.queue}</td>
                      <td className="px-3.5 py-1.5">
                        {d.revoked ? (
                          <span className="text-sm text-muted">Revoked</span>
                        ) : canRevoke ? (
                          <button
                            type="button"
                            onClick={() => {
                              setTarget(d);
                              setReason("");
                              setError(null);
                              setDone(null);
                            }}
                            className="min-h-[40px] rounded-md border border-control bg-card px-3 py-2 font-bold text-warn-ink hover:bg-warn-bg"
                            aria-label={`Revoke ${d.name}, serial ${d.serial}`}
                          >
                            Revoke
                          </button>
                        ) : (
                          <span className="text-sm text-muted">Revoke needs the Supervisor role</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </PollView>
      <ConfirmDialog
        open={target !== null}
        title={target ? `Revoke ${target.name}?` : "Revoke device?"}
        confirmLabel="Revoke"
        busy={busy}
        error={error}
        onCancel={() => setTarget(null)}
        onConfirm={revoke}
      >
        <p className="m-0">
          Serial <b className="font-mono">{target?.serial}</b>. It stops working at once and must be paired again to be used.
          Unsent items stay locked on the device for 72 hours.
        </p>
        <label htmlFor="revoke-reason" className="font-bold">
          Reason (optional)
        </label>
        <input
          id="revoke-reason"
          maxLength={200}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Lost, broken, left the company…"
          className="min-h-[44px] rounded-md border border-control bg-card px-3"
        />
      </ConfirmDialog>
    </>
  );
}
