"""Tests for the Telegram to seenbook mapping, on real Telethon TL objects."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from telethon import types

from util import seenbook_telegram as m

AT = 1_700_000_000_000
PHOTO = 5_555
# Telethon marks channel 1234 as -100 followed by the id padded to ten digits.
CHAT_ID = -1000000001234


def user(**kw: object) -> types.User:
    base: dict[str, object] = {
        "id": 42,
        "first_name": "Ada",
        "last_name": "L",
        "username": "ada",
        "access_hash": 1,
    }
    base.update(kw)
    return types.User(**base)


def supergroup(count: int | None = 10) -> types.Channel:
    return types.Channel(
        id=1234,
        title="Club",
        photo=types.ChatPhotoEmpty(),
        date=None,
        megagroup=True,
        participants_count=count,
    )


def test_account_full_user_without_photo_clears_avatar() -> None:
    assert m.account(user()) == {
        "id": "42",
        "bot": False,
        "displayName": "Ada L",
        "username": "ada",
        "avatar": None,
    }


def test_account_min_user_keeps_avatar_unknown() -> None:
    acc = m.account(user(min=True, photo=None))
    assert "avatar" not in acc


def test_collectible_username_fallback() -> None:
    u = user(
        username=None,
        usernames=[
            types.Username(username="old", active=False),
            types.Username(username="new", active=True),
        ],
    )
    assert m.account(u)["username"] == "new"


def test_photo_id() -> None:
    assert (
        m.photo_id(user(photo=types.UserProfilePhoto(photo_id=PHOTO, dc_id=2))) == PHOTO
    )
    assert m.photo_id(user()) is None


def test_contexts() -> None:
    assert m.chat_context(supergroup()) == {
        "type": "group",
        "id": str(CHAT_ID),
        "name": "Club",
    }
    broadcast = types.Channel(
        id=1234, title="News", photo=types.ChatPhotoEmpty(), date=None, broadcast=True
    )
    assert m.chat_context(broadcast) == {
        "type": "channel",
        "id": str(CHAT_ID),
        "name": "News",
    }
    assert m.chat_context(
        types.Chat(
            id=77,
            title="Old",
            photo=types.ChatPhotoEmpty(),
            participants_count=3,
            date=None,
            version=1,
        )
    ) == {
        "type": "group",
        "id": "-77",
        "name": "Old",
    }
    assert m.chat_context(user()) == {"type": "dm", "id": "42", "name": "Ada L"}
    assert m.chat_context(None, -5) == {"type": "group", "id": "-5"}
    assert m.chat_context(None) is None


def test_message_seen_uses_chat_and_message_id() -> None:
    event = m.message_seen(CHAT_ID, 9, user(), 42, supergroup(), AT)
    assert event["id"] == f"m:{CHAT_ID}:9"
    assert event["occurrenceId"] == f"{CHAT_ID}:9"
    assert event["context"]["id"] == str(CHAT_ID)
    assert m.message_seen(CHAT_ID, 9, None, 42, None, AT)["account"] == {"id": "42"}


def test_member_count() -> None:
    assert m.member_count(supergroup(12)) == 12
    assert m.member_count(supergroup(None)) is None


def test_status() -> None:
    assert m.status_name(types.UserStatusOnline(expires=datetime.now(UTC))) == "online"
    assert m.status_name(types.UserStatusRecently()) == "recently"
    assert m.status_name(None) is None
    assert "sighting" not in m.status_seen(42, None, "online", AT)
    assert m.status_seen(42, None, "offline", AT)["sighting"] is False
    # Online then offline in the same millisecond must not collapse into one id.
    assert (
        m.status_seen(42, None, "online", AT)["id"]
        != m.status_seen(42, None, "offline", AT)["id"]
    )


def test_membership_admin_and_left() -> None:
    group = m.chat_context(supergroup())
    assert group is not None
    admin = types.ChannelParticipantAdmin(
        user_id=42,
        promoted_by=1,
        date=datetime(2026, 1, 1, tzinfo=UTC),
        admin_rights=types.ChatAdminRights(),
        rank="Mod",
    )
    event = m.membership(user(), group, AT, participant=admin)
    assert event["roles"] == [{"name": "Mod"}]
    assert event["joinedAt"] == int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    creator = types.ChannelParticipantCreator(
        user_id=42, admin_rights=types.ChatAdminRights()
    )
    assert m.membership(user(), group, AT, participant=creator)["owner"] is True
    left = m.membership(user(), group, AT, left=True)
    assert left["left"] is True
    assert left["id"].startswith("ml:")


def test_name_update_and_avatar() -> None:
    update = types.UpdateUserName(
        user_id=42,
        first_name="Ada",
        last_name="",
        usernames=[types.Username(username="ada2", active=True)],
    )
    assert m.name_update(update, AT)["account"] == {
        "id": "42",
        "displayName": "Ada",
        "username": "ada2",
    }
    avatar = m.avatar_event(user(), PHOTO, b"\xff\xd8jpeg", AT)
    assert avatar["avatar"] == {
        "key": str(PHOTO),
        "dataBase64": base64.b64encode(b"\xff\xd8jpeg").decode(),
    }
    assert avatar["id"] == f"av:42:{PHOTO}"
