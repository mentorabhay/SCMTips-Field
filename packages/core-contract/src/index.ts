/**
 * SCMTIPS Core Platform Contract Types (P13 Reference / Task T1.032).
 */

export const CORE_TAG = "core-p13";

export interface JwksKey {
  kty: string;
  use?: string;
  alg?: string;
  crv?: string;
  kid: string;
  x?: string;
  y?: string;
  n?: string;
  e?: string;
}

export interface JwksResponse {
  keys: JwksKey[];
}

export interface TokenRequest {
  principal_id: string;
  tenant_id: string;
  device_id?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface DeviceStatusResponse {
  device_id: string;
  tenant_id: string;
  status: "active" | "revoked" | "suspended";
  fingerprint?: string;
  last_seen_at?: string;
}

export interface GenericAck {
  success: boolean;
  message: string;
}
