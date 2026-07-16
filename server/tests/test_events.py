"""T-013 tests — the SSE event bus: the thread→loop bridge, replay, ping, close.

All offline, no sockets. The async paths are driven with `asyncio.run` (no
pytest-asyncio needed — a plain coroutine per test), which gives a real running loop
so `bind_loop` + `call_soon_threadsafe` exercise the genuine cross-thread hand-off,
not a stub. Wire-format parsing is shared with the route tests via `parse_sse`.
"""

import asyncio
import json
import threading

from app.events import EventBus, format_sse


# --- shared SSE wire-format parsing -----------------------------------------


def parse_frame(frame: str) -> tuple[str, dict]:
    """One `event:/data:` SSE frame → (event_name, decoded_payload)."""
    lines = frame.strip().split("\n")
    event = lines[0].removeprefix("event: ")
    data = json.loads(lines[1].removeprefix("data: "))
    return event, data


def parse_sse(text: str) -> list[tuple[str, dict]]:
    """A whole SSE response body → ordered (event, payload) pairs."""
    frames = [chunk for chunk in text.split("\n\n") if chunk.strip()]
    return [parse_frame(frame + "\n\n") for frame in frames]


def _drain(bus: EventBus, job_id: str, **kwargs) -> list[tuple[str, dict]]:
    """Run a stream to completion (only valid once the job is closed) and parse it.

    The replay-then-close path: for a job whose terminal `close` already fired, the
    generator replays the buffer and returns, so this terminates without waiting.
    """

    async def run():
        return [frame async for frame in bus.stream(job_id, **kwargs)]

    return [parse_frame(f) for f in asyncio.run(run())]


# --- format ------------------------------------------------------------------


def test_format_sse_is_event_then_json_then_blank_line():
    assert format_sse("ping", {}) == "event: ping\ndata: {}\n\n"
    frame = format_sse("job.queued", {"job_id": "j", "url": "u"})
    event, data = parse_frame(frame)
    assert event == "job.queued"
    assert data == {"job_id": "j", "url": "u"}


# --- replay: a client that connects late loses nothing -----------------------


def test_replays_buffered_events_then_closes():
    bus = EventBus()
    bus.publish("j", "job.queued", {"job_id": "j", "url": "u"})
    bus.publish("j", "track.downloading", {"job_id": "j"})
    bus.publish("j", "track.done", {"job_id": "j", "path": "/x.mp3", "tags": {}})
    bus.close("j")

    events = _drain(bus, "j")
    assert [name for name, _ in events] == [
        "job.queued",
        "track.downloading",
        "track.done",
    ]


def test_publish_after_close_is_dropped():
    bus = EventBus()
    bus.publish("j", "job.queued", {"job_id": "j", "url": "u"})
    bus.close("j")
    bus.publish("j", "track.done", {"job_id": "j"})  # stray, post-terminal

    assert [name for name, _ in _drain(bus, "j")] == ["job.queued"]


# --- ping: an idle stream is kept alive --------------------------------------


def test_ping_emitted_on_idle():
    async def run():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        gen = bus.stream("j", ping_interval=0.01)
        try:
            # Empty buffer, not closed → the first frame is the idle keepalive.
            return await gen.__anext__()
        finally:
            await gen.aclose()

    event, data = parse_frame(asyncio.run(run()))
    assert event == "ping"
    assert data == {}


# --- the bridge: events published FROM a worker thread reach a loop subscriber ---


def test_live_delivery_from_worker_thread():
    async def run():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        received: list[tuple[str, dict]] = []

        async def consume():
            async for frame in bus.stream("j", ping_interval=100):
                received.append(parse_frame(frame))

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)  # let the generator subscribe before we publish

        # Publish from a REAL separate thread — this is the call_soon_threadsafe path.
        def worker():
            bus.publish("j", "job.queued", {"job_id": "j", "url": "u"})
            bus.publish("j", "track.done", {"job_id": "j", "path": "/x", "tags": {}})
            bus.close("j")

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        await asyncio.wait_for(task, timeout=2)
        return received

    received = asyncio.run(run())
    assert [name for name, _ in received] == ["job.queued", "track.done"]


def test_two_subscribers_both_receive_live():
    async def run():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        got_a: list[str] = []
        got_b: list[str] = []

        async def consume(sink):
            async for frame in bus.stream("j", ping_interval=100):
                sink.append(parse_frame(frame)[0])

        tasks = [
            asyncio.create_task(consume(got_a)),
            asyncio.create_task(consume(got_b)),
        ]
        await asyncio.sleep(0.05)

        def worker():
            bus.publish("j", "track.identifying", {"job_id": "j"})
            bus.close("j")

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()

        await asyncio.wait_for(asyncio.gather(*tasks), timeout=2)
        return got_a, got_b

    got_a, got_b = asyncio.run(run())
    assert got_a == ["track.identifying"]
    assert got_b == ["track.identifying"]


def test_events_isolated_per_job():
    bus = EventBus()
    bus.publish("a", "job.queued", {"job_id": "a", "url": "ua"})
    bus.publish("b", "job.queued", {"job_id": "b", "url": "ub"})
    bus.close("a")
    bus.close("b")

    a = _drain(bus, "a")
    b = _drain(bus, "b")
    assert a[0][1]["job_id"] == "a"
    assert b[0][1]["job_id"] == "b"
    assert len(a) == 1 and len(b) == 1
