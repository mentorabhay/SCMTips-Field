"use client";

import React, { createContext, useContext, useEffect, useState, useSyncExternalStore } from "react";
import type { ActiveVisits, ApprovalRequest, Device, Mismatch, QueueSummary, Task } from "@/lib/api";
import { api, sessionStore } from "@/lib/client";
import { hasPermission, isExpired, type FieldSession } from "@/lib/session";
import { usePoll, type PollState } from "./usePoll";

// ------------------------------------------------------------------ session

interface SessionValue {
  /** false until the browser has read sessionStorage (server render and first client paint). */
  ready: boolean;
  session: FieldSession | null;
  can: (permission: string) => boolean;
  signOut: () => void;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const stored = useSyncExternalStore(
    (fn) => sessionStore.subscribe(fn),
    () => sessionStore.get(),
    () => null,
  );
  const [ready, setReady] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setReady(true);
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  const session = stored && !isExpired(stored, now) ? stored : null;
  useEffect(() => {
    if (stored && isExpired(stored, now)) sessionStore.clear();
  }, [stored, now]);
  const value: SessionValue = {
    ready,
    session,
    can: (p) => Boolean(session && hasPermission(session.permissions, p)),
    signOut: () => sessionStore.clear(),
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const v = useContext(SessionContext);
  if (!v) throw new Error("useSession outside SessionProvider");
  return v;
}

// ------------------------------------------------------------------ live lists (polled every 5 s)

/** Permission each list needs on field-api, and the dev sign-in role that has it. */
export const NEEDS = {
  tasks: { permission: "field.task.read", role: "Supervisor" },
  queues: { permission: "field.queue.read", role: "Supervisor" },
  devices: { permission: "field.device.read", role: "Supervisor" },
  system: { permission: "field.system.read", role: "Supervisor" },
  sites: { permission: "field.site.read", role: "Supervisor" },
} as const;

export interface LiveData {
  tasks: PollState<Task[]>;
  approvals: PollState<ApprovalRequest[]>;
  mismatches: PollState<Mismatch[]>;
  queues: PollState<QueueSummary[]>;
  devices: PollState<Device[]>;
  visits: PollState<ActiveVisits>;
  refresh: {
    tasks: () => Promise<void>;
    approvals: () => Promise<void>;
    mismatches: () => Promise<void>;
    queues: () => Promise<void>;
    devices: () => Promise<void>;
    visits: () => Promise<void>;
  };
}

const LiveContext = createContext<LiveData | null>(null);

export function LiveDataProvider({ children }: { children: React.ReactNode }) {
  const { session, can } = useSession();
  const on = Boolean(session);
  const key = session?.accessToken ?? "";
  const tasks = usePoll(() => api.listTasks(), { enabled: on && can(NEEDS.tasks.permission), key });
  const approvals = usePoll(() => api.listPendingApprovals(), { enabled: on, key });
  const mismatches = usePoll(() => api.listMismatches(), { enabled: on, key });
  const queues = usePoll(() => api.listPostingQueues(), { enabled: on && can(NEEDS.queues.permission), key });
  const devices = usePoll(() => api.listDevices(), { enabled: on && can(NEEDS.devices.permission), key });
  const visits = usePoll(() => api.listActiveVisits(), { enabled: on, key });
  const value: LiveData = {
    tasks: tasks.state,
    approvals: approvals.state,
    mismatches: mismatches.state,
    queues: queues.state,
    devices: devices.state,
    visits: visits.state,
    refresh: {
      tasks: tasks.refresh,
      approvals: approvals.refresh,
      mismatches: mismatches.refresh,
      queues: queues.refresh,
      devices: devices.refresh,
      visits: visits.refresh,
    },
  };
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveData {
  const v = useContext(LiveContext);
  if (!v) throw new Error("useLive outside LiveDataProvider");
  return v;
}
