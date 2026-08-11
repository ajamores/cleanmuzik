"""The reconcile seam — build evidence, ask the LLM to adjudicate, return a `Verdict`.

This is the R1.5 identity-stage brain (T-204, spec §5/§6). Three senses have already
been gathered upstream — the yt-dlp `SourceSignals` (T-201), the Shazam record (T-202),
and, when Shazam hands over an ISRC, the real MusicBrainz recording that ISRC names
(T-203). This module turns those into ONE structured LLM call per track that reconciles
them into a `Verdict`: which candidate (if any) is the identity, why, and how the senses
line up. T-205's gate consumes the `Verdict`; this module never lands or parks.

## The one non-negotiable: the LLM selects by INDEX, never authors identity

The augmented `candidates[]` is the union of beets' MusicBrainz candidates **plus** a
synthetic entry for the ISRC→MB recording when it resolved — every entry carrying a
`mbid` that came from a *real* lookup (spec §5). The LLM's `chosen_candidate` is an
integer index (`n`) into that list, enum-constrained to the present values (or `null`).
There is **no free-text artist/title/mbid field**, so the model can never invent an
identity or an MBID — the exact failure `spike/b_flow.py` had, whose free-text schema let
the LLM author the MBID. We reuse that spike's ISRC lookup and normalizer ideas elsewhere
(T-203, T-205); its prompt shape is forbidden and the system prompt here is a fresh
index-selection one.

## What travels, and what is stripped

Evidence handed to the model = `SourceSignals` + `dominance` (`top_score` +
`top_recording_ids`) + the augmented `candidates[]` (canonical, fixed order) + the
optional Shazam record. The order of `candidates[]` is serialized into the prompt exactly
as it is reused for index resolution, so an index never resolves against a different order
than the model saw. The `Verdict` has **no confidence field** — confidence is never
load-bearing (spec §5), so it is structurally impossible for one to leave this seam.

## Determinism + model

Temperature 0, one call per track, structured output forced via tool-use `tool_choice`.
The model is `claude-haiku-4-5` — the model the whole architecture-B spike (and therefore
the §7 acceptance corpus) was validated on, and one that still honours `temperature=0`
(the Opus/Sonnet-5 family rejects sampling params). See the `claude-api` skill.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("cleanmuzik")

# The spike validated architecture B end-to-end on Haiku; the §7 acceptance cases ARE the
# exp-9 cases, so the reconcile model must match the one that produced them. Haiku also
# still accepts `temperature=0` (the Opus/Sonnet-5 family 400s on any sampling param).
MODEL = "claude-haiku-4-5"
# Structured output is small (one verdict object); 1024 is ample headroom.
MAX_TOKENS = 1024

# The single forced tool. Its input schema IS the §6 Verdict, built per-track so
# `chosen_candidate`/`ranking` can enum over the candidates actually present.
_TOOL_NAME = "record_verdict"

_SENSES = ("yt", "fp", "sz")

SYSTEM_PROMPT = (
    "You reconcile the identity of ONE music track from up to three independent senses, "
    "then record a verdict by calling the record_verdict tool.\n\n"
    "The senses:\n"
    "- youtube: what the YouTube page claimed (title, uploader, and — for judgment only — "
    "album/release-year/tags/description). yt_artist and yt_title are the cleaned claim.\n"
    "- fingerprint: an acoustic AcoustID match. top_score is its confidence; "
    "top_recording_ids are the MusicBrainz recording MBIDs it points at.\n"
    "- shazam: a Shazam guess (artist/title) and, when present, an ISRC.\n\n"
    "You are given candidates[]: a fixed, numbered list of REAL identities. Each entry has "
    "n (its index), artist, title, mbid, and source ('musicbrainz' or 'isrc'). Every mbid "
    "came from a real lookup.\n\n"
    "Your job: pick the ONE candidate that is this track's true identity, by its index n, "
    "or null if none fits. You can ONLY point at a candidate by index — you never write an "
    "artist, title, or mbid yourself. If the true identity is not in candidates[], choose "
    "null and park.\n\n"
    "Rules:\n"
    "- Trust the fingerprint's recording when it is confident and a candidate matches it. "
    "Only override it in favour of a different candidate when youtube AND shazam both "
    "clearly support that other candidate (e.g. a mistagged rip whose real identity is the "
    "ISRC candidate).\n"
    "- Beware covers: a real ISRC can name the WRONG recording. If the senses disagree on "
    "artist or title, prefer to park.\n"
    "- Use album/year/tags/description only as judgment aids, never as the deciding fact.\n\n"
    "Fields to record:\n"
    "- verdict: 'accept' to land the chosen candidate, 'park' to send it to human review.\n"
    "- chosen_candidate: the index n you chose, or null.\n"
    "- agreeing_senses: which of yt/fp/sz genuinely support the chosen candidate (a "
    "downstream check re-derives this in code, so be honest, not generous).\n"
    "- ranking: every candidate index, best first, for the review card.\n"
    "- reason: one line.\n"
    "- contradictions: short notes on any sense that disagrees.\n"
    "- genre_suggestion / mood_suggestion: optional opinion, or null. Not written as tags."
)


@dataclass(frozen=True)
class Verdict:
    """The reconciled identity decision for one track (spec §6). No confidence field — ever.

    A *proposal* the LLM makes, validated into this shape. `chosen_candidate` and every
    entry of `ranking` are indices into the augmented `candidates[]` the call was given.
    `agreeing_senses` is the LLM's claim; T-205's gate RE-DERIVES the real agreement in
    code and never trusts this list's count. The seam deliberately has no `confidence`
    attribute, so confidence cannot travel past this boundary (spec §5).
    """

    verdict: str  # "accept" | "park"
    chosen_candidate: int | None
    agreeing_senses: list[str] = field(default_factory=list)
    ranking: list[int] = field(default_factory=list)
    reason: str = ""
    contradictions: list[str] = field(default_factory=list)
    genre_suggestion: str | None = None  # R1.5 never writes this (lastgenre owns genre)
    mood_suggestion: str | None = None  # captured, unused until R1.6


class ReconcileError(RuntimeError):
    """The reconcile call returned no usable verdict (no tool call in the response).

    Raised by `reconcile`; the seam treats any reconcile failure as "no verdict this
    track" in T-204 and, in T-205, as a park with reason 'adjudication unavailable'.
    """


def build_candidates(beets_candidates, isrc_recording) -> list[dict]:
    """The augmented `candidates[]` — beets' MB candidates ++ the ISRC entry if it resolved.

    Each entry is `{n, artist, title, mbid, source}` with `source ∈ {"musicbrainz",
    "isrc"}` and a real MBID. Beets candidates without a recording MBID are dropped: an
    entry with no real MBID could not be selected by index against a real identity (spec
    §5), and its presence would only let the model point at a hole. `n` is the position in
    THIS list — assigned as we build, so it is the same index the model selects by, the
    order it is serialized in, and the order T-205/T-206 persist. The ISRC entry, when
    present, is always appended last (canonical, fixed order).
    """
    out: list[dict] = []
    for cand in beets_candidates:
        info = getattr(cand, "info", None)
        mbid = getattr(info, "track_id", None) if info is not None else None
        if not mbid:
            continue
        out.append(
            {
                "n": len(out),
                "artist": getattr(info, "artist", None),
                "title": getattr(info, "title", None),
                "mbid": mbid,
                "source": "musicbrainz",
            }
        )
    if isrc_recording is not None:
        out.append(
            {
                "n": len(out),
                "artist": isrc_recording.artist,
                "title": isrc_recording.title,
                "mbid": isrc_recording.mbid,
                "source": "isrc",
            }
        )
    return out


def build_evidence(source_signals, dominance, candidates, shazam_record) -> dict:
    """The reconcile payload (spec §6): the three senses + the augmented candidates.

    `youtube` carries yt_album/yt_release_year/tags/description as JUDGMENT-ONLY context
    for the model (spec §2) — they are here so the LLM can *pick*, never so a fact is
    written. `shazam` is included only when it matched (a non-match is a non-vote, spec
    §5). `candidates` rides in the evidence so `reconcile` can build the per-track enum
    schema from it and index resolution uses the identical list.
    """
    yt = None
    if source_signals is not None:
        yt = {
            "title": source_signals.title,
            "uploader": source_signals.uploader,
            "channel_is_topic": source_signals.channel_is_topic,
            "description_head": source_signals.description_head,
            "tags": source_signals.tags,
            "duration": source_signals.duration,
            "yt_artist": source_signals.yt_artist,
            "yt_title": source_signals.yt_title,
            "yt_album": source_signals.yt_album,  # judgment-only
            "yt_release_year": source_signals.yt_release_year,  # judgment-only
        }
    shazam = None
    if shazam_record and shazam_record.get("matched"):
        shazam = {
            "shazam_artist": shazam_record.get("shazam_artist"),
            "shazam_title": shazam_record.get("shazam_title"),
            "isrc": shazam_record.get("isrc"),
        }
    return {
        "youtube": yt,
        "fingerprint": {
            "top_score": dominance.top_score,
            "top_recording_ids": list(dominance.top_recording_ids),
        },
        "candidates": candidates,
        "shazam": shazam,
    }


def _record_verdict_tool(candidates: list[dict]) -> dict:
    """The forced tool whose input schema is the §6 Verdict, specialised to this track.

    `chosen_candidate` is enum-constrained to the present `n` values plus `null`, and
    `ranking` to the present `n` values — so the only identity the model can point at is a
    real-MBID candidate by index. No `confidence` field exists in the schema.
    """
    n_values = [c["n"] for c in candidates]
    return {
        "name": _TOOL_NAME,
        "description": "Record the reconciled identity verdict for this one track.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "verdict": {"type": "string", "enum": ["accept", "park"]},
                "chosen_candidate": {
                    "enum": [*n_values, None],
                    "description": "Index n of the chosen candidate, or null if none fits.",
                },
                "agreeing_senses": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_SENSES)},
                },
                "ranking": {
                    "type": "array",
                    "items": ({"enum": n_values} if n_values else {"type": "integer"}),
                    "description": "Every candidate index, best first.",
                },
                "reason": {"type": "string"},
                "contradictions": {"type": "array", "items": {"type": "string"}},
                "genre_suggestion": {"type": ["string", "null"]},
                "mood_suggestion": {"type": ["string", "null"]},
            },
            "required": [
                "verdict",
                "chosen_candidate",
                "agreeing_senses",
                "ranking",
                "reason",
                "contradictions",
                "genre_suggestion",
                "mood_suggestion",
            ],
        },
    }


def _tool_input(message) -> dict:
    """The forced tool call's `input`, or raise. The call is forced, so this is the record."""
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == _TOOL_NAME:
            return dict(block.input or {})
    raise ReconcileError("reconcile response carried no record_verdict tool call")


def _coerce_verdict(raw: dict, candidates: list[dict]) -> Verdict:
    """Validate the raw tool input into a `Verdict`, dropping anything the model shouldn't set.

    The forced enum schema already constrains the model, but this is the load-bearing
    guard: `chosen_candidate` and `ranking` are re-checked against the ACTUAL candidate
    indices (a stray index becomes `null` / is filtered out), `agreeing_senses` is
    filtered to the real sense names, and any `confidence` the model emitted is simply
    never read — so it cannot reach the `Verdict`. `verdict` defaults to the safe "park"
    if the model returned something off-vocabulary.
    """
    valid_n = {c["n"] for c in candidates}

    chosen = raw.get("chosen_candidate")
    if chosen is not None and chosen not in valid_n:
        chosen = None

    ranking = [n for n in (raw.get("ranking") or []) if n in valid_n]
    senses = [s for s in (raw.get("agreeing_senses") or []) if s in _SENSES]

    verdict = raw.get("verdict")
    if verdict not in ("accept", "park"):
        verdict = "park"
    # An accept MUST name a real candidate. The forced schema permits accept + null, and
    # a stray index was nulled above — either way an "accept" with `chosen_candidate=None`
    # is an accept-with-no-identity that T-205 would try to land as candidates[None]. Keep
    # this seam's promise ("a stray value degrades, never lands"): reconcile the pair to park.
    if verdict == "accept" and chosen is None:
        verdict = "park"

    return Verdict(
        verdict=verdict,
        chosen_candidate=chosen,
        agreeing_senses=senses,
        ranking=ranking,
        reason=(raw.get("reason") or "").strip(),
        contradictions=[c for c in (raw.get("contradictions") or []) if isinstance(c, str)],
        genre_suggestion=raw.get("genre_suggestion") or None,
        mood_suggestion=raw.get("mood_suggestion") or None,
    )


def reconcile(evidence: dict, *, client, model: str = MODEL, max_tokens: int = MAX_TOKENS) -> Verdict:
    """One reconcile call → a validated `Verdict`. Temperature 0, forced structured output.

    `client` is an `anthropic.Anthropic`-shaped object (injected so tests run offline). The
    per-track tool schema is built from `evidence["candidates"]`, and the same list is used
    to validate the returned indices — an index can never resolve against a different order
    than the model saw. Raises `ReconcileError` if the response somehow lacks the forced
    tool call.
    """
    candidates = evidence.get("candidates") or []
    tool = _record_verdict_tool(candidates)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        system=SYSTEM_PROMPT,
        tools=[tool],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": json.dumps(evidence)}],
    )
    return _coerce_verdict(_tool_input(message), candidates)


def make_reconcile_fn(settings):
    """Build the default `reconcile_fn(evidence) -> Verdict`, or `None` when no key is set.

    Reads `ANTHROPIC_APIKEY` off `settings` via `getattr` so this works whether or not
    T-200 has declared the field yet: until the owner sets the key (T-200), this returns
    `None` and the pipeline degrades to the R1 fingerprint-only gate (spec §6 degrade row,
    implemented in T-205). The returned closure holds one `anthropic` client for the run.
    """
    key = getattr(settings, "anthropic_apikey", "") or ""
    if not key.strip():
        logger.info("ANTHROPIC_APIKEY not set — reconcile disabled, R1 fingerprint gate in effect")
        return None

    try:
        import anthropic  # local import: the seam builds this only when a key is present
    except ImportError:
        # A key is set but the package isn't importable (partial/failed install, env
        # drift). Fail soft to the R1 fingerprint gate — a misconfigured environment must
        # degrade, not error every track out of the pipeline (ADR-003 / spec §6 degrade).
        logger.warning(
            "ANTHROPIC_APIKEY is set but the `anthropic` package is not importable — "
            "reconcile disabled, falling back to the R1 fingerprint gate"
        )
        return None

    client = anthropic.Anthropic(api_key=key)

    def _reconcile_fn(evidence: dict) -> Verdict:
        return reconcile(evidence, client=client)

    return _reconcile_fn
