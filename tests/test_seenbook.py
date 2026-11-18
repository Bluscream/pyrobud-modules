"""Tests for the queue and throttle."""

from __future__ import annotations

import logging

import pytest

from util.seenbook import EventQueue, Observer, PostResult, Settings, Throttle

OBSERVER: Observer = {"accountId": "1"}
READY = Settings("http://x", "t", 10)
PAIR = 2
HALF = 100


def make(results: list[PostResult], sent: list[int]) -> EventQueue:
    async def post(
        _settings: Settings, _observer: Observer, batch: list[dict[str, object]]
    ) -> PostResult:
        sent.append(len(batch))
        return results.pop(0)

    return EventQueue(
        post=post, log=logging.getLogger("test"), settings=READY, observer=OBSERVER
    )


def test_throttle_ten_minutes_both_directions() -> None:
    t = Throttle()
    assert t.due("k", 1_000_000)
    assert not t.due("k", 1_000_000 + 600_000)
    assert t.due("k", 1_000_000 + 600_001)
    assert t.due("k", 1_000_000 - 600_001)


def test_overflow_drops_oldest() -> None:
    q = make([], [])
    q.max_queue = 3
    for i in range(5):
        q.enqueue({"type": "account_seen", "n": i})
    assert [e["n"] for e in q.events] == [2, 3, 4]
    assert q.stats.dropped == PAIR


@pytest.mark.asyncio
async def test_failure_requeues_and_backs_off() -> None:
    sent: list[int] = []
    q = make([PostResult(503, error="down"), PostResult(200, accepted=PAIR)], sent)
    q.extend([{"type": "a"}, {"type": "b"}])
    await q.flush()
    assert len(q) == PAIR
    assert q.failures == 1
    await q.flush()
    assert sent == [2]
    await q.flush(manual=True)
    assert len(q) == 0
    assert q.stats.sent == PAIR


@pytest.mark.asyncio
async def test_too_large_halves_and_bad_request_drops() -> None:
    sent: list[int] = []
    q = make(
        [
            PostResult(413, error="big"),
            PostResult(200, accepted=100),
            PostResult(400, error="bad"),
        ],
        sent,
    )
    q.batch_size = 200
    q.extend({"type": "x"} for _ in range(200))
    await q.flush()
    assert sent == [200, 100, 100]
    assert q.stats.dropped == HALF
    assert len(q) == 0


def test_snapshot_includes_in_flight_and_restore_filters() -> None:
    q = make([], [])
    q.in_flight = [{"type": "a"}]
    q.enqueue({"type": "b"})
    assert q.snapshot() == [{"type": "a"}, {"type": "b"}]
    q2 = make([], [])
    q2.restore([{"type": "a"}, "junk", {"no": 1}])
    assert list(q2.events) == [{"type": "a"}]
