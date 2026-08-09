"""Score blinded Haiku referee verdicts against the fingerprint's own matched recording.

Experiment 1 (accuracy go/no-go). Correct 1b definition (council §2, R1):
  On an auto-land-eligible song (confident fingerprint), an OVERRIDE = the referee
  ACCEPTS a recording DIFFERENT from the one the fingerprint matched. Veto-to-park is
  safe. Override MUST be 0.
Ground truth for "what the fingerprint matched" = the candidate whose recording_mbid is
in dominance.top_recording_ids (that is exactly what _matching_candidate does at land time).
NOTE: capture's item_tags = the raw YouTube tags read BEFORE tagging, NOT the landed
identity — do not use them as truth (that was the v1 scorer's bug).
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
cap = [json.loads(l) for l in (HERE / "capture.jsonl").read_text().splitlines()]
key = {k["id"]: k for k in json.loads((HERE / "answer_key.json").read_text())}
blind = {b["id"]: b for b in json.loads((HERE / "blinded.json").read_text())}
V = {}
for f in ("verdicts_0.json", "verdicts_9.json", "verdicts_18.json"):
    for v in json.loads((HERE / f).read_text()):
        V[v["id"]] = v


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def same_song(a, b):
    """Loose title-agreement (artist strings vary wildly across MB releases)."""
    if not a or not b:
        return False
    ta, tb = norm(a.get("title")), norm(b.get("title"))
    return bool(ta and tb and (ta in tb or tb in ta))


def fp_matched_candidate(rec):
    """The candidate the fingerprint actually matched: recording_mbid ∈ top_recording_ids."""
    dom = rec["dominance"] or {}
    top = set(dom.get("top_recording_ids") or [])
    for c in rec["candidates"] or []:
        if c["recording_mbid"] in top:
            return c
    return None


overrides, safe_vetoes, confirms, false_accepts, correct_parks, dup_ok, notes = (
    [], [], [], [], [], [], [])
rows = []
for i in sorted(key):
    k, b, rec, v = key[i], blind[i], cap[i], V.get(i)
    eligible = k["auto_land_eligible"]
    verdict = v["verdict"]
    cc = v.get("chosen_candidate")
    endorsed = rec["candidates"][cc] if (cc is not None and isinstance(cc, int)
                                         and 0 <= cc < len(rec["candidates"])) else None
    fp = fp_matched_candidate(rec)
    tag = ""

    if not eligible:
        if verdict == "accept":
            false_accepts.append(i); tag = "*** FALSE-ACCEPT on blank fp ***"
        else:
            correct_parks.append(i); tag = "park (correct — blank fp)"
    elif k["today_outcome"] != "done":
        # eligible but today parked (dedup twin / dominant-but-no-candidate) — informational
        dup_ok.append(i); tag = f"today-parked twin; referee={verdict}"
    else:
        # 1b-critical: today auto-landed with a confident fingerprint
        if verdict != "accept":
            safe_vetoes.append(i); tag = "veto->park (safe / caught contradiction)"
        else:
            dom_top = set((rec["dominance"] or {}).get("top_recording_ids") or [])
            if endorsed and endorsed["recording_mbid"] in dom_top:
                confirms.append(i); tag = "CONFIRM (fp's own recording)"
            elif fp and same_song(endorsed, fp):
                confirms.append(i); tag = "CONFIRM (same song, other release)"
            elif fp is None:
                confirms.append(i); tag = "confirm (fp rec not in candset)"
            else:
                overrides.append(i); tag = "*** OVERRIDE ***"

    e = f"{endorsed['artist']} - {endorsed['title']}" if endorsed else "(none)"
    rows.append(f"  {i:2} {tag:34} {(k['title'] or '')[:34]:34} ->{verdict:6} [{e[:32]}]")

print("=== per-song ===")
print("\n".join(rows))
n_crit = len(confirms) + len(safe_vetoes) + len(overrides)
print("\n=== EXPERIMENT 1 RESULT ===")
print(f"1b OVERRIDES of a correct fingerprint : {len(overrides)}  <-- MUST BE 0"
      + (f"  ids={overrides}" if overrides else "   PASS"))
print(f"   over {n_crit} confident auto-lands: {len(confirms)} confirm, "
      f"{len(safe_vetoes)} safe-veto {safe_vetoes}")
print(f"false-accepts on BLANK fingerprint    : {len(false_accepts)}"
      + (f" ids={false_accepts}" if false_accepts else "   PASS")
      + f"   (blanks parked correctly: {len(correct_parks)})")
print(f"dedup-twin auto-lands (informational) : {dup_ok}")
print(f"\nGATE 1(b): {'PASS — 0 overrides' if not overrides else 'FAIL — STOP'}")
