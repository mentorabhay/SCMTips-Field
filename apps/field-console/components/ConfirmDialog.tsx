"use client";

import React, { useEffect, useId, useRef } from "react";
import { Button } from "./ui";

/**
 * Modal confirm on the native <dialog> element: showModal() traps focus and Esc cancels.
 * The confirm button is not the default focus, so Enter does not destroy anything by accident.
 */
export function ConfirmDialog({
  open,
  title,
  confirmLabel,
  busy,
  error,
  onConfirm,
  onCancel,
  children,
}: {
  open: boolean;
  title: string;
  confirmLabel: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onCancel();
      }}
      className="w-[min(92vw,480px)] rounded-card border border-line bg-card p-0 text-ink shadow-xl backdrop:bg-black/40"
    >
      <div className="flex flex-col gap-4 p-5">
        <h2 id={titleId} className="m-0 text-xl font-bold">
          {title}
        </h2>
        <div className="flex flex-col gap-2">{children}</div>
        {error ? (
          <p role="alert" className="m-0 rounded-md bg-alert-bg px-3 py-2 text-alert-ink">
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={busy} autoFocus>
            Cancel
          </Button>
          <Button variant="dark" onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
