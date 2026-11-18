"""Staubsauger: reports the people this account sees to a self-hosted seenbook server.

Configure per account in the bot's TOML file; the module stays idle without url and token:

    [staubsauger]
    url = "http://192.168.2.11:8787"
    token = "<client token>"
    # flush_seconds = 10
    # avatars = true                  # download small profile photos, once per photo
    # avatar_interval = 3             # seconds between two photo downloads
    # active_member_limit = 5000      # largest chat .sbbackfill fetches participants of
    # passive_member_limit = 1000000  # largest chat whose received updates are reported
    # allowlist = [-1001234567890]    # chat ids that ignore both limits

Two limits: the active one covers anything that sends extra requests to Telegram (the
backfill command). The passive one covers updates Telegram pushes to us anyway (messages,
joins and leaves, typing, status). Passive collection never makes a request; avatars are the
one exception and are rate limited separately.
"""

import asyncio
from typing import Any, Dict, List, Optional

import telethon as tg
from telethon import types

from .. import command, module
from .util.seenbook import (
    EventQueue,
    Observer,
    PostResult,
    Settings,
    Throttle,
    now_ms,
    post_events,
)
from .util.seenbook_telegram import (
    avatar_event,
    chat_context,
    crawl_seen,
    display_name,
    member_count,
    membership,
    message_seen,
    millis,
    name_update,
    photo_id,
    status_name,
    status_seen,
    typing_seen,
    username,
)

PERSIST_SECONDS = 30
MAX_AVATAR_WAITING = 500
AVATAR_BACKPRESSURE = 1000
MAX_KNOWN_AVATARS = 100_000


class StaubsaugerModule(module.Module):
    name = "Staubsauger"

    queue: Optional[EventQueue]
    throttle: Throttle
    tasks: List["asyncio.Task[None]"]
    avatar_wanted: Dict[int, types.User]
    avatar_known: Dict[int, int]
    cfg: Dict[str, Any]

    async def on_load(self) -> None:
        self.db = self.bot.get_db("staubsauger")
        self.queue = None
        self.throttle = Throttle()
        self.tasks = []
        self.avatar_wanted = {}
        self.avatar_known = {}
        self.cfg = {}

    async def on_start(self, time_us: int) -> None:
        self.cfg = dict(self.bot.config.get("staubsauger", {}))
        if not self.cfg.get("url") or not self.cfg.get("token"):
            self.log.info("No [staubsauger] url/token in config; collecting nothing")
            return
        if self.queue is not None:
            return
        me = self.bot.user
        observer: Observer = {
            "accountId": str(me.id),
            "accountName": username(me) or display_name(me) or str(me.id),
        }
        settings = Settings(
            str(self.cfg["url"]).rstrip("/"),
            str(self.cfg["token"]),
            float(self.cfg.get("flush_seconds", 10)),
        )
        self.queue = EventQueue(
            post=self._post, log=self.log, settings=settings, observer=observer
        )
        self.queue.restore(await self.db.get("queue", []))
        self.queue.start()
        loop = asyncio.get_running_loop()
        self.tasks = [loop.create_task(self._persist_loop())]
        if self.cfg.get("avatars", True):
            self.tasks.append(loop.create_task(self._avatar_loop()))
        self.bot.client.add_event_handler(
            self.on_raw_name, tg.events.Raw(types.UpdateUserName)
        )
        self.log.info(
            f"Reporting to seenbook, {len(self.queue)} events restored from the last run"
        )

    async def on_stop(self) -> None:
        if self.queue is None:
            return
        self.bot.client.remove_event_handler(self.on_raw_name)
        for task in self.tasks:
            task.cancel()
        self.queue.stop()
        await self._persist()
        self.queue = None

    async def _post(
        self, settings: Settings, observer: Observer, batch: List[Dict[str, Any]]
    ) -> PostResult:
        return await post_events(
            self.bot.http, settings.server_url, settings.token, observer, batch
        )

    async def _persist(self) -> None:
        if self.queue is not None and self.queue.dirty:
            self.queue.dirty = False
            await self.db.put("queue", self.queue.snapshot())

    async def _persist_loop(self) -> None:
        while True:
            await asyncio.sleep(PERSIST_SECONDS)
            try:
                await self._persist()
            except Exception:  # keep the loop alive; the next round retries
                self.log.exception("Saving the queue failed")

    def allowed(self, chat_id: Optional[int]) -> bool:
        return chat_id is not None and chat_id in self.cfg.get("allowlist", [])

    def passive_ok(self, chat_id: Optional[int], chat: Any) -> bool:
        if self.allowed(chat_id):
            return True
        count = member_count(chat)
        return count is None or count <= int(
            self.cfg.get("passive_member_limit", 1_000_000)
        )

    def want_avatar(self, user: types.User) -> None:
        """Remember a user whose current photo was not sent yet. Never makes a request."""
        if (
            user.min
            or user.bot
            or user.id == self.bot.uid
            or not self.cfg.get("avatars", True)
        ):
            return
        pid = photo_id(user)
        if pid is None or self.avatar_known.get(user.id) == pid:
            return
        if len(self.avatar_wanted) < MAX_AVATAR_WAITING:
            self.avatar_wanted[user.id] = user

    def remember_avatar(self, user_id: int, pid: int) -> None:
        if len(self.avatar_known) >= MAX_KNOWN_AVATARS:
            self.avatar_known.clear()
        self.avatar_known[user_id] = pid

    async def _avatar_loop(self) -> None:
        interval = float(self.cfg.get("avatar_interval", 3))
        while True:
            await asyncio.sleep(interval)
            queue = self.queue
            if (
                queue is None
                or not self.avatar_wanted
                or len(queue) > AVATAR_BACKPRESSURE
            ):
                continue
            try:
                await self._fetch_avatar(queue)
            except Exception:  # one bad photo must not end the loop
                self.log.exception("Fetching a profile photo failed")

    async def _fetch_avatar(self, queue: EventQueue) -> None:
        user_id, user = self.avatar_wanted.popitem()
        pid = photo_id(user)
        if pid is None:
            return
        if await self.db.get(f"avatar.{user_id}") == pid:
            self.remember_avatar(user_id, pid)
            return
        try:
            data = await self.bot.client.download_profile_photo(
                user, file=bytes, download_big=False
            )
        except tg.errors.FloodWaitError as e:
            self.log.info(
                f"Telegram asked to wait {e.seconds}s before the next profile photo"
            )
            self.avatar_wanted.setdefault(user_id, user)
            await asyncio.sleep(e.seconds)
            return
        except tg.errors.RPCError as e:
            self.log.debug(
                f"Profile photo of {user_id} unavailable: {type(e).__name__}"
            )
            data = None
        if isinstance(data, bytes) and data:
            queue.enqueue(avatar_event(user, pid, data, now_ms()))
        self.remember_avatar(user_id, pid)
        await self.db.put(f"avatar.{user_id}", pid)

    async def on_message(self, msg: tg.custom.Message) -> None:
        queue = self.queue
        sender_id = msg.sender_id
        if queue is None or not sender_id or sender_id < 0 or sender_id == self.bot.uid:
            return
        chat = msg.chat
        if not self.passive_ok(msg.chat_id, chat):
            return
        sender = msg.sender if isinstance(msg.sender, types.User) else None
        queue.enqueue(
            message_seen(
                msg.chat_id,
                msg.id,
                sender,
                sender_id,
                chat,
                millis(msg.date) or now_ms(),
            )
        )
        if sender is not None:
            self.want_avatar(sender)

    async def on_chat_action(self, event: tg.events.ChatAction.Event) -> None:
        queue = self.queue
        joined = event.user_joined or event.user_added
        left = event.user_left or event.user_kicked
        if (
            queue is None
            or not (joined or left)
            or not self.passive_ok(event.chat_id, event.chat)
        ):
            return
        group = chat_context(event.chat, event.chat_id)
        if group is None:
            return
        at = now_ms()
        for user in event.users or []:
            if isinstance(user, types.User) and user.id != self.bot.uid:
                queue.enqueue(membership(user, group, at, left=bool(left)))

    async def on_user_update(self, event: tg.events.UserUpdate.Event) -> None:
        queue = self.queue
        user_id = event.user_id
        if queue is None or not user_id or user_id == self.bot.uid:
            return
        user = event.sender if isinstance(event.sender, types.User) else None
        at = now_ms()
        status = status_name(event.status)
        if status is not None:
            if self.throttle.due(f"p:{user_id}:{status}", at):
                queue.enqueue(status_seen(user_id, user, status, at))
        elif (
            event.typing
            and self.passive_ok(event.chat_id, event.chat)
            and self.throttle.due(f"t:{user_id}:{event.chat_id}", at)
        ):
            queue.enqueue(typing_seen(user_id, user, event.chat, event.chat_id, at))
        if user is not None:
            self.want_avatar(user)

    async def on_raw_name(self, update: types.UpdateUserName) -> None:
        if self.queue is not None and update.user_id != self.bot.uid:
            self.queue.enqueue(name_update(update, now_ms()))

    @command.desc("Show the Staubsauger queue, or send it now with 'flush'")
    @command.alias("sb")
    @command.usage("[flush]", optional=True)
    async def cmd_staubsauger(self, ctx: command.Context) -> str:
        queue = self.queue
        if queue is None:
            return "Staubsauger is not configured: add url and token under [staubsauger] in the config."
        if ctx.input.strip() == "flush":
            await queue.flush(manual=True)
            await self._persist()
        s = queue.stats
        return (
            f"Queued {len(queue)}, sent {s.sent}, duplicates {s.duplicates}, rejected {s.rejected}, dropped {s.dropped}, "
            f"avatars waiting {len(self.avatar_wanted)}\n{s.status}"
        )

    @command.desc(
        "Queue a chat's participant list for seenbook; fetching it counts against the active member limit"
    )
    @command.alias("sbb")
    @command.usage("[chat id or @username, default this chat]", optional=True)
    async def cmd_sbbackfill(self, ctx: command.Context) -> str:
        queue = self.queue
        if queue is None:
            return "Staubsauger is not configured."
        text = ctx.input.strip()
        ref: Any = (
            (int(text) if text.lstrip("-").isdigit() else text)
            if text
            else ctx.msg.chat_id
        )
        client = self.bot.client
        entity = await client.get_entity(ref)
        group = chat_context(entity)
        if group is None or group["type"] == "dm":
            return "That is not a group or channel."
        limit = int(self.cfg.get("active_member_limit", 5000))
        total = (await client.get_participants(entity, limit=0)).total
        if total > limit and not self.allowed(tg.utils.get_peer_id(entity)):
            return f"{group.get('name', group['id'])} has {total} members, more than the active limit of {limit}. Add it to allowlist to fetch it anyway."
        at = now_ms()
        count = 0
        try:
            async for user in client.iter_participants(entity):
                if isinstance(user, types.User) and user.id != self.bot.uid:
                    queue.enqueue(crawl_seen(user, group, at))
                    queue.enqueue(
                        membership(user, group, at, participant=user.participant)
                    )
                    count += 1
        except tg.errors.FloodWaitError as e:
            return f"Telegram asked to wait {e.seconds}s; queued {count} participants so far."
        return f"Queued {count} of {total} participants of {group.get('name', group['id'])}."
