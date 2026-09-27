"""Run one CTranslate2 grammar-model candidate over the eval set.

usage: python evaluate.py <model_key> [--shots N]

Candidates other than the shipped model are read from ct2/<key>/ here
(gitignored); see README.md for the conversion recipe.

Uses the app's own _SYSTEM / _SHOTS / validate() so results reflect what
would ship. Every candidate runs with the two free speedups (6 intra
threads, static_prompt caching of the system + few-shot prefix) so the
comparison is model vs model, not config vs config.
"""
import json, os, re, sys, time
sys.path.insert(0, r"C:\Users\sumit\Projects\Talkative")
import ctranslate2
from tokenizers import Tokenizer
from talkative import grammar_engine as ge

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hard_cases import CASES

MODELS = {
    "qwen25-1.5b": dict(path=str(ge.engine_dir()), fmt="chatml", end="<|im_end|>"),
    "gemma3-1b": dict(path=os.path.join(HERE, "ct2", "gemma3-1b"), fmt="gemma", end="<end_of_turn>"),
    "llama32-1b": dict(path=os.path.join(HERE, "ct2", "llama32-1b"), fmt="llama3", end="<|eot_id|>"),
    "qwen25-0.5b": dict(path=os.path.join(HERE, "ct2", "qwen25-0.5b"), fmt="chatml", end="<|im_end|>"),
}


def render(fmt, system, shots, user):
    if fmt == "chatml":
        pre = f"<|im_start|>system\n{system}<|im_end|>\n"
        for s, c in shots:
            pre += f"<|im_start|>user\n{s}<|im_end|>\n<|im_start|>assistant\n{c}<|im_end|>\n"
        return pre, f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"
    if fmt == "gemma":  # no system role: fold it into the first user turn
        pre = ""
        first = True
        for s, c in shots:
            u = f"{system}\n\n{s}" if first else s
            first = False
            pre += f"<start_of_turn>user\n{u}<end_of_turn>\n<start_of_turn>model\n{c}<end_of_turn>\n"
        return pre, f"<start_of_turn>user\n{user}<end_of_turn>\n<start_of_turn>model\n"
    if fmt == "llama3":
        h = lambda r: f"<|start_header_id|>{r}<|end_header_id|>\n\n"
        pre = h("system") + system + "<|eot_id|>"
        for s, c in shots:
            pre += h("user") + s + "<|eot_id|>" + h("assistant") + c + "<|eot_id|>"
        return pre, h("user") + user + "<|eot_id|>" + h("assistant")
    raise ValueError(fmt)


def main():
    key = sys.argv[1]
    nshots = int(sys.argv[sys.argv.index("--shots") + 1]) if "--shots" in sys.argv else len(ge._SHOTS)
    cfg = MODELS[key]
    tok = Tokenizer.from_file(os.path.join(cfg["path"], "tokenizer.json"))
    gen = ctranslate2.Generator(cfg["path"], device="cpu", compute_type="int8", intra_threads=6)
    shots = ge._SHOTS[:nshots]

    # Private: real dictations from this machine's debug.log, built by
    # extract_log_cases.py and gitignored. Optional -- the hand-written
    # cases alone still run.
    lc = os.path.join(HERE, "log_cases.json")
    log_cases = json.load(open(lc, encoding="utf-8")) if os.path.exists(lc) else []
    items = [dict(cat=c, input=i, keep=k, avoid=a) for c, i, k, a in CASES]
    items += [dict(cat="log", input=x["input"], keep=[], avoid=[], cloud_ref=x["cloud_ref"]) for x in log_cases]

    prefix_text, _ = render(cfg["fmt"], ge._SYSTEM, shots, "x")
    prefix = tok.encode(prefix_text).tokens  # adds BOS where the tokenizer wants one

    def clean(text):
        _, rest_text = render(cfg["fmt"], ge._SYSTEM, shots, text)
        rest = tok.encode(rest_text, add_special_tokens=False).tokens
        t = time.perf_counter()
        r = gen.generate_batch([rest], static_prompt=prefix, max_length=len(rest) + 250,
                               sampling_temperature=0, include_prompt_in_result=False,
                               end_token=cfg["end"])[0]
        dt = time.perf_counter() - t
        out = tok.decode(r.sequences_ids[0], skip_special_tokens=True).strip()
        out = re.sub(r"^<think>.*?</think>\s*", "", out, flags=re.DOTALL).strip()
        return out, dt, len(r.sequences_ids[0])

    clean("warm up the static prompt cache")
    results = []
    for it in items:
        out, dt, n = clean(it["input"])
        low = out.lower()
        it.update(output=out, secs=round(dt, 2), out_tokens=n,
                  guards_ok=ge.validate(it["input"], out),
                  keep_missing=[k for k in it["keep"] if k not in low],
                  avoid_hit=[a for a in it["avoid"] if a in low],
                  unchanged=(out.strip() == it["input"].strip()))
        results.append(it)
        flag = "" if it["guards_ok"] and not it["keep_missing"] and not it["avoid_hit"] else "  <-- FLAG"
        print(f"[{it['cat']:8}] {dt:5.2f}s {'ok ' if it['guards_ok'] else 'REJ'}{flag}\n   in : {it['input'][:150]}\n   out: {out[:150]}")

    tag = key + (f"-shots{nshots}" if nshots != len(ge._SHOTS) else "")
    json.dump(dict(model=tag, prefix_tokens=len(prefix), results=results),
              open(os.path.join(HERE, f"results_{tag}.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    n = len(results)
    rej = sum(not r["guards_ok"] for r in results)
    miss = sum(bool(r["keep_missing"] or r["avoid_hit"]) for r in results)
    secs = sorted(r["secs"] for r in results)
    print(f"\n== {tag}: {n} cases | guard rejections {rej} | meaning flags {miss} | "
          f"median {secs[n // 2]:.2f}s  p90 {secs[int(n * .9)]:.2f}s  max {secs[-1]:.2f}s  total {sum(secs):.1f}s")


if __name__ == "__main__":
    main()
