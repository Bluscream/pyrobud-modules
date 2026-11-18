"""Platform-neutral seenbook client: batching queue, HTTP posting and the sighting throttle.

Shared by the Red cog (red-discordbot-cogs/staubsauger/seenbook.py) and the Pyrobud module
(pyrobud-modules/util/seenbook.py). Keep the copies identical.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

import aiohttp
from yarl import URL

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable, Iterable

Event = dict[str, Any]
Observer = dict[str, str]

SEEN_STEP_MS: Final = 600_000
MAX_QUEUE: Final = 20_000
FLUSH_AT: Final = 500
MAX_BATCH: Final = 1000
MIN_BATCH: Final = 50
BASE_BACKOFF: Final = 5.0
MAX_BACKOFF: Final = 300.0
SHORT: Final = 300
HTTP_BAD_REQUEST: Final = 400
HTTP_TOO_LARGE: Final = 413
REQUEST_TIMEOUT: Final = aiohttp.ClientTimeout(total=60)


def now_ms() -> int:
    """Return the current time in epoch milliseconds."""
    return int(time.time() * 1000)


def clip(text: str) -> str:
    """Cut text to the server's short text limit."""
    return text[:SHORT]


@dataclass(frozen=True, slots=True)
class PostResult:
    """Outcome of one POST. A non-empty error means the batch was not taken."""

    status: int
    accepted: int = 0
    duplicates: int = 0
    rejected: int = 0
    first_rejection: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        """Whether the server took the batch."""
        return not self.error

    def describe(self) -> str:
        """Return a sentence for logs and the status command."""
        if self.ok:
            return f"The server took {self.accepted} new events, already knew {self.duplicates} and rejected {self.rejected}."
        return f"{self.error} (HTTP {self.status})" if self.status else self.error


async def post_events(
    session: aiohttp.ClientSession,
    server_url: str,
    token: str,
    observer: Observer,
    events: list[Event],
) -> PostResult:
    """POST one batch. Never raises for network or server errors; the token is never logged."""
    url = URL(server_url) / "api/v1/events"
    body = {"v": 1, "observer": observer, "events": events}
    try:
        async with session.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        ) as response:
            if response.status >= HTTP_BAD_REQUEST:
                text = (await response.text())[:200]
                return PostResult(response.status, error=f"The server answered: {text}")
            data = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as e:
        return PostResult(0, error=f"The request failed: {type(e).__name__}")
    rejected = data.get("rejected") or []
    first = str(rejected[0].get("error", "")) if rejected else ""
    return PostResult(
        response.status,
        int(data.get("accepted", 0)),
        int(data.get("duplicates", 0)),
        len(rejected),
        first,
    )


class Throttle:
    """Lets one sighting per key through every 10 minutes, in either direction of time."""

    def __init__(self, step_ms: int = SEEN_STEP_MS, max_keys: int = 200_000) -> None:
        self.step_ms = step_ms
        self.max_keys = max_keys
        self.spans: dict[str, list[int]] = {}

    def due(self, key: str, at: int) -> bool:
        """Whether a sighting under this key at this time should be sent."""
        span = self.spans.get(key)
        if span is None:
            if len(self.spans) >= self.max_keys:
                self.spans.clear()
            self.spans[key] = [at, at]
            return True
        if at - span[1] > self.step_ms:
            span[1] = at
            return True
        if span[0] - at > self.step_ms:
            span[0] = at
            return True
        return False


@dataclass(slots=True)
class Stats:
    """Counters for the status command."""

    sent: int = 0
    duplicates: int = 0
    rejected: int = 0
    dropped: int = 0
    status: str = "Nothing was sent yet."


@dataclass(slots=True)
class Settings:
    """Where and how often to send."""

    server_url: str = ""
    token: str = ""
    flush_seconds: float = 10.0

    @property
    def ready(self) -> bool:
        """Whether both the server and the token are set."""
        return bool(self.server_url and self.token)


@dataclass(slots=True)
class EventQueue:
    """Bounded in-memory queue. Oldest events go first when it overflows; failures back off exponentially."""

    post: Callable[[Settings, Observer, list[Event]], Awaitable[PostResult]]
    log: logging.Logger
    settings: Settings = field(default_factory=Settings)
    observer: Observer | None = None
    max_queue: int = MAX_QUEUE
    events: deque[Event] = field(default_factory=deque)
    in_flight: list[Event] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)
    batch_size: int = MAX_BATCH
    failures: int = 0
    next_attempt: float = 0.0
    dirty: bool = False
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _wake: asyncio.Event = field(default_factory=asyncio.Event)
    _task: asyncio.Task[None] | None = None

    def __len__(self) -> int:
        """Return the number of events waiting."""
        return len(self.events)

    def enqueue(self, event: Event) -> None:
        """Add one event; never blocks."""
        self.events.append(event)
        self.dirty = True
        if len(self.events) > self.max_queue:
            excess = len(self.events) - self.max_queue
            for _ in range(excess):
                self.events.popleft()
            self.drop(excess, "The queue was full, so the oldest ones had to go.")
        if len(self.events) >= FLUSH_AT:
            self._wake.set()

    def extend(self, events: Iterable[Event]) -> None:
        """Add several events."""
        for event in events:
            self.enqueue(event)

    def drop(self, count: int, why: str) -> None:
        """Count and log events that will never be sent."""
        self.stats.dropped += count
        self.log.warning("Dropped %d events. %s", count, why)

    def snapshot(self) -> list[Event]:
        """Everything not yet confirmed by the server, for persistence."""
        return [*self.in_flight, *self.events]

    def restore(self, saved: object) -> None:
        """Put persisted events back in front of anything queued since."""
        if isinstance(saved, list):
            restored = [
                e
                for e in saved
                if isinstance(e, dict) and isinstance(e.get("type"), str)
            ]
            self.events.extendleft(reversed(restored))

    def reconfigure(self, settings: Settings) -> None:
        """Apply new settings and retry at once."""
        self.settings = settings
        self.failures = 0
        self.next_attempt = 0.0
        self._wake.set()

    async def _send_next(self, observer: Observer) -> bool:
        count = min(self.batch_size, len(self.events))
        self.in_flight = [self.events.popleft() for _ in range(count)]
        result = await self.post(self.settings, observer, self.in_flight)
        batch, self.in_flight = self.in_flight, []
        self.dirty = True
        if result.ok:
            self.failures = 0
            self.stats.sent += result.accepted
            self.stats.duplicates += result.duplicates
            self.stats.rejected += result.rejected
            self.stats.status = f"{time.strftime('%H:%M:%S')}: {result.describe()}"
            if result.rejected:
                self.log.warning(
                    "The server rejected %d events. The first reason was: %s",
                    result.rejected,
                    result.first_rejection,
                )
            return True
        too_large = result.status == HTTP_TOO_LARGE
        if result.status == HTTP_BAD_REQUEST or (too_large and len(batch) <= MIN_BATCH):
            self.drop(len(batch), f"The server refused the batch: {result.describe()}")
        else:
            self.events.extendleft(reversed(batch))
            if too_large:
                self.batch_size = max(MIN_BATCH, len(batch) // 2)
                return True
        delay = min(MAX_BACKOFF, BASE_BACKOFF * 2**self.failures)
        self.failures += 1
        self.next_attempt = time.monotonic() + delay
        self.stats.status = f"{time.strftime('%H:%M:%S')}: {result.describe()} Trying again in {round(delay)} seconds."
        self.log.warning(
            "Sending failed: %s Next try in %ds.", result.describe(), round(delay)
        )
        return False

    async def flush(self, *, manual: bool = False) -> None:
        """Send until empty or a failure. A manual flush ignores the backoff."""
        observer = self.observer
        if observer is None or not self.settings.ready or not self.events:
            return
        if not manual and time.monotonic() < self.next_attempt:
            return
        async with self._lock:
            more = True
            while more and self.events:
                more = await self._send_next(observer)

    async def _run(self) -> None:
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.settings.flush_seconds)
            self._wake.clear()
            try:
                await self.flush()
            except Exception:  # the loop must survive anything a single flush throws
                self.log.exception("Sending the queue failed.")

    def start(self) -> None:
        """Start the background sender."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    def stop(self) -> None:
        """Stop the sender and put an unconfirmed batch back."""
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self.in_flight:
            self.events.extendleft(reversed(self.in_flight))
            self.in_flight = []
