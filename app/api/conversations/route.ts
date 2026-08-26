import { callBackend } from "@/app/lib/backend";

// The conversation list for the history sidebar. Transcripts are not included —
// the list view never renders one.

export async function GET() {
  return callBackend("/conversations", { method: "GET" });
}
