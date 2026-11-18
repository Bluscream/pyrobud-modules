"""Pure mapping from Telethon objects to seenbook events.

Nothing here talks to Telegram: every function works on entities the client already holds.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from telethon import types, utils

from .seenbook import Event, clip

if TYPE_CHECKING:
    from datetime import datetime

STATUS_NAMES: dict[type, str] = {
    types.UserStatusOnline: "online",
    types.UserStatusOffline: "offline",
    types.UserStatusRecently: "recently",
    types.UserStatusLastWeek: "last_week",
    types.UserStatusLastMonth: "last_month",
}


def millis(time: datetime | None) -> int | None:
    """Convert a datetime to epoch milliseconds."""
    return None if time is None else int(time.timestamp() * 1000)


def display_name(user: types.User) -> str | None:
    """Join first and last name the way Telegram shows them."""
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    return clip(name) if name else None


def username(user: types.User) -> str | None:
    """Return the main username, or the first active collectible one."""
    if user.username:
        return str(user.username)
    for extra in user.usernames or []:
        if extra.active:
            return str(extra.username)
    return None


def photo_id(user: types.User) -> int | None:
    """Return the current profile photo id, or None without a photo or for min users."""
    photo = user.photo
    return int(photo.photo_id) if isinstance(photo, types.UserProfilePhoto) else None


def account(user: types.User) -> Event:
    """Map a user to a seenbook account.

    Min users (seen in big groups without full data) only carry what they carry; their
    missing photo does not mean they have none, so the avatar is only cleared for full users.
    """
    result: Event = {"id": str(user.id), "bot": bool(user.bot)}
    if not user.min or user.first_name is not None:
        result["displayName"] = display_name(user)
    name = username(user)
    if name:
        result["username"] = clip(name)
    if (not user.min and user.photo is None) or isinstance(
        user.photo, types.UserProfilePhotoEmpty
    ):
        result["avatar"] = None
    return result


def chat_context(chat: Any, chat_id: int | None = None) -> Event | None:
    """Map a user (private chat), basic group or channel to a context.

    Without the entity, chat_id alone still gives a context of a guessed type.
    """
    if isinstance(chat, types.User):
        context: Event = {"type": "dm", "id": str(chat.id)}
        name = display_name(chat)
    elif isinstance(chat, (types.Chat, types.ChatForbidden)):
        context = {"type": "group", "id": str(utils.get_peer_id(chat))}
        name = chat.title
    elif isinstance(chat, (types.Channel, types.ChannelForbidden)):
        broadcast = bool(chat.broadcast)
        context = {
            "type": "channel" if broadcast else "group",
            "id": str(utils.get_peer_id(chat)),
        }
        name = chat.title
    elif chat_id is not None:
        return {"type": "dm" if chat_id > 0 else "group", "id": str(chat_id)}
    else:
        return None
    if name:
        context["name"] = clip(name)
    return context


def member_count(chat: Any) -> int | None:
    """Return the participant count the client already knows, without asking Telegram."""
    count = getattr(chat, "participants_count", None)
    return count if isinstance(count, int) else None


def message_seen(
    chat_id: int,
    message_id: int,
    sender: types.User | None,
    sender_id: int,
    chat: Any,
    at: int,
) -> Event:
    """Map a message to a sighting of its sender."""
    event: Event = {
        "id": f"m:{chat_id}:{message_id}",
        "type": "account_seen",
        "at": at,
        "occurrenceId": f"{chat_id}:{message_id}",
        "account": account(sender) if sender is not None else {"id": str(sender_id)},
    }
    context = chat_context(chat, chat_id)
    if context is not None:
        event["context"] = context
    return event


def status_name(status: Any) -> str | None:
    """Map a Telegram status to online, offline, recently, last_week or last_month."""
    return STATUS_NAMES.get(type(status))


def status_seen(user_id: int, user: types.User | None, status: str, at: int) -> Event:
    """Map an online status update. Only online counts as a sighting."""
    acc: Event = account(user) if user is not None else {"id": str(user_id)}
    event: Event = {
        "id": f"p:{user_id}:{status}:{at}",
        "type": "account_seen",
        "at": at,
        "account": {**acc, "status": status},
    }
    if status != "online":
        event["sighting"] = False
    return event


def typing_seen(
    user_id: int, user: types.User | None, chat: Any, chat_id: int | None, at: int
) -> Event:
    """Map a typing indicator to a sighting in its chat."""
    event: Event = {
        "id": f"t:{user_id}:{chat_id}:{at}",
        "type": "account_seen",
        "at": at,
        "account": account(user) if user is not None else {"id": str(user_id)},
    }
    context = chat_context(chat, chat_id)
    if context is not None:
        event["context"] = context
    return event


def membership(
    user: types.User,
    group: Event,
    at: int,
    *,
    left: bool = False,
    participant: Any = None,
) -> Event:
    """Map a join, a leave or a participant row to a membership event."""
    prefix = "ml" if left else "mb"
    event: Event = {
        "id": f"{prefix}:{group['id']}:{user.id}:{at}",
        "type": "membership",
        "at": at,
        "account": account(user),
        "group": group,
    }
    if left:
        event["left"] = True
        return event
    joined = getattr(participant, "date", None)
    event["joinedAt"] = millis(joined) if joined is not None else at
    if isinstance(
        participant, (types.ChannelParticipantCreator, types.ChatParticipantCreator)
    ):
        event["owner"] = True
    if isinstance(
        participant,
        (
            types.ChannelParticipantCreator,
            types.ChannelParticipantAdmin,
            types.ChatParticipantAdmin,
        ),
    ):
        rank = getattr(participant, "rank", None)
        event["roles"] = [{"name": clip(rank or "admin")}]
    return event


def crawl_seen(user: types.User, group: Event, at: int) -> Event:
    """Map a participant list row. It updates fields without counting as a sighting."""
    return {
        "id": f"c:{group['id']}:{user.id}:{at}",
        "type": "account_seen",
        "at": at,
        "account": account(user),
        "context": group,
        "sighting": False,
    }


def name_update(update: types.UpdateUserName, at: int) -> Event:
    """Map a name change Telegram pushed to us, without counting it as a sighting."""
    name = " ".join(part for part in (update.first_name, update.last_name) if part)
    acc: Event = {
        "id": str(update.user_id),
        "displayName": clip(name) if name else None,
    }
    active = [u.username for u in update.usernames or [] if u.active]
    if active:
        acc["username"] = clip(str(active[0]))
    return {
        "id": f"n:{update.user_id}:{at}",
        "type": "account_seen",
        "at": at,
        "account": acc,
        "sighting": False,
    }


def avatar_event(user: types.User, photo: int, data: bytes, at: int) -> Event:
    """Map downloaded small profile photo bytes. Telegram has no public CDN, so the bytes travel inline."""
    return {
        "id": f"av:{user.id}:{photo}",
        "type": "avatar",
        "at": at,
        "account": {"id": str(user.id)},
        "avatar": {
            "key": str(photo),
            "dataBase64": base64.b64encode(data).decode("ascii"),
        },
    }
