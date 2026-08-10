"""Exp 8 — Shazam back-to-back throttle probe (the B go/no-go risk that can only be measured).

Architecture B makes Shazam a PRIMARY sense, called on every track. ADR-019 only ever ran
Shazam paced at 2s spacing (exp 6). This fires all 26 rips with ZERO spacing from the
residential IP and watches for the failure modes that would sink B: rising latency, empty
responses, or outright errors/bans. A hang is itself a finding, so each call has a hard 30s
timeout mapped to an error (this is also the fail-soft the R1.5 spec review flagged as missing).

Run with the 3.12 Shazam venv:  .venv-shazam/bin/python spike/throttle_probe.py
"""
import asyncio
import json
import re
import time
from pathlib import Path

from shazamio import Shazam

HERE = Path(__file__).resolve().parent
AUD = HERE / "audio"
OUT = HERE / "throttle.jsonl"
CALL_TIMEOUT_S = 30.0

files = sorted(p for p in AUD.glob("*") if p.suffix not in (".part", ".db"))


async def recognize(shazam, path):
    t0 = time.perf_counter()
    try:
        out = await asyncio.wait_for(shazam.recognize(str(path)), timeout=CALL_TIMEOUT_S)
        t = out.get("track") or {}
        return {
            "shazam_artist": t.get("subtitle"),
            "shazam_title": t.get("title"),
            "isrc": t.get("isrc"),
            "matched": bool(t),
            "shazam_s": round(time.perf_counter() - t0, 2),
            "error": None,
        }
    except asyncio.TimeoutError:
        return {"matched": False, "error": "timeout",
                "shazam_s": round(time.perf_counter() - t0, 2)}
    except Exception as exc:  # noqa: BLE001 — fail-soft
        return {"matched": False, "error": f"{type(exc).__name__}: {exc}",
                "shazam_s": round(time.perf_counter() - t0, 2)}


async def main():
    shazam = Shazam()
    rows = []
    run_t0 = time.perf_counter()
    with OUT.open("w") as fh:
        for p in files:
            m = re.match(r"(\d+)_([^.]+)", p.name)
            idx = int(m.group(1)) if m else -1
            vid = m.group(2) if m else p.stem
            rec = {"id": idx, "video_id": vid, "file": p.name}
            rec.update(await recognize(shazam, p))       # NO sleep — back-to-back on purpose
            rows.append(rec)
            tag = (f"{rec['shazam_artist']} - {rec['shazam_title']}"
                   if rec["matched"] else f"NO MATCH ({rec['error'] or 'empty'})")
            print(f"[{idx:2}] {rec['shazam_s']:6.2f}s  {tag[:58]}", flush=True)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
    total = time.perf_counter() - run_t0

    # Verdict: did back-to-back degrade vs the paced exp-6 run?
    lat = [r["shazam_s"] for r in rows]
    matched = [r for r in rows if r["matched"]]
    errors = [r for r in rows if not r["matched"]]
    first_half = lat[: len(lat) // 2]
    second_half = lat[len(lat) // 2:]
    print(f"\n=== EXP 8 — back-to-back throttle probe (n={len(rows)}) ===")
    print(f"  total wall        : {total:.1f}s   (paced exp-6 was ~2s/song by construction)")
    print(f"  matched / error   : {len(matched)} / {len(errors)}")
    if errors:
        print(f"  errors            : {[(r['id'], r['error']) for r in errors]}")
    print(f"  latency  min/med/max: {min(lat):.2f} / {sorted(lat)[len(lat)//2]:.2f} / {max(lat):.2f}s")
    print(f"  1st-half vs 2nd-half median: "
          f"{sorted(first_half)[len(first_half)//2]:.2f}s  vs  "
          f"{sorted(second_half)[len(second_half)//2]:.2f}s   (rising = throttling)")
    print(f"\n  READ: if error rate ~0 and 2nd-half median not materially higher, Shazam "
          f"sustains B's per-track cadence. Rising latency/errors => it is the new floor.")


asyncio.run(main())
