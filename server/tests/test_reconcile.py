"""T-204 tests — the reconcile seam builds evidence, forces structured output, validates.

All offline: `reconcile()` drives a fake `anthropic`-shaped client, so no network and no
key are touched. The load-bearing guarantees under test are the ones the spec forbids
getting wrong (spec §5/§6):

- the augmented `candidates[]` carries only real-MBID entries, ISRC appended last;
- the model is handed a per-track enum schema and can only point at a candidate by index;
- a returned `confidence` is structurally unable to reach the `Verdict`;
- the coercion re-validates indices/senses so a stray value degrades, never lands.
"""

import json
from types import SimpleNamespace

import pytest

from app import reconcile
from app.reconcile import (
    ReconcileError,
    Verdict,
    _coerce_verdict,
    _record_verdict_tool,
    build_candidates,
    build_evidence,
    make_reconcile_fn,
)


def _cand(track_id, artist=None, title=None):
    return SimpleNamespace(info=SimpleNamespace(track_id=track_id, artist=artist, title=title))


def _isrc(mbid="mb-real", artist="Pa Salieu", title="Frontline"):
    return SimpleNamespace(mbid=mbid, artist=artist, title=title)


# --- build_candidates: real MBIDs only, ISRC appended last ------------------


def test_build_candidates_indexes_and_maps_beets():
    out = build_candidates([_cand("rec-A", "A", "one"), _cand("rec-B", "B", "two")], None)
    assert [c["n"] for c in out] == [0, 1]
    assert out[0] == {"n": 0, "artist": "A", "title": "one", "mbid": "rec-A", "source": "musicbrainz"}
    assert all(c["source"] == "musicbrainz" for c in out)


def test_build_candidates_drops_entries_without_a_real_mbid():
    # A candidate with no recording MBID cannot be selected by index against a real
    # identity — it is dropped, not handed to the model as a hole.
    out = build_candidates([_cand(None), _cand("rec-A", "A", "one")], None)
    assert [c["mbid"] for c in out] == ["rec-A"]
    assert out[0]["n"] == 0  # n is the position in THIS list, not the beets index


def test_build_candidates_appends_isrc_entry_last_when_resolved():
    out = build_candidates([_cand("rec-A", "A", "one")], _isrc())
    assert [c["source"] for c in out] == ["musicbrainz", "isrc"]
    assert out[-1] == {"n": 1, "artist": "Pa Salieu", "title": "Frontline", "mbid": "mb-real", "source": "isrc"}


def test_build_candidates_no_isrc_entry_when_unresolved():
    out = build_candidates([_cand("rec-A", "A", "one")], None)
    assert [c["source"] for c in out] == ["musicbrainz"]
    assert len(out) == 1


# --- build_evidence: the three senses, judgment-only fields ride along -------


def _signals():
    return SimpleNamespace(
        title="Artist - Song (Official Video)",
        uploader="Artist - Topic",
        channel_is_topic=True,
        description_head="notes",
        tags=["pop"],
        duration=180.0,
        yt_artist="Artist",
        yt_title="Song",
        yt_album="Some Album",
        yt_release_year=2020,
    )


def test_build_evidence_carries_senses_and_candidates():
    dom = SimpleNamespace(top_score=0.9, top_recording_ids=("rec-A",))
    cands = build_candidates([_cand("rec-A", "A", "one")], None)
    shazam = {"matched": True, "shazam_artist": "A", "shazam_title": "one", "isrc": "GB123"}

    ev = build_evidence(_signals(), dom, cands, shazam)

    assert ev["fingerprint"] == {"top_score": 0.9, "top_recording_ids": ["rec-A"]}
    assert ev["candidates"] == cands
    assert ev["shazam"] == {"shazam_artist": "A", "shazam_title": "one", "isrc": "GB123"}
    # judgment-only fields are present for the model to read (spec §2)
    assert ev["youtube"]["yt_album"] == "Some Album"
    assert ev["youtube"]["yt_release_year"] == 2020
    assert ev["youtube"]["yt_artist"] == "Artist"


def test_build_evidence_drops_unmatched_shazam_to_a_non_vote():
    dom = SimpleNamespace(top_score=0.0, top_recording_ids=())
    ev = build_evidence(_signals(), dom, [], {"matched": False, "error": "timeout"})
    assert ev["shazam"] is None


def test_build_evidence_tolerates_absent_signals():
    dom = SimpleNamespace(top_score=0.0, top_recording_ids=())
    ev = build_evidence(None, dom, [], None)
    assert ev["youtube"] is None


# --- the forced tool schema: index-only selection ---------------------------


def test_tool_schema_constrains_chosen_and_ranking_to_present_indices():
    cands = build_candidates([_cand("rec-A"), _cand("rec-B")], _isrc())  # n = 0,1,2
    schema = _record_verdict_tool(cands)["input_schema"]
    props = schema["properties"]
    assert props["chosen_candidate"]["enum"] == [0, 1, 2, None]
    assert props["ranking"]["items"]["enum"] == [0, 1, 2]
    # no free-text identity field, and no confidence field, exist on the schema
    assert "confidence" not in props
    assert not {"artist", "title", "mbid"} & set(props)
    assert schema["additionalProperties"] is False


def test_tool_schema_with_no_candidates_only_allows_null():
    schema = _record_verdict_tool([])["input_schema"]
    assert schema["properties"]["chosen_candidate"]["enum"] == [None]


# --- coercion: the load-bearing re-validation -------------------------------


def test_coerce_strips_confidence_and_keeps_valid_fields():
    cands = build_candidates([_cand("rec-A"), _cand("rec-B")], None)
    raw = {
        "verdict": "accept",
        "chosen_candidate": 1,
        "agreeing_senses": ["yt", "fp"],
        "ranking": [1, 0],
        "reason": "  fp + yt agree ",
        "contradictions": [],
        "genre_suggestion": "grime",
        "mood_suggestion": None,
        "confidence": 0.99,  # must never reach the Verdict (spec §5)
    }
    v = _coerce_verdict(raw, cands)
    assert v.verdict == "accept"
    assert v.chosen_candidate == 1
    assert v.agreeing_senses == ["yt", "fp"]
    assert v.ranking == [1, 0]
    assert v.reason == "fp + yt agree"
    assert v.genre_suggestion == "grime"
    # confidence is structurally absent from the Verdict
    assert not hasattr(v, "confidence")


def test_coerce_drops_out_of_range_index_and_bad_senses():
    cands = build_candidates([_cand("rec-A")], None)  # only n=0 exists
    raw = {
        "verdict": "park",
        "chosen_candidate": 5,  # not a real index → dropped to None
        "agreeing_senses": ["yt", "bogus"],
        "ranking": [0, 9],  # 9 filtered out
        "reason": "x",
        "contradictions": ["yt says A, fp says B"],
    }
    v = _coerce_verdict(raw, cands)
    assert v.chosen_candidate is None
    assert v.agreeing_senses == ["yt"]
    assert v.ranking == [0]
    assert v.contradictions == ["yt says A, fp says B"]


def test_coerce_defaults_off_vocabulary_verdict_to_park():
    v = _coerce_verdict({"verdict": "maybe", "chosen_candidate": None}, [])
    assert v.verdict == "park"


def test_coerce_accept_without_a_chosen_candidate_downgrades_to_park():
    # An accept that names no identity would land as candidates[None] in T-205 — the seam
    # reconciles the pair down to park rather than emitting an accept-with-no-identity.
    v = _coerce_verdict({"verdict": "accept", "chosen_candidate": None}, [])
    assert v.verdict == "park"


def test_coerce_accept_with_out_of_range_index_downgrades_to_park():
    cands = build_candidates([_cand("rec-A")], None)  # only n=0 exists
    v = _coerce_verdict({"verdict": "accept", "chosen_candidate": 7}, cands)
    assert v.chosen_candidate is None
    assert v.verdict == "park"


# --- reconcile(): forced structured output at temperature 0 -----------------


class _FakeMessages:
    def __init__(self, tool_input, calls):
        self._tool_input = tool_input
        self._calls = calls

    def create(self, **kwargs):
        self._calls.append(kwargs)
        block = SimpleNamespace(type="tool_use", name="record_verdict", input=self._tool_input)
        return SimpleNamespace(content=[SimpleNamespace(type="text"), block])


class _FakeClient:
    def __init__(self, tool_input):
        self.calls = []
        self.messages = _FakeMessages(tool_input, self.calls)


def test_reconcile_forces_the_tool_at_temperature_zero():
    cands = build_candidates([_cand("rec-A")], _isrc())
    ev = build_evidence(_signals(), SimpleNamespace(top_score=0.2, top_recording_ids=()), cands, None)
    client = _FakeClient(
        {
            "verdict": "accept",
            "chosen_candidate": 1,
            "agreeing_senses": ["yt", "sz"],
            "ranking": [1, 0],
            "reason": "override lands on the ISRC recording",
            "contradictions": ["fp weak"],
            "genre_suggestion": None,
            "mood_suggestion": None,
        }
    )

    v = reconcile.reconcile(ev, client=client)

    assert isinstance(v, Verdict)
    assert v.chosen_candidate == 1  # indexes into the exact augmented list
    call = client.calls[0]
    assert call["model"] == reconcile.MODEL
    assert call["temperature"] == 0
    assert call["tool_choice"] == {"type": "tool", "name": "record_verdict"}
    # the evidence handed over is the fixed-order candidate list, serialized verbatim
    assert json.loads(call["messages"][0]["content"])["candidates"] == cands


def test_reconcile_raises_when_no_tool_call_returned():
    class _NoToolClient:
        messages = SimpleNamespace(create=lambda **k: SimpleNamespace(content=[SimpleNamespace(type="text")]))

    with pytest.raises(ReconcileError):
        reconcile.reconcile({"candidates": []}, client=_NoToolClient())


# --- make_reconcile_fn: absent key degrades to None -------------------------


def test_make_reconcile_fn_returns_none_without_a_key():
    assert make_reconcile_fn(SimpleNamespace(anthropic_apikey="")) is None
    assert make_reconcile_fn(SimpleNamespace()) is None  # field not declared yet (pre-T-200)


def test_make_reconcile_fn_degrades_when_anthropic_unimportable(monkeypatch):
    # A key is set but the package won't import (env drift) — degrade to the R1 gate,
    # never let the ImportError escape and error the track out (ADR-003 / spec §6).
    import builtins

    real_import = builtins.__import__

    def _fail_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no anthropic wheel")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_anthropic)
    assert make_reconcile_fn(SimpleNamespace(anthropic_apikey="sk-test")) is None
