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

const DAILY_QUOTA_PER_INSTALL = 300; // combined /transcribe + /grammar calls

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

function unauthorized() {
  return new Response("Unauthorized", { status: 401 });
}

function quotaExceeded() {
  return Response.json(
    { error: "daily quota exceeded" },
    { status: 429 }
  );
}

// One read + (on success) one write per allowed request, against a
// per-install-per-day key. KV's free tier caps at 1,000 writes/day
// account-wide (not per-key) and 1 write/sec per key -- fine at today's
// scale (a handful to a few dozen daily users), but the fix if that's
// ever actually hit is upgrading to Workers Paid ($5/mo, removes the
// write cap), not a redesign of this function.
async function checkAndIncrementQuota(env, installId) {
  const day = new Date().toISOString().slice(0, 10); // YYYY-MM-DD (UTC)
  const key = `quota:${installId}:${day}`;
  const current = parseInt((await env.QUOTA.get(key)) || "0", 10);
  if (current >= DAILY_QUOTA_PER_INSTALL) {
    return false;
  }
  // expirationTtl in seconds; 2 days covers the UTC-day boundary safely.
  await env.QUOTA.put(key, String(current + 1), { expirationTtl: 172800 });
  return true;
}

async function handleTranscribe(request, env) {
  const bytes = new Uint8Array(await request.arrayBuffer());
  if (bytes.length === 0) {
    return Response.json({ text: "" });
  }
  const form = new FormData();
  form.append("file", new Blob([bytes], { type: "audio/wav" }), "audio.wav");
  form.append("model", "whisper-large-v3-turbo");
  form.append("language", "en"); // matches the local model's small.en (English-only)
  form.append("response_format", "json");

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
  return Response.json({ text: result.text || "" });
}

async function handleGrammar(request, env) {
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

  const result = await env.AI.run("@cf/meta/llama-3.2-3b-instruct", {
    messages,
    temperature: 0,
  });
  return Response.json({ text: result.response || text });
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
    if (!(await checkAndIncrementQuota(env, installId))) {
      return quotaExceeded();
    }
    const url = new URL(request.url);
    try {
      if (url.pathname === "/transcribe") {
        return await handleTranscribe(request, env);
      }
      if (url.pathname === "/grammar") {
        return await handleGrammar(request, env);
      }
    } catch (err) {
      return Response.json({ error: String(err) }, { status: 500 });
    }
    return new Response("Not found", { status: 404 });
  },
};
