import asyncio
import os
import time
import traceback
from base64 import b64encode, b64decode

import telethon as tg
from telethon.tl.types import InputPeerChannel
from re import compile

def has_real_media(msg: tg.custom.Message):
    return True if (msg.document or msg.photo) and msg.web_preview else False


def has_affecting_media(msg: tg.custom.Message):
    return True if msg.photo or msg.video or msg.sticker or msg.web_preview else False


tg.custom.Message.has_real_media = has_real_media
tg.custom.Message.has_affecting_media = has_affecting_media

telegram_uid_regex = compile(r"(?<!\d)\d{6,9}(?!\d)")

def splitMsg(msg, chars=4096):
    return [msg[i:i + chars] for i in range(0, len(msg), chars)]

def get_id(peer_id):
    return peer_id.user_id if hasattr(peer_id, 'user_id') else 0

def ChatStr(chat: tg.types.Chat):
    if isinstance(chat, InputPeerChannel): return f"{chat.channel_id}"
    if hasattr(chat, "title"): return f"\"{chat.title}\" ({chat.id})"
    return f"{chat.id}"


def UserStr(user: tg.types.User, full: bool = False, dont_mention: bool = False):
    if dont_mention:
        return f'<user id="{user.id}" first_name="{user.first_name}" last_name="{user.last_name}" user_name="{user.username}"/>'
    fullname = ""
    if user.first_name: fullname += user.first_name
    if user.last_name: fullname += f" {user.last_name}"
    result = f"\"[{fullname if fullname else user.id}](tg://user?id={user.id})\""
    if full:
        if user.username: result += f" @{user.username}"
        if user.id: result += f" (`{user.id})`"
    return result

def ParseUserStr(first_name: str = None, last_name: str = None, user_name: str = None, id: int = None, full: bool = None):
    return UserStr(tg.types.User(id, first_name=first_name, last_name=last_name, username=user_name), full)


def sanitize(input):
    return input.replace("`", "")


def add_lrm(str_to_modify):
    '''Add a Left to Right Mark (LRM) at provided string start'''
    barray = bytearray(b"\xe2\x80\x8e")
    str_to_modify = str_to_modify.encode("utf-8")
    for b in str_to_modify:
        barray.append(b)
    str_to_modify = barray.decode("utf-8")
    return str_to_modify


def base64encode(input: str):
    return b64encode(bytes(str(input), "utf-8")).decode("utf-8", "ignore")


def base64decode(input: str):
    return b64decode(input).decode("utf-8", "ignore")


def mention_user(user):
    if user.username:
        return f"@{user.username}"
    else:
        return f"[{tg.utils.get_display_name(user)}](tg://user?id={user.id})"


def time_us():
    return int(time.time() * 1000000)


def time_ms():
    return int(time_us() / 1000)


def format_duration_us(t_us):
    t_us = int(t_us)

    t_ms = t_us / 1000
    t_s = t_ms / 1000
    t_m = t_s / 60
    t_h = t_m / 60
    t_d = t_h / 24

    if t_d >= 1:
        rem_h = t_h % 24
        rem_m = t_m % 60
        rem_s = t_s % (24 * 60 * 60) % 60
        return "%dd%dh%dm%ds" % (t_d, rem_h, rem_m, rem_s)
    elif t_h >= 1:
        rem_m = t_m % 60
        rem_s = t_s % (60 * 60) % 60
        return "%dh%dm%ds" % (t_h, rem_m, rem_s)
    elif t_m >= 1:
        rem_s = t_s % 60
        return "%dm%ds" % (t_m, rem_s)
    elif t_s >= 10:
        return "%ds" % t_s
    elif t_ms >= 10:
        return "%d ms" % t_ms
    else:
        return "%d μs" % t_us


def find_prefixed_funcs(obj, prefix):
    results = []

    for sym in dir(obj):
        if sym.startswith(prefix):
            name = sym[len(prefix):]
            func = getattr(obj, sym)
            if not callable(func):
                continue

            results.append((name, func))

    return results


def filter_code_block(inp):
    if inp.startswith("```") and inp.endswith("```"):
        inp = inp[3:][:-3]
    elif inp.startswith("`") and inp.endswith("`"):
        inp = inp[1:][:-1]

    return inp


def format_exception(exp):
    tb = traceback.extract_tb(exp.__traceback__)

    # Replace absolute paths with relative paths
    cwd = os.getcwd()
    for frame in tb:
        if cwd in frame.filename:
            frame.filename = os.path.relpath(frame.filename)

    stack = "".join(traceback.format_list(tb))
    msg = str(exp)
    if msg:
        msg = ": " + msg

    return f"Traceback (most recent call last):\n{stack}{type(exp).__name__}{msg}"


async def run_sync(func):
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(None, func)
    await future
    return future.result()


async def msg_download_file(download_msg, status_msg, destination=bytes, file_type="file"):
    last_percent = -5

    def prog_func(current_bytes, total_bytes):
        nonlocal last_percent

        if not status_msg:
            return

        # Only edit message if progress >= 5%
        # This reduces Telegram rate-limit exhaustion
        percent = int((current_bytes / total_bytes) * 100)
        if abs(percent - last_percent) >= 5:
            loop = asyncio.get_event_loop()
            loop.create_task(status_msg.result(f"Downloading {file_type}... {percent}% complete"))

        last_percent = percent

    return await download_msg.download_media(file=destination, progress_callback=prog_func)
