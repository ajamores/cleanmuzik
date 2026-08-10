"""Phase A of the Shazam arm: download all 26 corpus rips into spike/audio/, retained
and resumable, using the app's HARDENED download_song (a bare yt-dlp config gets 403'd).
Skips any id already present. Stops loudly if 403/bot-checks pile up (throttle guard).
Run: .venv/bin/python spike/download_corpus.py   (the 3.14 app venv)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DB_PATH", str(Path(tempfile.mkdtemp()) / "x.db"))
import json

from app.download import download_song

HERE = Path(__file__).resolve().parent
AUD = HERE / "audio"
AUD.mkdir(exist_ok=True)
corpus = json.loads((HERE / "corpus_manifest.json").read_text())["corpus"]

forbidden = 0
for i, row in enumerate(corpus):
    vid, url = row["video_id"], row["url"]
    existing = list(AUD.glob(f"{i:02d}_{vid}.*"))
    if existing:
        print(f"[{i:2}] have {existing[0].name}", flush=True)
        continue
    tmp = Path(tempfile.mkdtemp(prefix="cmz-"))
    try:
        p = download_song(url, tmp)
        dest = AUD / f"{i:02d}_{vid}{p.suffix}"
        p.replace(dest)
        print(f"[{i:2}] downloaded {dest.name}", flush=True)
        forbidden = 0
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        print(f"[{i:2}] FAIL {vid}: {msg[:100]}", flush=True)
        if "403" in msg or "Forbidden" in msg or "bot" in msg.lower():
            forbidden += 1
            if forbidden >= 3:
                print("\n!! 3 consecutive 403/bot errors — residential IP throttling. STOPPING.",
                      flush=True)
                break
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

have = sorted(p.name for p in AUD.glob("*") if p.suffix != ".part")
print(f"\naudio present: {len(have)}/26")
