/** POST /api/console-auth/refresh. A new field token from the core token cookie, before the 600 s field token ends (M5-J01). */
import type { NextRequest } from "next/server";
import { handleRefresh } from "../../../../lib/consoleAuthHandlers";
import { serverDeps } from "../../../../lib/consoleAuthDeps";

export const dynamic = "force-dynamic";

export function POST(req: NextRequest) {
  return handleRefresh(req, serverDeps());
}
