import { callBackend, readJson } from "@/app/lib/backend";

// Asks the backend who speaks next. No model call — this is a fast lookup that
// lets the UI light up the right portrait while the reply is still being
// written. The turn rule itself lives in backend/app/orchestrator.py.

export async function POST(req: Request) {
  const body = await readJson(req);
  if (body === null) {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  return callBackend("/agent/next-speaker", { body });
}
