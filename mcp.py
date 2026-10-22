"""MCP server for this account, served over streamable HTTP with a bearer token.

Configure per account in the bot's TOML file; the module stays idle without it:

    [mcp]
    port = 8611
    token = "<random secret>"
    # host = "0.0.0.0"
"""

import hmac
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

import telethon as tg
from aiohttp import web

from .. import module

PROTOCOL_VERSION = "2025-06-18"
ChatRef = Union[int, str]


def _chat_ref(value: Any) -> ChatRef:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        return text


def _message(msg: tg.custom.Message) -> Dict[str, Any]:
    return {
        "id": msg.id,
        "chat_id": msg.chat_id,
        "sender_id": msg.sender_id,
        "date": msg.date.isoformat() if msg.date else None,
        "out": msg.out,
        "text": msg.raw_text,
        "reply_to": msg.reply_to_msg_id,
        "media": type(msg.media).__name__ if msg.media else None,
        "links": _links(msg),
    }


def _links(msg: tg.custom.Message) -> List[Dict[str, str]]:
    """URLs behind text links and inline buttons, which raw_text drops."""
    links = [
        {"text": text, "url": ent.url}
        for ent, text in (msg.get_entities_text(tg.tl.types.MessageEntityTextUrl) or [])
    ]
    for row in msg.buttons or []:
        links.extend({"text": b.text, "url": b.url} for b in row if getattr(b, "url", None))
    return links


def _entity(ent: Any) -> Dict[str, Any]:
    return {
        "id": tg.utils.get_peer_id(ent),
        "type": type(ent).__name__,
        "name": tg.utils.get_display_name(ent),
        "username": getattr(ent, "username", None),
    }


class MCPModule(module.Module):
    name = "MCP"

    runner: Optional[web.AppRunner]
    token: str
    tools: Dict[str, Dict[str, Any]]

    async def on_load(self) -> None:
        self.runner = None
        self.tools = {
            "whoami": {
                "description": "The Telegram account this server acts as.",
                "schema": {"type": "object", "properties": {}},
                "run": self.tool_whoami,
            },
            "list_dialogs": {
                "description": "Recent chats, newest first, with unread counts.",
                "schema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 30}},
                },
                "run": self.tool_list_dialogs,
            },
            "get_messages": {
                "description": "Messages from one chat, newest first. Optional text search and paging by offset_id.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "chat": {"type": ["integer", "string"], "description": "Chat id, @username or phone"},
                        "limit": {"type": "integer", "default": 20},
                        "search": {"type": "string"},
                        "offset_id": {"type": "integer", "description": "Return messages older than this id"},
                    },
                    "required": ["chat"],
                },
                "run": self.tool_get_messages,
            },
            "search_messages": {
                "description": "Search messages across all chats.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["query"],
                },
                "run": self.tool_search_messages,
            },
            "get_entity": {
                "description": "Resolve a user, group or channel.",
                "schema": {
                    "type": "object",
                    "properties": {"chat": {"type": ["integer", "string"]}},
                    "required": ["chat"],
                },
                "run": self.tool_get_entity,
            },
            "send_message": {
                "description": "Send a text message as this account.",
                "schema": {
                    "type": "object",
                    "properties": {
                        "chat": {"type": ["integer", "string"]},
                        "text": {"type": "string"},
                        "reply_to": {"type": "integer"},
                    },
                    "required": ["chat", "text"],
                },
                "run": self.tool_send_message,
            },
            "mark_read": {
                "description": "Mark a chat as read.",
                "schema": {
                    "type": "object",
                    "properties": {"chat": {"type": ["integer", "string"]}},
                    "required": ["chat"],
                },
                "run": self.tool_mark_read,
            },
        }

    async def on_start(self, time_us: int) -> None:
        cfg = self.bot.config.get("mcp", {})
        if not cfg.get("port") or not cfg.get("token"):
            self.log.info("No [mcp] port/token in config; MCP server not started")
            return

        self.token = str(cfg["token"])
        app = web.Application(client_max_size=4 * 1024 * 1024)
        app.router.add_post("/mcp", self.handle)
        app.router.add_get("/mcp", self.handle_get)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, cfg.get("host", "0.0.0.0"), int(cfg["port"])).start()
        self.log.info(f"MCP server listening on port {cfg['port']}")

    async def on_stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    def authorized(self, request: web.Request) -> bool:
        header = request.headers.get("Authorization", "")
        return header.startswith("Bearer ") and hmac.compare_digest(header[7:], self.token)

    async def handle_get(self, request: web.Request) -> web.Response:
        # No server-initiated stream; streamable HTTP lets the server refuse GET.
        return web.Response(status=405)

    async def handle(self, request: web.Request) -> web.Response:
        if not self.authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(self.error(None, -32700, "Parse error"), status=400)

        if isinstance(body, list):
            replies = [r for r in [await self.dispatch(m) for m in body] if r is not None]
            return web.json_response(replies) if replies else web.Response(status=202)

        reply = await self.dispatch(body)
        return web.json_response(reply) if reply is not None else web.Response(status=202)

    @staticmethod
    def error(msg_id: Any, code: int, text: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    async def dispatch(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}
        if msg_id is None:
            return None  # notification, e.g. notifications/initialized

        if method == "initialize":
            result: Dict[str, Any] = {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pyrobud-mcp", "version": "1.0.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": name, "description": t["description"], "inputSchema": t["schema"]}
                    for name, t in self.tools.items()
                ]
            }
        elif method == "tools/call":
            result = await self.call_tool(params.get("name", ""), params.get("arguments") or {})
        else:
            return self.error(msg_id, -32601, f"Method not found: {method}")

        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

        run: Callable[[Dict[str, Any]], Awaitable[Any]] = tool["run"]
        try:
            data = await run(args)
        except Exception as e:  # reported to the caller as a tool error, not a transport failure
            self.log.warning(f"MCP tool {name} failed", exc_info=e)
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}

        text = json.dumps(data, ensure_ascii=False, default=str)
        return {"content": [{"type": "text", "text": text}], "isError": False}

    async def tool_whoami(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return _entity(self.bot.user)

    async def tool_list_dialogs(self, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        dialogs = await self.bot.client.get_dialogs(limit=int(args.get("limit", 30)))
        return [
            {**_entity(d.entity), "unread": d.unread_count, "last_message": d.message.raw_text if d.message else None}
            for d in dialogs
        ]

    async def tool_get_messages(self, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        msgs = await self.bot.client.get_messages(
            _chat_ref(args["chat"]),
            limit=int(args.get("limit", 20)),
            search=args.get("search"),
            offset_id=int(args.get("offset_id", 0)),
        )
        return [_message(m) for m in msgs]

    async def tool_search_messages(self, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        msgs = await self.bot.client.get_messages(None, limit=int(args.get("limit", 20)), search=args["query"])
        return [_message(m) for m in msgs]

    async def tool_get_entity(self, args: Dict[str, Any]) -> Dict[str, Any]:
        return _entity(await self.bot.client.get_entity(_chat_ref(args["chat"])))

    async def tool_send_message(self, args: Dict[str, Any]) -> Dict[str, Any]:
        msg = await self.bot.client.send_message(
            _chat_ref(args["chat"]), args["text"], reply_to=args.get("reply_to")
        )
        return _message(msg)

    async def tool_mark_read(self, args: Dict[str, Any]) -> Dict[str, Any]:
        await self.bot.client.send_read_acknowledge(_chat_ref(args["chat"]))
        return {"ok": True}
