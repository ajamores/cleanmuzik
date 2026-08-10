"""Exp 7 / lock 3 — measure the REAL latency of the production adjudication call.

The one thing the API key unlocks: how long does one Haiku adjudication call actually
take, made the way R1.5 production would make it (Python → api.anthropic.com). Path B's
other half (Shazam) is already measured (median 1.58s). B_identity ≈ Shazam + Haiku;
art-bytes + LRCLIB fetch parallelize off the critical path (different servers, not behind
MusicBrainz's 1/sec floor). Compare against the measured beets-chain baseline: 11s park /
37s auto-land.

Reads ANTHROPIC_APIKEY explicitly (project convention; SDK default is ANTHROPIC_API_KEY).
System prompt (the rubric) is cache_control'd so warm calls reflect production steady state.
Run with the app venv (anthropic installed there):  .venv/bin/python spike/speed_haiku.py
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
key = None
for line in (HERE.parent.parent / ".env").read_text().splitlines():
    if line.startswith("ANTHROPIC_APIKEY="):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
client = anthropic.Anthropic(api_key=key)
MODEL = "claude-haiku-4-5"

SYSTEM = (
    "You are an identity adjudicator for a music tagging pipeline. You do NOT identify "
    "songs from scratch. Given a fingerprint verdict, MusicBrainz candidates, YouTube "
    "signals, and a Shazam guess, decide CONFIRM (accept the fingerprint's match) or "
    "PARK (send to human review). When a confident fingerprint exists you may only "
    "confirm its match or park — never switch to a different recording. Reply with a "
    "single JSON object: {\"verdict\":\"accept\"|\"park\",\"chosen_mbid\":<string|null>,"
    "\"confidence\":0.0-1.0,\"reason\":\"<one line>\"}. No prose outside the JSON."
)

blind = json.loads((HERE / "blinded.json").read_text())
sample = blind[:12]  # enough for a stable median


def call(row):
    user = json.dumps({
        "youtube": row["youtube"],
        "acoustid": row["acoustid"],
        "musicbrainz_candidates": row["musicbrainz_candidates"],
        "shazam": None,
    })
    t0 = time.perf_counter()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    dt = time.perf_counter() - t0
    return dt, msg.usage


lat = []
print(f"model={MODEL}  n={len(sample)}")
for i, row in enumerate(sample):
    dt, usage = call(row)
    warm = getattr(usage, "cache_read_input_tokens", 0) or 0
    tag = "warm" if warm else "COLD"
    print(f"  [{row['id']:2}] {dt:5.2f}s  {tag}  in={usage.input_tokens} "
          f"cache_read={warm} out={usage.output_tokens}", flush=True)
    lat.append(dt)

# first call pays cold cache-write + schema; steady-state is the rest
cold = lat[0]
warm_lat = lat[1:]
print(f"\ncold first call : {cold:.2f}s")
print(f"warm calls      : median {statistics.median(warm_lat):.2f}s  "
      f"min {min(warm_lat):.2f}  max {max(warm_lat):.2f}  (n={len(warm_lat)})")
print(f"\n=== PATH B identity latency (Shazam median 1.58s + Haiku warm median) ===")
b = 1.58 + statistics.median(warm_lat)
print(f"  B ≈ {b:.2f}s   vs  A baseline: 10.96s (park) / 36.20s (auto-land)")
print(f"  speedup vs auto-land: {36.20 / b:.1f}x")
