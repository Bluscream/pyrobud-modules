from re import MULTILINE, finditer
from typing import TYPE_CHECKING
import telethon as tg

from .. import command, module
from .util.bluscream import UserStr, telegram_uid_regex

if TYPE_CHECKING:
    from .classes.DataCenter import DataCenter


class DebugModuleAddon(module.Module):
    name = "Debug Extensions"
    disabled = False

    @command.desc("Prints info about a certain user")
    @command.alias("uinfo")
    async def cmd_userinfo(self, ctx: command.Context) -> str:
        """Get detailed information about a user including datacenter location."""
        # Get user from input or reply
        user: tg.types.User = None
        if ctx.input:
            try:
                user = await self.bot.client.get_entity(int(ctx.input))
            except (ValueError, Exception) as ex:
                return f"Could not find user with ID {ctx.input}: {ex}"
        elif ctx.msg.is_reply:
            reply_msg = await ctx.msg.get_reply_message()
            user = await reply_msg.get_sender()
        
        if not user:
            return "Could not find user anywhere! Provide a user ID or reply to a message."
        
        # Build basic info
        reply_lines = [
            f'**Display Name:** `{user.first_name or ""} {user.last_name or ""}`'.strip(),
            f'**Username:** `@{user.username}`' if user.username else '**Username:** N/A',
            f'**User ID:** `{user.id}`'
        ]
        
        # Add status if available
        if hasattr(user, 'status') and user.status:
            try:
                reply_lines.append(f'**Status:** `{user.status.stringify()}`')
            except:
                pass
        
        # Add datacenter info if available
        if hasattr(self.bot, 'dc') and self.bot.dc and user.photo and hasattr(user.photo, 'dc_id'):
            dc_id = user.photo.dc_id
            if dc_id in self.bot.dc.dcs:
                dc = self.bot.dc.dcs[dc_id]
                if dc.geo:
                    reply_lines.append(f'**Datacenter:** `{dc.geo.city}, {dc.geo.country} (DC{dc.id})`')
                    reply_lines.append(f'**Region:** `{dc.geo.continent}`')
                else:
                    reply_lines.append(f'**Datacenter:** `DC{dc.id}` (no geo info)')
            else:
                reply_lines.append(f'**Datacenter:** `DC{dc_id}` (not in cache)')
        
        return '\n'.join(reply_lines)

    @command.desc("Prints info about data centers")
    @command.alias("dcs")
    async def cmd_datacenters(self, ctx: command.Context) -> str:
        """Display information about all known Telegram datacenters."""
        if not hasattr(self.bot, 'dc') or not self.bot.dc:
            return "DataCenters not initialized (Startup module may be disabled)"
        
        if not self.bot.dc.dcs:
            return "No datacenters in cache yet"
        
        reply = ["**Telegram Data Centers:**\n"]
        for dc in self.bot.dc.dcs.values():
            geo_info = f"{dc.geo.continent}" if dc.geo else "Unknown"
            ping_info = f"{dc.ping}ms" if dc.ping >= 0 else "N/A"
            reply.append(f'**DC{dc.id}** ({dc.code}): {geo_info} - {ping_info}')
        
        return '\n'.join(reply)

    @command.desc("Dump all the data of a message to your cloud")
    @command.alias("mdp")
    async def cmd_mdumpprivate(self, ctx: command.Context) -> str:
        if not ctx.msg.is_reply: return
        reply_msg = await ctx.msg.get_reply_message()
        await ctx.msg.delete()
        data = f"```{reply_msg.stringify()}```"
        await self.bot.client.send_message("me", data)

    @command.desc("Convert all tg uids to profile links")
    @command.alias("idlink", "linkids", "linkid")
    async def cmd_idlinks(self, ctx: command.Context) -> str:
        text = ctx.input
        if not text and ctx.msg.is_reply: text = (await ctx.msg.get_reply_message()).text
        matches = finditer(telegram_uid_regex, text, MULTILINE)
        uids = set()
        for _, match in enumerate(matches, start=1):
            uids.add(match.group())

        if len(uids) < 1: return "No UIDs found in the given message."
        ret = f"Found **{len(uids)}** UIDs:\n"
        for uid in uids:
            try:
                user = await self.bot.client.get_entity(int(uid))
                ret += f"\n - {UserStr(user, True)}"
            except: ret += f"\n - [{uid}](tg://user?id={uid})"
        return ret

    @command.desc("Returns the profile link for a user id")
    async def cmd_link(self, ctx: command.Context) -> str:
        uid = ctx.input
        # try:
        user = await self.bot.client.get_entity(int(uid))
        fullname = ""
        if user.first_name: fullname += user.first_name
        if user.last_name: fullname += f" {user.last_name}"
        
        self.bot.client.send_message(ctx.msg.chat_id, message=f"[{fullname if fullname else user.id}](tg://user?id={user.id})") # , parse_mode=tg.client.messageparse.MessageParseMethods.parse_mode)
        # except: return f"[{uid}](tg://user?id={uid})"