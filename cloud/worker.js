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
  "the speaker actually said. Keep every number exactly as the speaker " +
  "said it: number words stay words and digits stay digits. Reply with " +
  "only the cleaned text."
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
  ["the call is at four fifteen and the budget is two point five million",
   "The call is at four fifteen, and the budget is two point five million."],
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
  const day = today(); // YYYY-MM-DD (UTC)
  const stub = env.QUOTA_DO.get(env.QUOTA_DO.idFromName(installId));
  return await stub.take(day, DAILY_QUOTA_PER_INSTALL);
}

// Handlers return a plain payload object (the fetch handler adds timing
// and builds the Response, since with speculative quota checks the quota
// result may arrive after the handler finishes), or BUSY for an upstream
// rate limit.
const BUSY = Symbol("busy");

// Last quota count this isolate saw per install, for speculative mode
// (see the fetch handler). Isolate memory only.
const SPECULATE_MARGIN = 50;
const knownCounts = new Map();

function today() {
  return new Date().toISOString().slice(0, 10);
}

function rememberCount(installId, count) {
  if (knownCounts.size > 10000) {
    knownCounts.clear();
  }
  knownCounts.set(installId, { day: today(), count });
}

function knownNearCap(installId) {
  const k = knownCounts.get(installId);
  return !!k && k.day === today() &&
    k.count >= DAILY_QUOTA_PER_INSTALL - SPECULATE_MARGIN;
}

async function handleTranscribe(request, env, timing) {
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.length === 0) {
    return { text: "" };
  }
  const form = new FormData();
  form.append("file", new Blob([bytes], { type: "audio/wav" }), "audio.wav");
  form.append("model", "whisper-large-v3-turbo");
  form.append("language", "en"); // matches the local model's small.en (English-only)
  // verbose_json for per-segment no_speech_prob / avg_logprob, so segments
  // that are really silence can be dropped (see below).
  form.append("response_format", "verbose_json");
  // Optional bias prompt from the client (sentence style + personal
  // dictionary vocabulary, or developer mode's literal-symbol style),
  // base64 UTF-8 in X-Prompt-B64. Clients before 2026-09-25 never sent
  // one; a malformed value is ignored rather than failing the dictation.
  const promptB64 = request.headers.get("X-Prompt-B64");
  let prompt = "";
  if (promptB64) {
    try {
      const raw = Uint8Array.from(atob(promptB64), (c) => c.charCodeAt(0));
      prompt = new TextDecoder().decode(raw).slice(0, 800).trim();
      if (prompt) form.append("prompt", prompt);
    } catch (e) {
      // ignore
    }
  }

  // Groq first. Every user shares one free Groq key (~20 requests/minute),
  // so when it refuses (429), errors or can't be reached, fall back to
  // Workers AI rather than showing "Cloud is busy" (2026-09-27). Only when
  // both fail does the client get BUSY. X-Force-Fallback: 1 skips Groq so
  // the fallback's quality can be measured on demand.
  const t0 = Date.now();
  let groqResp = null;
  let groqProblem = request.headers.get("X-Force-Fallback") === "1" ? "forced" : null;
  if (!groqProblem) {
    try {
      groqResp = await fetch("https://api.groq.com/openai/v1/audio/transcriptions", {
        method: "POST",
        headers: { Authorization: `Bearer ${env.GROQ_API_KEY}` },
        body: form,
      });
      if (groqResp.status === 429 || groqResp.status >= 500) {
        groqProblem = `groq ${groqResp.status}`;
      } else if (!groqResp.ok) {
        throw new Error(`Groq transcription failed: ${groqResp.status} ${await groqResp.text()}`);
      }
    } catch (e) {
      if (e.message?.startsWith("Groq transcription failed")) throw e;
      groqProblem = `groq unreachable: ${e}`;
    }
  }
  if (groqProblem) {
    timing.groq_problem = groqProblem;
    try {
      const fb = await workersAiTranscribe(env, bytes, prompt);
      timing.upstream_ms = Date.now() - t0;
      if (fb.turbo_error) timing.turbo_error = fb.turbo_error;
      return { text: fb.text, via: fb.via };
    } catch (e) {
      timing.fallback_error = String(e);
      return BUSY; // same shape as our per-install quota: the client shows "Cloud is busy"
    }
  }
  const result = await groqResp.json();
  timing.upstream_ms = Date.now() - t0;
  // Whisper invents text for audio with no speech in it ("Thank you.",
  // and with a prompt, prompt-flavored text like "dot com" or "So, I'll
  // show you how to do it."). faster-whisper -- what Local mode uses --
  // drops such segments with exactly this rule by default
  // (no_speech_threshold 0.6 + log_prob_threshold -1.0); do the same here.
  // Per-segment numbers go back in timing so the thresholds stay
  // measurable from the client.
  const segments = Array.isArray(result.segments) ? result.segments : null;
  if (!segments) {
    return { text: result.text || "", via: "groq" };
  }
  const kept = [];
  timing.segments = segments.map((s) => {
    const silent = s.no_speech_prob > NO_SPEECH_PROB && s.avg_logprob < MIN_AVG_LOGPROB;
    if (!silent) kept.push(s.text || "");
    return [round2(s.no_speech_prob), round2(s.avg_logprob), silent ? 0 : 1];
  });
  return { text: kept.join("").trim(), via: "groq" };
}

// Workers AI speech-to-text, for when Groq can't serve. large-v3-turbo (the
// same model Groq runs) takes the WAV as a base64 string; the older base
// "whisper" model takes a byte array and is the last resort. Counts against
// Workers AI's own free allowance (10,000 neurons/day, account-wide).
async function workersAiTranscribe(env, bytes, prompt) {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  try {
    const input = { audio: btoa(binary), language: "en" };
    if (prompt) input.initial_prompt = prompt;
    const r = await env.AI.run("@cf/openai/whisper-large-v3-turbo", input);
    return { text: (r.text || "").trim(), via: "workers-ai-large-v3-turbo" };
  } catch (e) {
    const r = await env.AI.run("@cf/openai/whisper", { audio: [...bytes] });
    return { text: (r.text || "").trim(), via: "workers-ai-whisper", turbo_error: String(e) };
  }
}

const NO_SPEECH_PROB = 0.6;
const MIN_AVG_LOGPROB = -1.0;
const round2 = (x) => Math.round((Number(x) || 0) * 100) / 100;

async function handleGrammar(request, env, timing) {
  const { text } = await request.json();
  if (!text) {
    return { text: "" };
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
        return { text: plainText(out), via: "groq" };
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
  return {
    text: result.response || text,
    via: "workers-ai",
    groq_error: groqError,
  };
}

export default {
  async fetch(request, env, ctx) {
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
    const url = new URL(request.url);
    const handler = { "/transcribe": handleTranscribe, "/grammar": handleGrammar }[url.pathname];
    if (!handler) {
      return new Response("Not found", { status: 404 });
    }

    // Per-stage server-side timings, returned in each JSON response so
    // cloud latency can be broken down from the client.
    const timing = { colo: request.cf?.colo };
    const tq = Date.now();
    const quotaPromise = checkAndIncrementQuota(env, installId).then((q) => {
      timing.quota_ms = Date.now() - tq;
      timing.quota_count = q.count;
      rememberCount(installId, q.count);
      return q;
    });

    // Speculative mode: the quota check (~70ms from a warm isolate, ~650ms
    // from a fresh one -- measured 2026-09-25, BOM; real dictations are
    // minutes apart, so mostly fresh) is taken off the response path
    // entirely -- it still runs and counts exactly, via ctx.waitUntil,
    // and its result teaches this isolate the install's count. Installs
    // this isolate knows are at or near their cap are gated before
    // anything reaches Groq, exactly as before. Speculating on installs
    // this isolate hasn't seen costs no real protection: X-Install-Id is client-chosen,
    // so an abuser could already mint fresh ids that start at zero -- the
    // per-install quota only ever reined in runaway legitimate installs,
    // and the providers' free-tier caps remain the real cost backstop. The
    // leak is at most one served request per fresh isolate for an
    // over-cap install before that isolate learns its count. (Speculative
    // responses only carry quota_ms/quota_count if the check happened to
    // finish before the upstream call did.)
    const speculative = !knownNearCap(installId);
    timing.speculative = speculative;
    try {
      let payload;
      if (speculative) {
        ctx.waitUntil(quotaPromise);
        payload = await handler(request, env, timing);
      } else {
        const quota = await quotaPromise;
        if (!quota.ok) {
          return quotaExceeded();
        }
        payload = await handler(request, env, timing);
      }
      if (payload === BUSY) {
        return quotaExceeded();
      }
      return Response.json({ ...payload, timing });
    } catch (err) {
      return Response.json({ error: String(err) }, { status: 500 });
    }
  },
};
