/**
 * Phones and glasses (T2.061 / T2.062): GET /v1/devices -> rows; Revoke -> POST /v1/devices/{id}/revoke.
 * Stale = no heartbeat for 15 minutes (is_stale from field-api). Copy MSG2.19 after a revoke.
 */
import type { Device } from "../api";
import { relativeTime } from "./format";

export const MSG2_19 = "Device revoked. It stops capturing within a minute. Unsent items stay locked on the device for 72 hours.";

export type SeenTone = "ok" | "stale" | "off";

export interface DeviceRow {
  id: string;
  name: string;
  serial: string;
  paired: string;
  seen: string;
  seenTone: SeenTone;
  battery: string;
  queue: string;
  revoked: boolean;
  versions: string;
}

export function kindLabel(kind: string): string {
  if (kind === "phone") return "Phone";
  if (kind === "glasses") return "Glasses";
  return kind ? kind.charAt(0).toUpperCase() + kind.slice(1) : "Device";
}

export function deviceName(d: Device): string {
  return `${kindLabel(d.kind)} · ${d.model}`;
}

export function deviceRow(d: Device, byId: ReadonlyMap<string, Device>, nowMs: number): DeviceRow {
  const revoked = d.status === "revoked" || Boolean(d.revoked_at);
  const partner = d.paired_with ? byId.get(d.paired_with) : undefined;
  const versions = [d.app_version ? `app ${d.app_version}` : null, d.firmware_version ? `firmware ${d.firmware_version}` : null]
    .filter(Boolean)
    .join(" · ");
  return {
    id: d.id,
    name: deviceName(d),
    serial: d.serial_no,
    paired: partner ? deviceName(partner) : d.paired_with ? "Paired (device not in this list)" : "Not paired",
    seen: revoked ? `Revoked ${relativeTime(d.revoked_at, nowMs).toLowerCase()}` : relativeTime(d.last_seen_at, nowMs),
    seenTone: revoked ? "off" : d.is_stale ? "stale" : "ok",
    battery: typeof d.battery_pct === "number" ? `${d.battery_pct}%` : "Not reported",
    queue: typeof d.queue_depth === "number" ? String(d.queue_depth) : "Not reported",
    revoked,
    versions,
  };
}

export function buildDeviceRows(devices: readonly Device[], nowMs: number): DeviceRow[] {
  const byId = new Map(devices.map((d) => [d.id, d]));
  const rank = (r: DeviceRow) => (r.revoked ? 2 : r.seenTone === "stale" ? 1 : 0);
  return devices.map((d) => deviceRow(d, byId, nowMs)).sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}
