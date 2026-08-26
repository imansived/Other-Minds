import { callBackend, readJson } from "@/app/lib/backend";

// One stored conversation: read it, mirror the live transcript into it, or
// remove it. Storage lives in backend/app/store.py.

export async function GET(_req: Request, ctx: RouteContext<"/api/conversations/[id]">) {
  const { id } = await ctx.params;
  return callBackend(`/conversations/${encodeURIComponent(id)}`, { method: "GET" });
}

export async function PUT(req: Request, ctx: RouteContext<"/api/conversations/[id]">) {
  const { id } = await ctx.params;
  const body = await readJson(req);
  if (body === null) {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  return callBackend(`/conversations/${encodeURIComponent(id)}`, {
    method: "PUT",
    body,
  });
}

export async function DELETE(
  _req: Request,
  ctx: RouteContext<"/api/conversations/[id]">,
) {
  const { id } = await ctx.params;
  return callBackend(`/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
