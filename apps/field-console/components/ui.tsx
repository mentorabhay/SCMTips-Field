"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import type { ApiError } from "@/lib/api";
import { useSession } from "./session";
import type { PollState } from "./usePoll";

export function cx(...c: Array<string | false | null | undefined>): string {
  return c.filter(Boolean).join(" ");
}

export function PageHeader({ title, lead, children }: { title: string; lead: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex flex-col gap-1">
        <h1 className="m-0 text-[26px] font-bold leading-tight sm:text-[30px]">{title}</h1>
        <p className="m-0 text-muted">{lead}</p>
      </div>
      {children}
    </div>
  );
}

type ButtonVariant = "primary" | "secondary" | "dark" | "danger";

const BUTTON: Record<ButtonVariant, string> = {
  primary: "border-0 bg-primary text-white hover:bg-primary-hover",
  secondary: "border border-control bg-card text-ink hover:bg-soft",
  dark: "border-0 bg-ink text-white hover:bg-black",
  danger: "border border-control bg-card text-warn-ink hover:bg-warn-bg",
};

export function Button({
  variant = "secondary",
  className,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      type="button"
      {...rest}
      className={cx(
        "inline-flex min-h-[44px] items-center justify-center rounded-md px-4 py-2 font-bold disabled:cursor-not-allowed disabled:opacity-60",
        BUTTON[variant],
        className,
      )}
    />
  );
}

export type PillTone = "warn" | "ok" | "neutral" | "alert" | "info";

const PILL: Record<PillTone, string> = {
  warn: "bg-warn-pill text-warn-pillink",
  ok: "bg-ok-bg text-ok-ink",
  neutral: "bg-pill-bg text-pill-ink",
  alert: "bg-alert-bg text-alert-ink",
  info: "bg-selected text-primary",
};

export function Pill({ tone, children }: { tone: PillTone; children: React.ReactNode }) {
  return <span className={cx("inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-[13px] font-bold", PILL[tone])}>{children}</span>;
}

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return <div className={cx("rounded-card border border-line bg-card", className)}>{children}</div>;
}

// ------------------------------------------------------------------ states

function StateBox({ tone = "plain", role, children }: { tone?: "plain" | "error"; role?: string; children: React.ReactNode }) {
  return (
    <div
      role={role}
      className={cx(
        "flex flex-col items-start gap-2 rounded-card border p-5",
        tone === "error" ? "border-alert-line bg-alert-bg text-alert-ink" : "border-line bg-card",
      )}
    >
      {children}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <StateBox role="status">
      <span className="text-muted">{label}</span>
    </StateBox>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: React.ReactNode }) {
  return (
    <StateBox>
      <b>{title}</b>
      {body ? <span className="text-muted">{body}</span> : null}
      {action}
    </StateBox>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <StateBox tone="error" role="alert">
      <b>{error.title}</b>
      {error.code ? <span className="text-sm">Code {error.code}</span> : null}
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </StateBox>
  );
}

/** SCR1.03 copy. */
export function ForbiddenState({ role }: { role: string }) {
  const { signOut } = useSession();
  return (
    <StateBox>
      <b>You do not have access to this page</b>
      <span className="text-muted">Ask a Field administrator for the role: {role}.</span>
      <Link href="/login" onClick={signOut} className="font-bold">
        Sign out
      </Link>
    </StateBox>
  );
}

/**
 * Renders a polled list: loading, error (with last good data kept), no-permission (403 or a missing
 * permission before calling), empty, or the content.
 */
export function PollView<T>({
  state,
  role,
  isEmpty,
  empty,
  onRetry,
  children,
}: {
  state: PollState<T>;
  role: string;
  isEmpty?: (d: T) => boolean;
  empty?: React.ReactNode;
  onRetry?: () => void;
  children: (d: T) => React.ReactNode;
}) {
  if (state.status === "idle") return <ForbiddenState role={role} />;
  if (state.status === "loading") return <LoadingState />;
  if (state.status === "error") {
    if (state.error.kind === "forbidden") return <ForbiddenState role={role} />;
    if (state.data === undefined) return <ErrorState error={state.error} onRetry={onRetry} />;
    return (
      <>
        <ErrorState error={state.error} onRetry={onRetry} />
        <p className="m-0 text-sm text-muted">Showing the last answer from field-api below.</p>
        {isEmpty?.(state.data) ? empty : children(state.data)}
      </>
    );
  }
  return <>{isEmpty?.(state.data) ? empty : children(state.data)}</>;
}

/** SCR4.09 "Live" / "Data is {n} min old" (stale after 2 min). */
export function Freshness({ state }: { state: PollState<unknown> }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 5000);
    return () => clearInterval(t);
  }, []);
  const at = state.status === "ok" ? state.at : state.status === "error" ? state.at : undefined;
  if (at === undefined) return null;
  const mins = Math.floor((now - at) / 60000);
  const stale = state.status === "error" || mins >= 2;
  return (
    <span className="text-sm text-muted" aria-live="polite">
      {stale ? (mins >= 1 ? `Data is ${mins} min old` : "Not updating") : "Live · updates every 5 seconds"}
    </span>
  );
}
