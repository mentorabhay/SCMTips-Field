/** POST /api/console-auth/pairing. A code from the SCMTIPS core that signs the person's phone in, as a QR link (M5-L03). */
import type { NextRequest } from "next/server";
import { handlePairing } from "../../../../lib/consoleAuthHandlers";
import { serverDeps } from "../../../../lib/consoleAuthDeps";

export const dynamic = "force-dynamic";

export function POST(req: NextRequest) {
  return handlePairing(req, serverDeps());
}
