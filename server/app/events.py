"""SSE event bus — the thread→event-loop bridge that streams stage progress (T-013, spec §6).

The pipeline runs on a worker thread (ADR-001); the SSE endpoint streams on the
asyncio event loop. Nothing may cross that boundary casually — a `asyncio.Queue`
touched from a foreign thread corrupts. This module is the sanctioned hand-off:

- **`publish(job_id, event, data)`** is called *from the worker thread* as each
  stage transitions (wired into `run_pipeline`). It appends the event to a per-job
  buffer and pushes it to every connected subscriber's `asyncio.Queue` via
  `loop.call_soon_threadsafe` — the one thread-safe way to poke a loop primitive
  from another thread.
- **`stream(job_id)`** is the async generator the route returns. It first *replays*
  the buffer, then live-streams the rest, emitting a `ping` on idle and closing on
  the terminal sentinel.

## Why the buffer (the load-bearing part)

The T-016 track card opens `GET /api/jobs/{id}/events` a beat *after* `POST /api/jobs`
returns — but the worker may already have emitted `job.queued` / `track.downloading`
by then. A pure live stream would drop them and leave the card stuck at "queued". So
every event is buffered per job; a connecting subscriber replays what already
happened *this process*, then live-streams the rest. The buffer is process-lifetime
only (spec §6 has no event log to persist) and bounded by `cap` so the always-on
host (Phase 1) doesn't grow it without end — oldest jobs' channels fall off first,
exactly like `JobRegistry`.

## The close sentinel

Not every terminal path has a spec event: a landed song ends on `track.done`, a park
on `track.review_required`, a failure on `track.error` — but a duplicate *skip* lands
nothing and has no event in the §6 catalogue. So stream closure is driven by an
internal `close(job_id)` sentinel that `run_pipeline` fires on every terminal path,
not by sniffing for a terminal event name. The sentinel closes the stream without
being surfaced to the client; a late subscriber to an already-closed job replays the
buffer and stops.

## Episodes: why a channel can re-open (T-014)

A park is terminal *for the acquire run* but not for the job — the owner resolves the
review later and the import resumes, which must stream its tail. `close()` already
fired, though, and `publish()` early-returns on a closed channel, so those tail events
would land in a black hole. `reopen(job_id)` is the sanctioned way back: it clears
`closed` and **resets the buffer**, starting a fresh *episode* of the job's stream.

Resetting the buffer (rather than appending to it) is the load-bearing half. T-016's
card must close its EventSource on `track.review_required` — otherwise EventSource
auto-reconnects on the server's EOF and loops forever — so T-017 opens a **new**
EventSource after the resolve POST returns. That new subscriber replays the buffer;
if the buffer still held the acquire episode it would replay `track.review_required`
and close again *instantly*, leaving the card stuck at "Needs review" forever — the
exact hang the reopen exists to prevent. So each episode's buffer holds only its own
events, and the replay is what saves the tail from the gap between the POST returning
and the subscriber connecting.

## The batch channel (T-305)

A batch drives ONE extra channel, keyed `batch_channel(playlist_id)`, that every member
job's events are mirrored onto (stamped with the member's `position`/`job_id`) plus the
batch-level `batch.queued` / `batch.progress` — so a 50-track batch costs one
`EventSource`, not 50 against the browser's ~6-per-origin cap. The mirroring itself
lives in `app.jobs._BatchScopedBus` (it needs the job row); this module only supplies
the key, the `batch.progress` payload shape, and `pin` — the eviction exemption that
keeps the long-lived batch channel alive while its member channels churn through the
cap. Each paste of a playlist is an *episode* of its batch channel, via the same
`reopen` the resolve path uses: the expansion route reopens it, so a re-paste's
subscribers don't replay the previous grind's terminal tally.
"""

import asyncio
import json
import threading

# Seconds of idle before a keepalive `ping` (spec §6). Long enough not to spam a
# healthy stream, short enough to keep proxies/load-balancers from culling an idle
# connection during a slow download.
PING_INTERVAL = 15.0

# Cap on retained per-job channels — mirrors JobRegistry._REGISTRY_CAP: a client can
# still connect just after a job finishes, but the map must not grow forever.
_CHANNEL_CAP = 256

# Internal sentinel pushed to live subscribers to close their stream. Deliberately a
# unique object (not None, not a spec event) so it can never collide with real data.
_CLOSE = object()

# Derived batch states carried on `batch.progress` (T-305). "waiting_on_you" — not
# "done" — while any member is parked in review: a finished grind with parked tracks is
# the owner's turn, and reporting "done" would bury the reviews (US17). A failed member
# never blocks "done" (ADR-002: one failure continues the batch) — it stays visible in
# the `failed` count instead of poisoning the state.
BATCH_RUNNING = "running"
BATCH_WAITING = "waiting_on_you"
BATCH_DONE = "done"
# An empty batch (`total == 0`) is "never_started", NOT "done" (T-310 design gate,
# screen 07). A crash between the playlist row-upsert and the enqueue leaves a batch
# with zero members; without this the "no queued, no review ⇒ done" fall-through would
# report a phantom *finished* batch and the card would paint a completed empty playlist.
# Like BATCH_DONE it is terminal-with-nothing-coming — the batch stream treats both as
# settled — but it reads as "never got off the ground", so the owner re-pastes.
BATCH_EMPTY = "never_started"


def batch_channel(playlist_id: str) -> str:
    """The bus key for a batch's ONE playlist-scoped stream (T-305).

    Channels are keyed by arbitrary strings and were all job ids until T-305. The
    batch stream shares the same bus, so its key is namespaced with a prefix no
    uuid-hex job id can collide with — and a reader of a channel dump can tell the
    one long-lived batch channel from its 50 member channels at a glance. Lives here
    (not `app.jobs`) so the import-light routes can subscribe without pulling beets.
    """
    return f"batch:{playlist_id}"


def batch_progress_payload(playlist_id: str, counts: dict[str, int]) -> dict:
    """The single `batch.progress` event shape: the durable tally + the derived state.

    `counts` is `Store.count_jobs_by_status`'s status → count map, recomputed from
    SQLite at every emit — never accumulated in memory — so a mid-batch restart
    cannot lose or skew the tally (T-312 rebuilds from the same read). Every place
    that emits or serves the tally goes through here, exactly like `candidate_row`,
    so the contract's key set lives in one spot.

    The status names are `app.jobs`' STATUS_* values kept as local literals for the
    same reason as the routes' terminal set — importing `app.jobs` from here would
    drag beets onto the import-light path. `running` folds into `queued`: from the
    batch's walk-away view a mid-pipeline track is simply "not finished yet", and
    the stamped `track.*` events already carry the finer live state.
    """
    landed = counts.get("done", 0)
    in_review = counts.get("review", 0)
    failed = counts.get("error", 0)
    skipped = counts.get("skipped", 0)
    queued = counts.get("queued", 0) + counts.get("running", 0)
    total = landed + in_review + failed + skipped + queued
    if total == 0:
        # Nothing was ever enqueued — the enqueue never ran (crash mid-paste). Terminal,
        # but "never started", not "done": the card must not render a finished empty batch.
        state = BATCH_EMPTY
    elif queued:
        state = BATCH_RUNNING
    elif in_review:
        state = BATCH_WAITING
    else:
        state = BATCH_DONE
    return {
        "playlist_id": playlist_id,
        "landed": landed,
        "in_review": in_review,
        "failed": failed,
        "skipped": skipped,
        "queued": queued,
        "total": total,
        "state": state,
    }


class _JobChannel:
    """Per-job event state: the replay buffer, the closed flag, live subscribers.

    Guarded by the owning `EventBus`'s single lock — never touched without it, so a
    worker-thread `publish` and a loop-thread `stream` see a consistent view.
    """

    __slots__ = ("events", "closed", "subscribers")

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.closed: bool = False
        self.subscribers: set[asyncio.Queue] = set()


def candidate_row(
    candidate_id: str | None,
    *,
    title: str | None = None,
    artist: str | None = None,
    score: float | None = None,
) -> dict:
    """The single spec §6 `track.review_required.candidates[]` row shape.

    Every place that emits a candidate row goes through here so the contract's key set
    lives in exactly one spot: the park-time builder (`import_seam._candidate_rows`),
    the id-only raise-recovery fallback (`jobs._id_only_candidates`, display fields
    null), and T-014's re-hydration for `GET /api/reviews`. Add or rename a field here
    and every path stays in lockstep. Lives in this import-light module (no beets) so
    both the heavy seam and the lazy route can import it.

    **No `album` / `year` / `art_url` — by decision, not omission (ADR-010).** A
    singleton candidate is a MusicBrainz *recording*; those three are properties of a
    *release*, and one recording appears on many. beets never fetches a release for a
    candidate (`track_for_id` → `track_info(recording)`), so these fields were emitted
    as null on every path from T-007 until 2026-07-17 — a contract key that is
    structurally always null is a lie, not a placeholder, and it read as "we just
    haven't filled it in yet". Reaching them costs a browse-releases call per candidate
    plus a which-release heuristic; ADR-010 rejects that. `score` (= 1 − beets' tag
    distance) is the discriminator and is free.
    """
    return {
        "candidate_id": candidate_id,
        "title": title,
        "artist": artist,
        "score": score,
    }


def format_sse(event: str, data: dict) -> str:
    """One event as an SSE frame: `event: <name>` + a JSON `data:` line + blank line.

    Kept module-level (not buried in the generator) so tests assert the wire shape
    directly. `data` is always a single JSON object per spec §6 — no multiline
    payloads, so a single `data:` line is sufficient and unambiguous.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class EventBus:
    """Thread-safe fan-out from the worker thread to any number of SSE subscribers.

    One instance lives on the `JobWorker` (so the route reaches it via
    `app.state.worker.bus`). Writes come from the single worker thread; reads
    (subscribe/stream) from the event loop. A single lock plus `call_soon_threadsafe`
    is the entire concurrency story — no new threads, no work moved onto the loop, so
    ADR-001's "one worker thread" is untouched (this only *observes* the pipeline).
    """

    def __init__(self, cap: int = _CHANNEL_CAP) -> None:
        self._channels: dict[str, _JobChannel] = {}
        self._lock = threading.Lock()
        self._cap = cap
        # Channel keys exempt from cap eviction (T-305) — see `pin`. A set of keys,
        # not a flag on `_JobChannel`, so a pin survives the channel being absent
        # (pinned-then-recreated after a restart) without special-casing creation.
        self._pinned: set[str] = set()
        # The loop `publish` schedules onto. Bound once at startup (lifespan runs on
        # the loop) or lazily by the first subscriber — a subscriber only ever exists
        # on the loop, so by the time live delivery is needed the loop is bound.
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the event loop the worker thread will schedule deliveries onto.

        Called from the lifespan (which runs on the loop) so cross-thread delivery
        works from the very first event. Idempotent-ish: last binding wins, which is
        correct for a single-loop process.
        """
        self._loop = loop

    # --- worker-thread side ------------------------------------------------

    def publish(self, job_id: str, event: str, data: dict) -> None:
        """Buffer an event for `job_id` and deliver it to every live subscriber.

        Called from the worker thread. Buffering happens under the lock (so a
        concurrently-subscribing stream sees either the event in its replay OR in its
        queue, never both, never neither); the actual `call_soon_threadsafe` is done
        outside the lock to keep the critical section tiny.
        """
        with self._lock:
            channel = self._channel_locked(job_id)
            if channel.closed:
                # A terminal already fired; late stray events are dropped rather than
                # confuse a client that has seen the stream end.
                return
            channel.events.append((event, data))
            subscribers = list(channel.subscribers)
            loop = self._loop
        self._dispatch(loop, subscribers, (event, data))

    def close(self, job_id: str) -> None:
        """Mark a job's stream terminal and unblock every live subscriber.

        Fired by `run_pipeline` on every terminal path (done / review / error / skip),
        so a stream always ends even when the terminal state has no §6 event (a
        duplicate skip). A subscriber that connects afterwards replays the buffer and
        returns immediately.
        """
        with self._lock:
            channel = self._channel_locked(job_id)
            if channel.closed:
                return
            channel.closed = True
            subscribers = list(channel.subscribers)
            loop = self._loop
        self._dispatch(loop, subscribers, _CLOSE)

    def pin(self, key: str) -> None:
        """Exempt a channel from cap eviction — for the long-lived batch channel (T-305).

        A 50-track batch churns 50 short member channels through the cap while its own
        channel must outlive every one of them; without the pin the batch channel is
        exactly the "oldest subscriber-less channel" `_evict_locked` reaps first,
        taking the replay buffer (and a pre-subscribe `batch.queued`) with it.
        Idempotent, and re-applied on every member emit so a post-restart resume
        re-pins the recreated channel. Released via `unpin` when the batch settles, so
        pins are bounded by the batches actually in flight, not the process lifetime.
        """
        with self._lock:
            self._pinned.add(key)

    def unpin(self, key: str) -> None:
        """Release a pin so a settled batch's channel ages out like any other."""
        with self._lock:
            self._pinned.discard(key)

    def reopen(self, job_id: str) -> None:
        """Start a fresh episode on a closed channel so a resumed job can stream again.

        Called from the **resolve route, on the event loop, before it returns** — not
        from the worker thread. The ordering is the whole point: T-017 opens its new
        EventSource as soon as the POST returns, and if the channel were still closed
        at that moment `stream()` would replay-and-return a dead stream. The worker may
        not touch the resolve for minutes (it is sequential, ADR-001), so it cannot be
        the one to reopen. Publishing from the loop thread is safe — `call_soon_threadsafe`
        is legal from the loop itself, and there are no subscribers at reopen time anyway.

        Clears `closed` and **empties the buffer** (see the module docstring): the new
        subscriber must not replay the acquire episode's `track.review_required` and
        close itself instantly. An absent channel (evicted by the cap, or gone after a
        restart) is simply created open — correct, since the resume is about to emit
        into it.
        """
        with self._lock:
            channel = self._channel_locked(job_id)
            channel.closed = False
            channel.events.clear()

    def _dispatch(self, loop, subscribers, item) -> None:
        # `loop is None` only before any subscriber can exist — a subscriber binds the
        # loop under the lock in `stream()` before adding itself — so guard once here
        # rather than re-check per subscriber. Either way the buffer already holds the
        # event for a later replay.
        if loop is None or not subscribers:
            return
        for queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, item)

    # --- loop side ---------------------------------------------------------

    async def stream(
        self, job_id: str, *, terminal: bool = False, ping_interval: float = PING_INTERVAL
    ):
        """Async generator of SSE frames for one job: replay, then live, then close.

        Registers a subscriber queue *and* snapshots the replay buffer under a single
        lock hold, so no event slips between the two (it lands in exactly one of them).
        Emits a `ping` frame after `ping_interval` seconds of silence so the
        connection survives an idle stretch, and returns cleanly on the close
        sentinel. The `finally` always unsubscribes — including on client disconnect,
        when Starlette cancels this generator.

        `terminal` is the caller's durable-status hint. A completed job's channel is
        eventually evicted by the cap (and every channel is gone after a restart); once
        it's evicted, a bare `_channel_locked` here would *fabricate a fresh open
        channel* and block forever on a `close()` that already fired on the discarded
        one — the stream would emit nothing but `ping`s indefinitely. So when the job is
        already terminal *and* no channel remains, there is nothing left to stream:
        replay nothing and return, letting the client fall back to `GET /api/jobs` for
        the final state. A still-present channel (the common just-finished case) is used
        as-is, replayed, and closed normally.
        """
        queue: asyncio.Queue = asyncio.Queue()
        channel: _JobChannel | None = None
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
            existing = self._channels.get(job_id)
            if existing is None and terminal:
                replay: list[tuple[str, dict]] = []
                already_closed = True
            else:
                channel = existing or self._channel_locked(job_id)
                replay = list(channel.events)
                already_closed = channel.closed
                if not already_closed:
                    channel.subscribers.add(queue)
        try:
            for event, data in replay:
                yield format_sse(event, data)
            if already_closed:
                return
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), ping_interval)
                except asyncio.TimeoutError:
                    yield format_sse("ping", {})
                    continue
                if item is _CLOSE:
                    return
                event, data = item
                yield format_sse(event, data)
        finally:
            if channel is not None:
                with self._lock:
                    channel.subscribers.discard(queue)

    # --- internals ---------------------------------------------------------

    def _channel_locked(self, job_id: str) -> _JobChannel:
        # Caller holds the lock. Gets or creates the channel, evicting oldest past cap.
        channel = self._channels.get(job_id)
        if channel is None:
            channel = _JobChannel()
            self._channels[job_id] = channel
            self._evict_locked()
        return channel

    def _evict_locked(self) -> None:
        # Drop oldest channels past the cap. A channel with live subscribers is skipped
        # so an in-flight stream is never yanked out from under a connected client, and
        # a pinned channel is skipped so a batch's one long-lived stream survives its
        # 50 member channels churning past it (T-305).
        while len(self._channels) > self._cap:
            for job_id, channel in self._channels.items():
                if not channel.subscribers and job_id not in self._pinned:
                    del self._channels[job_id]
                    break
            else:
                # Every remaining channel has a live subscriber or a pin — nothing
                # safe to evict. Stop rather than loop forever; the cap is soft
                # under load.
                return
