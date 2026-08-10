"""Full architecture-B head-to-head: fingerprint + Shazam + yt-dlp -> ISRC->MB for real facts
-> one LLM reconcile call -> final identity + genre/mood. Times each real call and scores the
identity against the answer key, then prints B vs today's A baseline.

B's identity+facts latency = Shazam (measured, throttle.jsonl) + ISRC->MB lookup + LLM reconcile.
Everything else B needs (cover-art bytes, LRCLIB lyrics) parallelises off this critical path, as
in exp 7. A baseline is the instrumented today-chain: ~11s (park) / ~37s (auto-land).

Reads ANTHROPIC_APIKEY explicitly (project convention). Run with the APP venv (anthropic +
stdlib http):  .venv/bin/python spike/b_flow.py
"""
import json
import re
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
UA = "CleanMuzik-spike/1.0 ( armand.amores1@gmail.com )"
MODEL = "claude-haiku-4-5"
A_PARK, A_AUTOLAND = 10.96, 36.20   # instrumented today-chain baselines (council §2a)

key = None
for line in (ROOT / ".env").read_text().splitlines():
    if line.startswith("ANTHROPIC_APIKEY="):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
client = anthropic.Anthropic(api_key=key)

blind = {r["id"]: r for r in json.loads((HERE / "blinded.json").read_text())}
answer = {r["id"]: r for r in json.loads((HERE / "answer_key.json").read_text())}
shz_path = HERE / "throttle.jsonl"
if not shz_path.exists():
    shz_path = HERE / "shazam.jsonl"      # fall back to the paced run if probe not yet run
shazam = {r["id"]: r for r in (json.loads(l) for l in shz_path.read_text().splitlines())}
print(f"shazam source: {shz_path.name}")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def isrc_to_mb(isrc):
    """One exact MusicBrainz lookup by ISRC -> real recording MBID + artist/title. This is the
    'keep the facts real, fast' step B depends on. Rate-limited 1/sec per MB policy."""
    if not isrc:
        return None, 0.0
    url = f"https://musicbrainz.org/ws/2/isrc/{urllib.parse.quote(isrc)}?fmt=json&inc=artist-credits"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        dt = time.perf_counter() - t0
        recs = data.get("recordings") or []
        if not recs:
            return None, dt
        r = recs[0]
        ac = r.get("artist-credit") or [{}]
        return {"mbid": r.get("id"), "title": r.get("title"),
                "artist": "".join(c.get("name", "") + (c.get("joinphrase", "") or "") for c in ac)}, dt
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}"}, time.perf_counter() - t0


SYSTEM = (
    "You reconcile a music track's identity from several senses, then tag it. You are given "
    "YouTube signals, an acoustic fingerprint (AcoustID score + MusicBrainz candidates), a Shazam "
    "guess, and — when available — a REAL MusicBrainz record resolved from Shazam's ISRC (trust its "
    "mbid/artist/title as fact; never invent an mbid). Rules: if the fingerprint is confident you "
    "may CONFIRM its match or PARK to human review, never switch to a different recording; if it is "
    "weak, you may identify from Shazam/ISRC. Author genre and mood freely (opinion). Reply with ONE "
    "JSON object: {\"verdict\":\"accept\"|\"park\",\"artist\":<str>,\"title\":<str>,"
    "\"mbid\":<str|null>,\"genre\":<str>,\"mood\":<str>,\"reason\":\"<one line>\"}. JSON only."
)


def reconcile(payload):
    t0 = time.perf_counter()
    msg = client.messages.create(
        model=MODEL, max_tokens=300,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    dt = time.perf_counter() - t0
    txt = msg.content[0].text
    m = re.search(r"\{.*\}", txt, re.S)
    return (json.loads(m.group(0)) if m else {"error": "unparsed", "raw": txt[:120]}), dt


rows, mb_hit, mb_correct, id_correct, pa_caught = [], 0, 0, 0, None
print(f"model={MODEL}  n={len(blind)}\n")
for i in sorted(blind):
    b, a, s = blind[i], answer[i], shazam.get(i, {})
    isrc = s.get("isrc")
    mb, mb_s = isrc_to_mb(isrc)
    time.sleep(1.1)                       # MB 1/sec floor — the one network limit B keeps
    if mb and "mbid" in mb:
        mb_hit += 1
        if norm(mb.get("title")) and norm(mb["title"]) in norm(a["title"]) or \
           norm(a["title"]) in norm(mb.get("title") or "x"):
            mb_correct += 1
    payload = {"youtube": b["youtube"], "acoustid": b["acoustid"],
               "musicbrainz_candidates": b["musicbrainz_candidates"],
               "shazam": {"artist": s.get("shazam_artist"), "title": s.get("shazam_title"),
                          "isrc": isrc} if s.get("matched") else None,
               "isrc_musicbrainz": mb if (mb and "mbid" in mb) else None}
    v, llm_s = reconcile(payload)
    shz_s = s.get("shazam_s", 0.0) or 0.0
    b_time = shz_s + mb_s + llm_s

    # score identity against the answer key's landed identity (or title ground-truth)
    want = a.get("landed_as") or {}
    got_ok = bool(norm(v.get("title")) and (norm(v.get("title")) in norm(want.get("title") or a["title"])
              or norm(want.get("title") or a["title"]) in norm(v.get("title"))))
    if got_ok:
        id_correct += 1
    if i == 7:                            # the Pa Salieu marquee mistag
        pa_caught = (v.get("verdict") == "park")
    rows.append({"id": i, "b_time": b_time, "shz": shz_s, "mb": mb_s, "llm": llm_s,
                 "verdict": v.get("verdict"), "artist": v.get("artist"), "title": v.get("title"),
                 "genre": v.get("genre"), "ok": got_ok, "mb_hit": bool(mb and "mbid" in mb)})
    print(f"[{i:2}] B={b_time:5.2f}s (shz {shz_s:.2f}+mb {mb_s:.2f}+llm {llm_s:.2f})  "
          f"{v.get('verdict','?'):5}  {'OK ' if got_ok else 'XX '}"
          f"{(v.get('artist') or '')[:22]:22} - {(v.get('title') or '')[:24]:24} "
          f"g={v.get('genre','')[:14]}", flush=True)

bt = [r["b_time"] for r in rows]
n = len(rows)
print(f"\n=== B FULL-FLOW HEAD-TO-HEAD (n={n}) ===")
print(f"  B identity+facts latency : median {statistics.median(bt):.2f}s  "
      f"min {min(bt):.2f}  max {max(bt):.2f}")
print(f"  A baseline (today chain) : {A_PARK:.1f}s park / {A_AUTOLAND:.1f}s auto-land")
print(f"  speedup vs auto-land     : {A_AUTOLAND / statistics.median(bt):.1f}x   "
      f"vs park: {A_PARK / statistics.median(bt):.1f}x")
print(f"  ISRC->MB hit / correct   : {mb_hit}/{n}  ({mb_correct} title-correct)")
print(f"  B identity correct       : {id_correct}/{n}  ({100*id_correct//n}%)")
print(f"  Pa Salieu (id 7) caught  : {pa_caught}   (True = B parked the mistag, correct)")
print(f"  A today identity correct : {sum(1 for a in answer.values() if a['today_outcome']=='done')}/{n}"
      f"  (today_outcome=='done'; note today MIS-lands id 7 as Vanessa Bling)")
(HERE / "b_flow_results.json").write_text(json.dumps(rows, indent=2))
print(f"\nwrote spike/b_flow_results.json")
