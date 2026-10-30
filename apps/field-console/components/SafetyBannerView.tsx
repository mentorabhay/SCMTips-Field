"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/api";
import { api } from "@/lib/client";
import type { SafetyBanner } from "@/lib/views/safety";
import { Button, cx } from "./ui";

/**
 * One person on a structure. Alerts (unacknowledged escalations) are role="alert"; the Sites view
 * offers Acknowledge (POST /v1/safety/visits/{id}/ack), the home view links to Sites.
 */
export function SafetyBannerView({
  banner,
  mode,
  onAcked,
}: {
  banner: SafetyBanner;
  mode: "link" | "ack";
  onAcked?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const alert = banner.tone === "alert";

  async function ack() {
    setBusy(true);
    setError(null);
    try {
      await api.acknowledgeVisit(banner.visitId, "Acknowledged in the console");
      setDone(true);
      onAcked?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.title : "Could not acknowledge.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role={alert ? "alert" : undefined}
      className={cx(
        "flex flex-wrap items-center gap-3 rounded-card border-2 px-4 py-3.5",
        alert ? "border-alert-line bg-alert-bg" : "border-warn-line bg-warn-bg",
      )}
    >
      <div className={cx("min-w-0 flex-[1_1_300px]", alert ? "text-alert-ink" : "text-ink")}>
        <b>{banner.headline}</b>
        <span> · {banner.body}</span>
        {error ? <div className="mt-1 font-bold text-alert-ink">{error}</div> : null}
        {done ? <div role="status" className="mt-1 font-bold">Acknowledged. The escalation is recorded with your name.</div> : null}
      </div>
      {mode === "ack" && banner.needsAck && !done ? (
        <Button variant="dark" onClick={ack} disabled={busy}>
          {busy ? "Acknowledging…" : "Acknowledge"}
        </Button>
      ) : null}
      {mode === "link" ? (
        <Link
          href="/sites"
          className="inline-flex min-h-[44px] items-center rounded-md bg-ink px-4 font-bold text-white no-underline hover:bg-black hover:text-white"
        >
          {banner.needsAck ? "Acknowledge in Sites and towers" : "Open lone-worker monitor"}
        </Link>
      ) : null}
    </div>
  );
}
