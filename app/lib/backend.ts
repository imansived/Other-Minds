// Server-side bridge to the Python (FastAPI) backend.
//
// The browser never talks to FastAPI directly: these route handlers proxy to it
// from the server, so the backend needs no CORS, no public exposure, and the
// API key stays where it already was — out of the client bundle entirely.

const API_URL = process.env.OTHER_MINDS_API_URL ?? "http://127.0.0.1:8000";

// Long enough for a full agent turn; the backend has its own shorter timeout.
const TIMEOUT_MS = 90_000;

export async function callBackend(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<Response> {
  const method = init.method ?? "POST";
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}${path}`, {
      method,
      headers: init.body === undefined ? {} : { "Content-Type": "application/json" },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
      cache: "no-store",
    });
  } catch (err) {
    // Two processes now, so "it just hangs" needs to become a real message:
    // the most common failure by far is simply forgetting to start the backend.
    const timedOut = err instanceof Error && err.name === "TimeoutError";
    return Response.json(
      {
        error: timedOut
          ? "The backend took too long to respond."
          : `Can't reach the Python backend at ${API_URL}. Start it with:\n` +
            `  npm run dev:api`,
      },
      { status: 503 },
    );
  }

  const text = await upstream.text();

  // Everything past this point exists to guarantee ONE thing: the client always
  // receives JSON. It parses every response with res.json(), so a non-JSON body
  // reaches the reader as "Unexpected token 'I' ... is not valid JSON" and
  // hides whatever actually went wrong.
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    // Not JSON at all. FastAPI answers an unhandled exception with the plain
    // text "Internal Server Error"; a proxy or a crash can produce HTML.
    return Response.json(
      {
        error:
          upstream.status >= 500
            ? `The backend failed (HTTP ${upstream.status}). Check the api log for the traceback.`
            : text.slice(0, 300) || `Unexpected response (HTTP ${upstream.status})`,
      },
      { status: upstream.status },
    );
  }

  // The backend speaks { error } on failure, which is what the client already
  // expects — but FastAPI's own request validation answers with { detail }.
  // Normalise that one case so every error reaches the client the same shape.
  if (!upstream.ok) {
    const body = parsed as { error?: unknown; detail?: unknown } | null;
    if (body?.error === undefined && body?.detail !== undefined) {
      const detail = body.detail;
      const message =
        typeof detail === "string"
          ? detail
          : ((detail as { msg?: string }[] | undefined)?.[0]?.msg ?? "Invalid request");
      return Response.json({ error: message }, { status: upstream.status });
    }
  }

  // Valid JSON — pass status and body through untouched.
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

/** Read a request's JSON body, or null if it isn't valid JSON. */
export async function readJson(req: Request): Promise<unknown | null> {
  try {
    return await req.json();
  } catch {
    return null;
  }
}
