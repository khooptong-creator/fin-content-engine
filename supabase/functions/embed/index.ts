// Fin-Content Engine — embedding edge function (Part II §1.2, §3.6).
//
// Wraps Supabase's built-in gte-small (384-dim) model via the `Supabase.ai` runtime.
// The worker calls this over HTTP with the constructed embedding input:
//     <title> <title> <first 500 chars of full_text or "">
// so the *input construction* lives in the Python worker (testable, config-driven)
// and this function stays a thin pass-through to the model. That separation is what
// makes the §5.1 provenance assertion meaningful: the fixture pins the model AND the
// input construction (title_weight_repeat, body_truncate_chars) on the worker side.

// eslint-disable-next-line @typescript-eslint/no-namespace
declare namespace Deno {
  // Supabase injects a global `Supabase` with `.ai.run()` at runtime.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const Supabase: any;
}

interface EmbedRequest {
  text: string;
}

interface EmbedResponse {
  embedding: number[];
}

export default async function handler(req: Request): Promise<Response> {
  if (req.method !== "POST") {
    return json({ error: "method not allowed" }, 405);
  }

  let body: EmbedRequest;
  try {
    body = (await req.json()) as EmbedRequest;
  } catch {
    return json({ error: "invalid JSON" }, 400);
  }

  if (!body || typeof body.text !== "string" || body.text.length === 0) {
    return json({ error: "missing 'text' field" }, 400);
  }

  // Truncate defensively. The worker already truncates body to 500 chars and
  // repeats the title; we cap the total here so a malformed request can't
  // blow up the model. ~2000 chars is a comfortable ceiling for gte-small.
  const text = body.text.slice(0, 2000);

  try {
    // Supabase's built-in gte-small. No API key, no auth header — the runtime
    // provides it. The model name is part of the §5.1 provenance contract:
    // changing it requires regenerating the fixture embeddings.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const result = await (Deno as any).Supabase.ai.run("gte-small", {
      value: text,
    });
    const embedding: number[] = Array.isArray(result?.data)
      ? result.data
      : result;
    if (!Array.isArray(embedding) || embedding.length !== 384) {
      return json(
        { error: `unexpected embedding shape: ${embedding?.length}` },
        502,
      );
    }
    return json({ embedding } satisfies EmbedResponse, 200);
  } catch (err) {
    // Surface a 5xx so the worker's retry/backoff path (§3.6) fires correctly.
    const message = err instanceof Error ? err.message : String(err);
    return json({ error: `embedding failed: ${message}` }, 502);
  }
}

function json(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// Tell Deno to actively serve the handler. Required on Supabase's current runtime;
// without it the function deploys but never answers requests.
Deno.serve(handler);
