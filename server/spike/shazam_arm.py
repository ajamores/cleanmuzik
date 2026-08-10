"""Phase B of the Shazam arm (exp 6, reliability). For each retained rip in spike/audio/,
run ShazamIO recognize and record identity + ISRC + timing + any error. Paced one-at-a-time
with a small delay (this is NOT the deliberate back-to-back throttle probe, exp 8).
Run: .venv-shazam/bin/python spike/shazam_arm.py   (the 3.12 shazam venv)
"""
import asyncio
import json
import re
import time
from pathlib import Path

from shazamio import Shazam

HERE = Path(__file__).resolve().parent
AUD = HERE / "audio"
OUT = HERE / "shazam.jsonl"
DELAY_S = 2.0  # gentle spacing; exp 8 measures true back-to-back behaviour separately

files = sorted(p for p in AUD.glob("*") if p.suffix not in (".part", ".db"))


async def recognize(shazam, path):
    t0 = time.perf_counter()
    try:
        out = await shazam.recognize(str(path))
        t = out.get("track") or {}
        return {
            "shazam_artist": t.get("subtitle"),
            "shazam_title": t.get("title"),
            "isrc": t.get("isrc"),
            "matched": bool(t),
            "shazam_s": round(time.perf_counter() - t0, 2),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — fail-soft: a Shazam miss must never crash the pipeline
        return {"matched": False, "error": f"{type(exc).__name__}: {exc}",
                "shazam_s": round(time.perf_counter() - t0, 2)}


async def main():
    shazam = Shazam()
    with OUT.open("w") as fh:
        for p in files:
            m = re.match(r"(\d+)_([^.]+)", p.name)
            idx = int(m.group(1)) if m else -1
            vid = m.group(2) if m else p.stem
            rec = {"id": idx, "video_id": vid, "file": p.name}
            rec.update(await recognize(shazam, p))
            tag = (f"{rec['shazam_artist']} - {rec['shazam_title']}"
                   if rec["matched"] else f"NO MATCH ({rec['error'] or 'empty'})")
            print(f"[{idx:2}] {rec['shazam_s']:5.2f}s  {tag[:60]}", flush=True)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            await asyncio.sleep(DELAY_S)
    print(f"\nwrote {OUT}  ({len(files)} songs)")


asyncio.run(main())
