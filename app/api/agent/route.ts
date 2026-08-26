import { callBackend, readJson } from "@/app/lib/backend";

// Thin proxy to the Python backend.
//
// The agents, their prompts, the model call and the turn rule all live in
// backend/app now — see backend/README.md. This handler exists so the browser
// keeps talking to its own origin.

export async function POST(req: Request) {
  const body = await readJson(req);
  if (body === null) {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  return callBackend("/agent/turn", { body });
}
