"use client";

import React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { isActive } from "@/lib/views/board";
import { roleLabel } from "@/lib/session";
import { config } from "@/lib/config";
import { LiveDataProvider, useLive, useSession } from "./session";
import { dataOf } from "./usePoll";
import { cx, LoadingState } from "./ui";

interface NavItem {
  href: string;
  label: string;
  count?: number | null;
  warn?: boolean;
}

function Logo() {
  return (
    <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-primary">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 7l9-4 9 4v10l-9 4-9-4z" />
        <path d="M3 7l9 4 9-4" />
        <path d="M12 11v10" />
      </svg>
    </span>
  );
}

function initials(id: string): string {
  const parts = id.replace(/^dev-/, "").split(/[^A-Za-z0-9]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

function Nav() {
  const path = usePathname() ?? "/";
  const live = useLive();
  const tasks = dataOf(live.tasks);
  const approvals = dataOf(live.approvals);
  const mismatches = dataOf(live.mismatches);
  const queues = dataOf(live.queues);
  const decisions = approvals || mismatches ? (approvals?.filter((a) => a.status === "pending").length ?? 0) + (mismatches?.length ?? 0) : null;
  const items: NavItem[] = [
    { href: "/", label: "Right now" },
    { href: "/work", label: "Live work", count: tasks ? tasks.filter(isActive).length : null },
    { href: "/decisions", label: "Decisions", count: decisions, warn: true },
    { href: "/warehouse/board", label: "Warehouse" },
    { href: "/sites", label: "Sites and towers" },
    { href: "/postings", label: "Postings to SAP", count: queues ? queues.filter((q) => q.is_blocked).length : null, warn: true },
    { href: "/devices", label: "Phones and glasses" },
    { href: "/sessions", label: "Assistant sessions" },
    { href: "/recalls", label: "Recalls · phase 5" },
    { href: "/packs", label: "Industry packs · phase 7" },
    { href: "/status", label: "System status" },
  ];
  return (
    <nav aria-label="Console" className="w-full shrink-0 md:w-[240px]">
      <ul className="m-0 flex list-none gap-1 overflow-x-auto p-3 md:flex-col md:overflow-visible md:p-4">
        {items.map((n) => {
          const on = n.href === "/" ? path === "/" : path === n.href || path.startsWith(`${n.href}/`);
          return (
            <li key={n.href} className="shrink-0">
              <Link
                href={n.href}
                aria-current={on ? "page" : undefined}
                className={cx(
                  "flex min-h-[44px] items-center gap-2.5 whitespace-nowrap rounded-md px-3 py-2.5 font-bold no-underline hover:bg-column",
                  on ? "bg-selected text-primary hover:text-primary" : "text-ink hover:text-ink",
                )}
              >
                <span className="flex-1">{n.label}</span>
                {n.count ? (
                  <span
                    className={cx("rounded-full px-2 py-px text-[13px]", n.warn ? "bg-warn-pill text-warn-pillink" : "bg-pill-bg text-pill-ink")}
                    aria-label={`${n.count} ${n.warn ? "waiting" : "open"}`}
                  >
                    {n.count}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function Header() {
  const { session, signOut } = useSession();
  const router = useRouter();
  return (
    <header className="flex flex-wrap items-center gap-x-5 gap-y-3 border-b border-line bg-card px-4 py-3.5 sm:px-6">
      <Link href="/" className="flex items-center gap-2.5 text-lg font-bold text-ink no-underline hover:text-ink">
        <Logo />
        SCMTips Field
      </Link>
      <div className="flex-1" />
      {session ? (
        <>
          <div className="text-sm text-muted">
            Tenant <span className="font-mono">{session.tenantId.slice(0, 8)}</span>
            {config.devSignIn ? " · development sign-in" : ""}
          </div>
          <div className="flex items-center gap-2 text-sm font-bold">
            <span aria-hidden="true" className="flex h-9 w-9 items-center justify-center rounded-full bg-primary text-white">
              {initials(session.principalId)}
            </span>
            <span>
              {session.principalId} · {roleLabel(session.roles)}
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              signOut();
              router.push("/login");
            }}
            className="min-h-[44px] rounded-md border border-control bg-card px-3 font-bold text-ink hover:bg-soft"
          >
            Sign out
          </button>
        </>
      ) : null}
    </header>
  );
}

function SignedOut() {
  return (
    <div className="flex flex-col items-start gap-2 rounded-card border border-line bg-card p-5">
      <h1 className="m-0 text-2xl font-bold">You are signed out</h1>
      <p className="m-0 text-muted">Sign in to see live work, decisions and postings.</p>
      <Link href="/login" className="inline-flex min-h-[44px] items-center rounded-md bg-primary px-4 font-bold text-white no-underline hover:bg-primary-hover hover:text-white">
        Sign in
      </Link>
    </div>
  );
}

export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const { ready, session } = useSession();
  return (
    <div className="min-h-screen bg-page text-ink">
      <a href="#main" className="sr-only-focusable absolute left-2 top-2 z-10 rounded bg-card px-3 py-2 font-bold">
        Skip to content
      </a>
      <Header />
      {!ready ? (
        <main id="main" className="mx-auto max-w-[1440px] p-6">
          <LoadingState />
        </main>
      ) : !session ? (
        <main id="main" className="mx-auto max-w-[1440px] p-6">
          <SignedOut />
        </main>
      ) : (
        <LiveDataProvider>
          <div className="mx-auto flex max-w-[1440px] flex-col md:flex-row">
            <Nav />
            <main id="main" className="flex min-w-0 flex-1 flex-col gap-5 p-4 sm:p-6">
              {children}
            </main>
          </div>
        </LiveDataProvider>
      )}
    </div>
  );
}
