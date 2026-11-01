"use client";

/** A QR code drawn as one SVG path from lib/qr.ts (M5-L03). Always black on white with its quiet zone, in either theme. */
import React, { useMemo } from "react";
import { encodeQr, QR_QUIET_ZONE, qrSvgPath } from "@/lib/qr";

export function QrCode({ text, label, size = 264 }: { text: string; label: string; size?: number }) {
  const { path, n } = useMemo(() => {
    const qr = encodeQr(text);
    return { path: qrSvgPath(qr), n: qr.size + 2 * QR_QUIET_ZONE };
  }, [text]);
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${n} ${n}`} width={size} height={size} shapeRendering="crispEdges" className="block h-auto max-w-full">
      <rect width={n} height={n} fill="#FFFFFF" />
      <path d={path} fill="#000000" />
    </svg>
  );
}
