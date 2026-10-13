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
// Per network address (2026-10-13): install ids are client-chosen, so a
// script minting fresh ids could use up the shared free Groq allowance and
// make Cloud busy for everyone. 600 requests = ~300 dictations, about a
// third of Groq's 1,000/day grammar cap. An office or a mobile carrier's
// shared address (CGNAT, common in India) shares one count. Raises the bar
// only -- rotating addresses still gets through.
const DAILY_QUOTA_PER_IP = 600;

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

async function checkAndIncrementQuota(env, name, limit) {
  const day = today(); // YYYY-MM-DD (UTC)
  const stub = env.QUOTA_DO.get(env.QUOTA_DO.idFromName(name));
  return await stub.take(day, limit);
}

// The per-address quota's counter name: a one-way hash of the address (the
// raw address is never stored -- PRIVACY.md), IPv6 cut to its /64 network
// so one connection can't rotate through its own addresses.
async function ipQuotaName(request) {
  const ip = request.headers.get("CF-Connecting-IP");
  if (!ip) return null;
  const net = ip.includes(":") ? ipv6Network(ip) : ip;
  const digest = await crypto.subtle.digest(
    "SHA-256", new TextEncoder().encode("talkative-ip:" + net));
  const hex = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return "ip:" + hex.slice(0, 32);
}

export function ipv6Network(ip) {
  let [head, tail] = ip.split("::");
  const h = head ? head.split(":") : [];
  const t = tail !== undefined && tail ? tail.split(":") : [];
  const groups = tail === undefined ? h : [...h, ...Array(8 - h.length - t.length).fill("0"), ...t];
  return groups.slice(0, 4).map((g) => parseInt(g || "0", 16).toString(16)).join(":");
}

// Free-limit log (2026-10-13): one Durable Object ("global") recording, per
// UTC day, every time a provider's free limit refused us and how close the
// day came to Groq's daily caps. Read with GET /limits + X-Admin-Key
// (tools/cloud_limits.py). Written only off the response path (waitUntil):
// on a limit hit, and when a day's peak usage rises past what this isolate
// last reported, so normal dictations rarely touch it.
//   hits:  { "<kind>": { n, first, last, detail } }  kind e.g.
//          "groq whisper-large-v3-turbo RPD", "workers-ai neurons/day",
//          "busy" (a user saw "Cloud is busy"), "install cap", "ip cap"
//   peak:  { "<model> requests/day": { used, limit } }
const LIMIT_DAYS_KEPT = 120;

export class LimitLog extends DurableObject {
  async hit(day, kind, detail) {
    const rec = (await this.ctx.storage.get(day)) || { hits: {}, peak: {} };
    const now = new Date().toISOString().slice(11, 19);
    const h = rec.hits[kind] || { n: 0, first: now };
    h.n += 1;
    h.last = now;
    if (detail) h.detail = String(detail).slice(0, 200);
    rec.hits[kind] = h;
    await this.save(day, rec);
  }

  async peak(day, name, used, limit) {
    const rec = (await this.ctx.storage.get(day)) || { hits: {}, peak: {} };
    const p = rec.peak[name];
    if (p && p.used >= used) return;
    rec.peak[name] = { used, limit };
    await this.save(day, rec);
  }

  async save(day, rec) {
    await this.ctx.storage.put(day, rec);
    const days = [...(await this.ctx.storage.list()).keys()].sort();
    if (days.length > LIMIT_DAYS_KEPT) {
      await this.ctx.storage.delete(days.slice(0, days.length - LIMIT_DAYS_KEPT));
    }
  }

  async report() {
    return Object.fromEntries(await this.ctx.storage.list());
  }
}

function limitLog(env) {
  return env.LIMIT_DO.get(env.LIMIT_DO.idFromName("global"));
}

// Record a limit hit without delaying the response or ever failing it.
function noteHit(env, ctx, kind, detail) {
  ctx.waitUntil(limitLog(env).hit(today(), kind, detail)
    .catch((e) => console.error("limit log hit failed", String(e))));
}

// Groq's 429 says which limit refused: "...on requests per day (RPD):
// Limit 2000, Used 2000, Requested 1..." -> "RPD", "Limit 2000, Used 2000".
// The organization id in the same message is not kept.
export function groqLimitKind(model, body) {
  const m = /\(([A-Z]{2,4})\):\s*(Limit \d+, Used \d+)/.exec(body || "");
  return m ? [`groq ${model} ${m[1]}`, m[2]] : [`groq ${model} 429`, ""];
}

// Workers AI's own daily free allowance running out (error 4006: "you have
// used up your daily free allocation of 10,000 neurons") vs any other error.
export function workersAiKind(err) {
  return /4006|daily free allocation|neurons/i.test(String(err))
    ? "workers-ai neurons/day" : null;
}

// Highest requests/day usage this isolate has already reported, per day+model.
const reportedPeak = new Map();

// Groq's response headers carry the daily request allowance:
// x-ratelimit-limit-requests / x-ratelimit-remaining-requests (RPD).
function notePeak(env, ctx, model, resp, timing) {
  const limitH = resp.headers.get("x-ratelimit-limit-requests");
  const leftH = resp.headers.get("x-ratelimit-remaining-requests");
  timing.groq_requests_left = leftH === null ? "none" : `${leftH}/${limitH}`;
  const limit = Number(limitH);
  const left = Number(leftH);
  if (!limit || leftH === null || Number.isNaN(left)) return;
  const used = limit - left;
  const key = `${today()} ${model}`;
  if ((reportedPeak.get(key) ?? -1) >= used) return;
  if (reportedPeak.size > 100) reportedPeak.clear();
  reportedPeak.set(key, used);
  ctx.waitUntil(
    limitLog(env).peak(today(), `${model} requests/day`, used, limit)
      .catch((e) => console.error("limit log peak failed", String(e)))
  );
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

function rememberCount(name, count) {
  if (knownCounts.size > 10000) {
    knownCounts.clear();
  }
  knownCounts.set(name, { day: today(), count });
}

function knownNearCap(name, limit) {
  const k = knownCounts.get(name);
  return !!k && k.day === today() && k.count >= limit - SPECULATE_MARGIN;
}

async function handleTranscribe(request, env, timing, ctx) {
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.length === 0) {
    return { text: "" };
  }
  const form = new FormData();
  form.append("file", new Blob([bytes], { type: "audio/wav" }), "audio.wav");
  // X-Stt-Model picks Groq's other Whisper for measurement (A/B against the
  // default, tools/grammar_eval/cloud_stt_ab.py, 2026-10-04). Allow-listed:
  // both have the same free-tier limits, so a test can't reach anything
  // the default couldn't.
  const STT_MODELS = ["whisper-large-v3-turbo", "whisper-large-v3"];
  const requested = request.headers.get("X-Stt-Model");
  const sttModel = STT_MODELS.includes(requested) ? requested : STT_MODELS[0];
  timing.stt_model = sttModel;
  form.append("model", sttModel);
  // X-Hinglish: 1 (2026-10-13, not yet sent by any released app): the
  // speaker mixes Hindi into English. Groq isn't pinned to English, and a
  // Roman-script Hinglish example in the prompt nudges it to write Hindi
  // in English letters; anything still in Indian script is rewritten
  // afterwards (romanizeHinglish). Without the header: English, as before.
  const hinglish = request.headers.get("X-Hinglish") === "1";
  if (!hinglish) {
    form.append("language", "en"); // matches the local model's small.en (English-only)
  }
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
    } catch (e) {
      // ignore
    }
  }
  if (hinglish) {
    prompt = (HINGLISH_STT_PROMPT + " " + prompt).slice(0, 800).trim();
  }
  if (prompt) form.append("prompt", prompt);

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
      if (groqResp.status === 429) {
        const [kind, detail] = groqLimitKind(sttModel, await groqResp.text());
        noteHit(env, ctx, kind, detail);
        groqProblem = kind;
      } else if (groqResp.status >= 500) {
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
      if (fb.turbo_error) {
        timing.turbo_error = fb.turbo_error;
        const kind = workersAiKind(fb.turbo_error);
        if (kind) noteHit(env, ctx, kind, "stt fallback");
      }
      return { text: fb.text, via: fb.via };
    } catch (e) {
      timing.fallback_error = String(e);
      noteHit(env, ctx, workersAiKind(e) || "workers-ai stt error", String(e));
      return BUSY; // same shape as our per-install quota: the client shows "Cloud is busy"
    }
  }
  notePeak(env, ctx, sttModel, groqResp, timing);
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
  let text = result.text || "";
  if (segments) {
    const kept = [];
    timing.segments = segments.map((s) => {
      const silent = s.no_speech_prob > NO_SPEECH_PROB && s.avg_logprob < MIN_AVG_LOGPROB;
      if (!silent) kept.push(s.text || "");
      return [round2(s.no_speech_prob), round2(s.avg_logprob), silent ? 0 : 1];
    });
    text = kept.join("").trim();
  }
  if (!hinglish) {
    return { text, via: "groq" };
  }
  const out = { text, via: "groq", language: result.language || null, hinglish: false };
  if (INDIAN_SCRIPT.test(text) && request.headers.get("X-Hinglish-Rewrite") !== "0") {
    out.stt_text = text;
    const t1 = Date.now();
    out.text = await romanizeHinglish(env, text);
    timing.romanize_ms = Date.now() - t1;
    out.hinglish = true;
  } else if (INDIAN_SCRIPT.test(text) || /hindi|urdu/i.test(result.language || "")) {
    out.hinglish = true;
  }
  return out;
}

// Hinglish (see X-Hinglish in handleTranscribe). The STT prompt shows
// Whisper the target style; the rewrite turns any Devanagari/Urdu script
// it still produced into Roman letters, as Indians type Hindi in chat.
const HINGLISH_STT_PROMPT =
  "Haan, main kal office aaunga. Meeting 4 baje hai, report bhej dena please.";
const INDIAN_SCRIPT = /[\u0900-\u097F\u0600-\u06FF]/;
const ROMANIZE_SYSTEM = (
  "You convert transcribed Hindi-English (Hinglish) speech into the way " +
  "people in India type it in chat. Write Hindi and Urdu words in Roman " +
  "(English) letters with common informal spellings (hai, nahi, kya, " +
  "mujhe, kar raha hoon, theek hai). Write English words, even if they " +
  "were transcribed in Hindi script, in normal English spelling (meeting, " +
  "placement, experience). Write numbers as digits. Do not translate, do " +
  "not add or remove words, keep the word order. Add light punctuation. " +
  "Reply with only the converted text."
);
const ROMANIZE_SHOTS = [
  ["मैं कल ऑफिस नहीं आ पाऊंगा, मीटिंग रिशेड्यूल कर दो",
   "Main kal office nahi aa paunga, meeting reschedule kar do."],
  ["सो फर्स्ट थिंग यू हैव टू अंडरस्टैंड इज़ कि प्लेसमेंट कितना है",
   "So first thing you have to understand is ki placement kitna hai."],
  ["रिपोर्ट पांच बजे तक भेज देना ओके", "Report 5 baje tak bhej dena, okay."],
];

async function romanizeHinglish(env, text) {
  const messages = [{ role: "system", content: ROMANIZE_SYSTEM }];
  for (const [a, b] of ROMANIZE_SHOTS) {
    messages.push({ role: "user", content: a }, { role: "assistant", content: b });
  }
  messages.push({ role: "user", content: text });
  try {
    const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GROQ_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        model: GROQ_GRAMMAR_MODEL, messages, temperature: 0,
        reasoning_effort: "low", include_reasoning: false, max_tokens: 2048,
      }),
    });
    if (r.ok) {
      const out = (await r.json()).choices?.[0]?.message?.content;
      if (out && !INDIAN_SCRIPT.test(out)) return plainText(out.trim());
    }
  } catch (e) {
    // fall through: Indian-script text beats no text
  }
  return text;
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

async function handleGrammar(request, env, timing, ctx) {
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
      notePeak(env, ctx, GROQ_GRAMMAR_MODEL, groqResp, timing);
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
      const body = await groqResp.text();
      groqError = `${groqResp.status} ${body.slice(0, 300)}`;
      if (groqResp.status === 429) {
        const [kind, detail] = groqLimitKind(GROQ_GRAMMAR_MODEL, body);
        noteHit(env, ctx, kind, detail);
      }
    }
  } catch (err) {
    groqError = String(err).slice(0, 300);
  }

  let result;
  try {
    result = await env.AI.run("@cf/meta/llama-3.2-3b-instruct", {
      messages,
      temperature: 0,
    });
  } catch (e) {
    noteHit(env, ctx, workersAiKind(e) || "workers-ai grammar error", String(e));
    throw e;
  }
  return {
    text: result.response || text,
    via: "workers-ai",
    groq_error: groqError,
  };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/limits") {
      // Not the shared secret: that one ships in the public EXE.
      if (!env.ADMIN_KEY || request.headers.get("X-Admin-Key") !== env.ADMIN_KEY) {
        return unauthorized();
      }
      return Response.json(await limitLog(env).report());
    }
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
    const handler = { "/transcribe": handleTranscribe, "/grammar": handleGrammar }[url.pathname];
    if (!handler) {
      return new Response("Not found", { status: 404 });
    }

    // Per-stage server-side timings, returned in each JSON response so
    // cloud latency can be broken down from the client.
    const timing = { colo: request.cf?.colo };
    const tq = Date.now();
    const ipName = await ipQuotaName(request);
    const quotaPromise = Promise.all([
      checkAndIncrementQuota(env, installId, DAILY_QUOTA_PER_INSTALL),
      ipName ? checkAndIncrementQuota(env, ipName, DAILY_QUOTA_PER_IP)
        : Promise.resolve({ ok: true, count: 0 }),
    ]).then(([q, ipq]) => {
      timing.quota_ms = Date.now() - tq;
      timing.quota_count = q.count;
      timing.ip_quota_count = ipq.count;
      rememberCount(installId, q.count);
      if (ipName) rememberCount(ipName, ipq.count);
      return { ok: q.ok && ipq.ok, cap: !q.ok ? "install cap" : !ipq.ok ? "ip cap" : null };
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
    // X-Quota-Sync: 1 waits for the quota checks so the response carries
    // quota_count / ip_quota_count (tests; only slows the caller down).
    const speculative = request.headers.get("X-Quota-Sync") !== "1" &&
      !knownNearCap(installId, DAILY_QUOTA_PER_INSTALL) &&
      !(ipName && knownNearCap(ipName, DAILY_QUOTA_PER_IP));
    timing.speculative = speculative;
    try {
      let payload;
      if (speculative) {
        ctx.waitUntil(quotaPromise);
        payload = await handler(request, env, timing, ctx);
      } else {
        const quota = await quotaPromise;
        if (!quota.ok) {
          noteHit(env, ctx, quota.cap, null);
          return quotaExceeded();
        }
        payload = await handler(request, env, timing, ctx);
      }
      if (payload === BUSY) {
        noteHit(env, ctx, "busy", url.pathname);
        return quotaExceeded();
      }
      return Response.json({ ...payload, timing });
    } catch (err) {
      return Response.json({ error: String(err) }, { status: 500 });
    }
  },
};
