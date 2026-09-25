import { DurableObject } from "cloudflare:workers";

// Talkative cloud processing mode -- see talkative/config.py's
// PROCESSING_MODE and cloud_client.py.
//
// Two routes, one per model-backed pipeline stage the local app normally
// runs on-device:
//   POST /transcribe  body: raw WAV bytes       -> { "text": "..." }
//   POST /grammar      body: {"text": "..."}     -> { "text": "..." }
//
// Both require a matching X-Shared-Secret header (env.SHARED_SECRET, set
// via `wrangler secret put SHARED_SECRET`) -- a soft deterrent only, not
// real auth: the secret ships inside a public EXE, so treat it as
// extractable by anyone motivated to look. The two things actually
// bounding cost/abuse are (1) the per-install daily QUOTA check below,
// keyed by the X-Install-Id header the app already generates
// (talkative/feedback.py's install_id()), and (2) each upstream
// provider's own free-tier cap, which hard-errors instead of billing as
// long as neither account has billing enabled: Workers AI's account-wide
// 10,000 neurons/day for /grammar (see wrangler.toml), and Groq's
// no-card free tier for /transcribe (~2,000 requests/day, ~8 hours of
// audio/day as of 2026-09 -- see GROQ_API_KEY note in wrangler.toml).
// Don't remove the shared secret (it's free to keep and stops the most
// casual scraping), but don't mistake it for the real protection either.
//
// /transcribe moved off Workers AI to Groq's hosted whisper-large-v3-turbo
// on 2026-09-19: real accuracy upgrade (actual large-v3-turbo weights, not
// Cloudflare's smaller base @cf/openai/whisper), and Groq's free tier
// needs no card. Cloudflare's own @cf/openai/whisper-large-v3-turbo was
// tried first (see the old handleTranscribe comment, still true) and
// rejected every audio shape tested against its schema, which is why
// /transcribe ran on the smaller base model until now.
//
// /grammar moved to Groq (GROQ_GRAMMAR_MODEL) on 2026-09-25 for latency
// (same GROQ_API_KEY), with the original Workers AI model kept as an
// automatic fallback -- see handleGrammar.

const DAILY_QUOTA_PER_INSTALL = 300; // combined /transcribe + /grammar calls

// Groq's Llama chat models (llama-3.1-8b-instant etc.) are enterprise-only
// as of 2026-09 -- a free-tier key gets 404 model_not_found for them. The
// gpt-oss models are what a free key can use.
const GROQ_GRAMMAR_MODEL = "openai/gpt-oss-20b";

// Same system instruction and few-shot examples as
// talkative/grammar_engine.py's _SYSTEM/_SHOTS, so cloud mode behaves the
// same as local mode. Keep these two in sync by hand if either changes.
const SYSTEM = (
  "You clean up dictated text. Fix grammar and punctuation. Remove word " +
  "repetitions, false starts, and spoken self-corrections (keep only what " +
  "the speaker corrected themselves to). Most sentences are already " +
  "clear and should only get grammar and punctuation fixes -- leave the " +
  "speaker's own words, idioms, and phrasing alone even if a plainer or " +
  "more formal version occurs to you. Only reword a sentence when it is " +
  "genuinely garbled or hard to follow (missing words, tangled syntax), " +
  "and even then stay as close to the speaker's own words as you " +
  "reasonably can. Never add information or invent claims the speaker " +
  "didn't make, never change names or numbers, and never drop something " +
  "the speaker actually said. Reply with only the cleaned text."
);

const SHOTS = [
  ["the report the report needs to go out before the meeting starts",
   "The report needs to go out before the meeting starts."],
  ["send the file today, oh sorry, send the file by this evening.",
   "Send the file by this evening."],
  ["we should also check the numbers again before we send it because last " +
   "time there was a mistake in the numbers and the client noticed it",
   "We should also check the numbers again before we send it, because last " +
   "time there was a mistake in the numbers and the client noticed it."],
  ["there's this issue where when the user clicks the button nothing " +
   "happens sometimes it's kind of random",
   "There's an issue where clicking the button sometimes does nothing; " +
   "it seems random."],
];

// gpt-oss likes typographic characters (curly quotes, narrow no-break
// space in "3 pm") that Whisper never emits -- map them back to the plain
// ASCII the rest of the pipeline and the dictionary rules expect.
function plainText(s) {
  return s
    .replace(/[‘’‛]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[    ]/g, " ");
}

function unauthorized() {
  return new Response("Unauthorized", { status: 401 });
}

function quotaExceeded() {
  return Response.json(
    { error: "daily quota exceeded" },
    { status: 429 }
  );
}

// Per-install daily quota, one Durable Object per install id (2026-09-25).
// Replaced a Workers KV counter that under-counted badly: KV reads are
// cached per colo for up to ~60s, so back-to-back requests all read the
// same stale count and wrote the same next value back (measured: 10
// requests -> counter of 2). A Durable Object is single-threaded with
// strongly consistent storage, so take() is an exact atomic
// check-and-increment, and it's fast (a few ms) because the object lives
// near where it was first used. Storage stays one small record per
// install: the day rolls the count over rather than adding a new key.
export class QuotaCounter extends DurableObject {
  async take(day, limit) {
    const rec = (await this.ctx.storage.get("rec")) || { day, count: 0 };
    if (rec.day !== day) {
      rec.day = day;
      rec.count = 0;
    }
    if (rec.count >= limit) {
      return { ok: false, count: rec.count };
    }
    rec.count += 1;
    await this.ctx.storage.put("rec", rec);
    return { ok: true, count: rec.count };
  }
}

async function checkAndIncrementQuota(env, installId) {
  const day = new Date().toISOString().slice(0, 10); // YYYY-MM-DD (UTC)
  const stub = env.QUOTA_DO.get(env.QUOTA_DO.idFromName(installId));
  return await stub.take(day, DAILY_QUOTA_PER_INSTALL);
}

async function handleTranscribe(request, env, timing) {
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.length === 0) {
    return Response.json({ text: "" });
  }
  const form = new FormData();
  form.append("file", new Blob([bytes], { type: "audio/wav" }), "audio.wav");
  form.append("model", "whisper-large-v3-turbo");
  form.append("language", "en"); // matches the local model's small.en (English-only)
  form.append("response_format", "json");

  const t0 = Date.now();
  const groqResp = await fetch(
    "https://api.groq.com/openai/v1/audio/transcriptions",
    {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GROQ_API_KEY}` },
      body: form,
    }
  );
  if (groqResp.status === 429) {
    // Groq's own free-tier limit, not ours -- surface the same "busy" shape
    // our per-install quota uses so cloud_client.py's existing 429 handling
    // (CLOUD_BUSY_MESSAGE) covers this too, no client-side change needed.
    return quotaExceeded();
  }
  if (!groqResp.ok) {
    throw new Error(`Groq transcription failed: ${groqResp.status} ${await groqResp.text()}`);
  }
  const result = await groqResp.json();
  timing.upstream_ms = Date.now() - t0;
  return Response.json({ text: result.text || "", timing });
}

async function handleGrammar(request, env, timing) {
  const { text } = await request.json();
  if (!text) {
    return Response.json({ text: "" });
  }
  const messages = [{ role: "system", content: SYSTEM }];
  for (const [spoken, cleaned] of SHOTS) {
    messages.push({ role: "user", content: spoken });
    messages.push({ role: "assistant", content: cleaned });
  }
  messages.push({ role: "user", content: text });

  // Groq first (2026-09-25) for latency: Workers AI's llama-3.2-3b took
  // ~1-1.5s per call.
  // Any Groq failure (its own free-tier 429 included) falls back to the
  // original Workers AI path rather than surfacing an error -- grammar is
  // optional polish, so a slower answer beats none.
  // Why the Groq attempt fell back, returned alongside the fallback result
  // (status + Groq's own error text, never the key) so a silent fallback is
  // diagnosable from the client without Worker log access.
  let groqError = null;
  const t0 = Date.now();
  try {
    const groqResp = await fetch(
      "https://api.groq.com/openai/v1/chat/completions",
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GROQ_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: GROQ_GRAMMAR_MODEL,
          messages,
          temperature: 0,
          // gpt-oss is a reasoning model: keep its thinking short (that's
          // where the latency goes) and out of the returned content.
          reasoning_effort: "low",
          include_reasoning: false,
          max_tokens: 2048,
        }),
      }
    );
    if (groqResp.ok) {
      const result = await groqResp.json();
      const out = result.choices?.[0]?.message?.content;
      if (out) {
        timing.upstream_ms = Date.now() - t0;
        // Groq's own server-side time, to separate model time from the
        // Worker<->Groq network hop.
        timing.groq_total_ms = Math.round((result.usage?.total_time || 0) * 1000);
        return Response.json({ text: plainText(out), via: "groq", timing });
      }
      groqError = "empty completion";
    } else {
      groqError = `${groqResp.status} ${(await groqResp.text()).slice(0, 300)}`;
    }
  } catch (err) {
    groqError = String(err).slice(0, 300);
  }

  const result = await env.AI.run("@cf/meta/llama-3.2-3b-instruct", {
    messages,
    temperature: 0,
  });
  return Response.json({
    text: result.response || text,
    via: "workers-ai",
    groq_error: groqError,
    timing,
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Not found", { status: 404 });
    }
    if (request.headers.get("X-Shared-Secret") !== env.SHARED_SECRET) {
      return unauthorized();
    }
    const installId = request.headers.get("X-Install-Id");
    if (!installId) {
      return new Response("Missing X-Install-Id", { status: 400 });
    }
    // Per-stage server-side timings, returned in each JSON response so
    // cloud latency can be broken down from the client (see
    // cloud_client.py's callers / the debug.log timing line).
    const tq = Date.now();
    const quota = await checkAndIncrementQuota(env, installId);
    if (!quota.ok) {
      return quotaExceeded();
    }
    const timing = {
      quota_ms: Date.now() - tq,
      quota_count: quota.count,
      colo: request.cf?.colo,
    };
    const url = new URL(request.url);
    try {
      if (url.pathname === "/transcribe") {
        return await handleTranscribe(request, env, timing);
      }
      if (url.pathname === "/grammar") {
        return await handleGrammar(request, env, timing);
      }
    } catch (err) {
      return Response.json({ error: String(err) }, { status: 500 });
    }
    return new Response("Not found", { status: 404 });
  },
};
