"""Spike capture run — build the offline fixture every experiment replays against.

For each of the 26 corpus video IDs, runs the REAL identify path (download → transcode →
AcoustID fingerprint → MusicBrainz candidate search) in ISOLATION, and records per song:

  - source_signals : the yt-dlp info dict download.py:299 discards (title, uploader,
                     channel_is_topic from the "- Topic" suffix, description head, tags,
                     duration, video_id) — the LLM's non-audio evidence.
  - candidates     : beets' MusicBrainz candidate list at choose_item time — recording
                     MBID, artist/title/album, tag-distance. THE data lock 1b needs
                     (candidates for the *landed* songs, which SSE never emits).
  - dominance      : the AcoustID verdict — top_score, gap, top recording MBIDs.
  - outcome        : what the real gate did this run (landed / review / skipped).
  - ground_truth   : the corpus label (done = fingerprint was accepted historically).
  - timing         : total wall + the AcoustID dominance-lookup seconds.

Isolation (per CLAUDE.md's standing hazard + run_isolated.py): temp DB_PATH, temp beets
LIBRARY_DIRECTORY patched in both modules, JELLYFIN_API_KEY blanked. Nothing touches
/mnt/c or the real DB. Run with cwd=server:  .venv/bin/python spike/capture.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # server/ onto path

# --- isolation: set BEFORE importing app modules (they read DB_PATH at first use) ---
ROOT = Path(tempfile.mkdtemp(prefix="cleanmuzik-spike-"))
os.environ["DB_PATH"] = str(ROOT / "data" / "cleanmuzik.db")
os.environ["JELLYFIN_API_KEY"] = ""  # never touch the real Jellyfin (ADR-008)
(ROOT / "data").mkdir(parents=True, exist_ok=True)
LIB = ROOT / "library"
LIB.mkdir(parents=True, exist_ok=True)

import yt_dlp  # noqa: E402

import app.beets_engine as be  # noqa: E402
import app.import_seam as seam  # noqa: E402
from app.db import Store  # noqa: E402
from app.download import download_song  # noqa: E402
from app.import_seam import FingerprintTrustSession  # noqa: E402
from app.jobs import JobRegistry, run_pipeline  # noqa: E402
from app.transcode import transcode_to_mp3_320  # noqa: E402

be.LIBRARY_DIRECTORY = str(LIB)
seam.LIBRARY_DIRECTORY = str(LIB)
print(f"[iso] DB_PATH={os.environ['DB_PATH']}", file=sys.stderr)
print(f"[iso] LIBRARY_DIRECTORY={be.LIBRARY_DIRECTORY}", file=sys.stderr)

HERE = Path(__file__).resolve().parent
manifest = json.loads((HERE / "corpus_manifest.json").read_text())
corpus = manifest["corpus"]
_LIMIT = int(os.environ.get("SPIKE_LIMIT", "0"))
if _LIMIT:
    corpus = corpus[:_LIMIT]

# --- choose_item hook: capture candidates + dominance without a second AcoustID call ---
# The real choose_item calls self.dominance_fn(path) once. We wrap that fn per session to
# memoize its result, run the REAL choose_item, then read the memoized dominance + the
# task.candidates it decided over. One network lookup, real decision, full capture.
_CAP: dict = {}
_real_choose = FingerprintTrustSession.choose_item


def _cand_row(candidate):
    info = getattr(candidate, "info", None)
    if info is None:
        return None
    dist = getattr(candidate, "distance", None)
    try:
        dist = float(dist) if dist is not None else None
    except Exception:
        dist = None
    return {
        "recording_mbid": getattr(info, "track_id", None),
        "artist": getattr(info, "artist", None),
        "title": getattr(info, "title", None),
        "album": getattr(info, "album", None),
        "distance": dist,
    }


def _capturing_choose_item(self, task):
    if not hasattr(self, "_spike_dom_cache"):
        real_fn = self.dominance_fn
        cache = {}

        def memo(path):
            if path not in cache:
                cache[path] = real_fn(path)
            return cache[path]

        self.dominance_fn = memo
        self._spike_dom_cache = cache
    result = _real_choose(self, task)
    dom = None
    for v in self._spike_dom_cache.values():
        dom = v  # singleton import: exactly one path
    _CAP["candidates"] = [r for c in (task.candidates or []) if (r := _cand_row(c))]
    _CAP["dominance"] = (
        None
        if dom is None
        else {
            "top_score": dom.top_score,
            "runner_up_score": dom.runner_up_score,
            "gap": dom.gap,
            "top_recording_ids": list(dom.top_recording_ids),
        }
    )
    _CAP["item_tags"] = {
        "artist": getattr(task.item, "artist", None),
        "title": getattr(task.item, "title", None),
        "album": getattr(task.item, "album", None),
    }
    return result


FingerprintTrustSession.choose_item = _capturing_choose_item


def source_signals(url: str) -> dict:
    """The info dict download.py discards — metadata only, no media pull."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True, "extract_flat": False}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    ch = info.get("channel") or info.get("uploader") or ""
    tags = info.get("tags") or []
    desc = (info.get("description") or "")[:600]
    return {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "channel": info.get("channel"),
        "channel_is_topic": str(ch).endswith("- Topic"),
        "duration_s": info.get("duration"),
        "tags": tags[:25],
        "description_head": desc,
        "artist_field": info.get("artist"),
        "track_field": info.get("track"),
    }


def main():
    out = HERE / "capture.jsonl"
    store = Store(Path(os.environ["DB_PATH"]))
    store.init_schema()
    n = len(corpus)
    with out.open("w") as fh:
        for i, row in enumerate(corpus, 1):
            vid, url, label = row["video_id"], row["url"], row["label"]
            print(f"\n[{i}/{n}] {label:6} {vid}", flush=True)
            rec = {"video_id": vid, "url": url, "ground_truth": label}
            t0 = time.perf_counter()
            rec["source_signals"] = source_signals(url)
            _CAP.clear()
            try:
                job = store.create_job(url)
                state = run_pipeline(
                    job.id, url,
                    store=store, registry=JobRegistry(), staging_root=ROOT / "staging",
                    download_fn=download_song,
                    transcode_fn=transcode_to_mp3_320,
                    scan_fn=lambda **k: True,  # never hit real Jellyfin
                )
                rec["outcome"] = {"status": state.status,
                                  "stage": getattr(state, "stage", None),
                                  "error": getattr(state, "error", None)}
            except Exception as exc:  # noqa: BLE001 — one failure continues the batch
                rec["outcome"] = {"status": "harness_error",
                                  "error": f"{type(exc).__name__}: {exc}"}
            rec["candidates"] = _CAP.get("candidates")
            rec["dominance"] = _CAP.get("dominance")
            rec["item_tags"] = _CAP.get("item_tags")
            rec["wall_s"] = round(time.perf_counter() - t0, 2)
            title = (rec["source_signals"] or {}).get("title") or ""
            dom = rec["dominance"]
            print(f"    -> {rec['outcome']['status']:14} "
                  f"score={dom['top_score']:.3f} " if dom else "    -> "
                  f"{rec['outcome']['status']:14} score=n/a ", end="", flush=True)
            print(f"cands={len(rec['candidates'] or [])} {rec['wall_s']}s  {title[:50]}",
                  flush=True)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
