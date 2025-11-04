from datetime import datetime

from .. import command, module, util
from .util.bluscream import *


class Bluscream(module.Module):
    name = "Bluscream"
    disabled = False

    db: util.db.AsyncDB

    async def on_load(self) -> None:
        self.db = self.bot.get_db("bluscream")

    # async def on_message(self, msg: tg.custom.Message):
    #     if msg.chat_id is not None and msg.chat_id == self.bot.uid:
    #         await msg.forward_to(-280032537)

    @command.desc("Temporarily approve someone in chat")
    @command.alias("tapprove")
    @command.usage("<timespan> [user or reply]", optional=True, reply=True)
    async def cmd_tempapprove(self, ctx: command.Context) -> str:
        """Temporarily approve a user in a chat, then unapprove after the timespan."""
        if not ctx.input:
            return "Usage: .tapprove <timespan> [user or reply]\nExample: .tapprove 1h @username"
        
        args = split_args(ctx.input)
        if not args:
            return "Please provide a timespan (e.g., 1h, 30m, 2d)"
        
        try:
            timespan = parse_timespan(args[0])
        except Exception as ex:
            return f"Invalid timespan format: {args[0]}\nExample: 1h, 30m, 2d"
        
        user = None
        
        # Get user from reply or argument
        if ctx.msg.is_reply:
            reply_msg = await ctx.msg.get_reply_message()
            user = await reply_msg.get_sender()
            await reply_msg.reply("/approve")
        elif len(args) >= 2:
            try:
                user = await self.bot.client.get_entity(args[1])
                await self.bot.client.send_message(ctx.msg.chat_id, f"/approve {user.id}")
            except Exception as ex:
                return f"Could not find user: {args[1]}"
        else:
            return "Please reply to a user or provide a user ID/username"
        
        if not user:
            return "Could not get user information"
        
        await ctx.msg.delete()
        
        # Wait for approve command to process
        await asyncio.sleep(2)
        
        timespan_fmt = strfdelta(timespan, "{days}d {hours}h {minutes}m {seconds}s")
        await self.bot.client.send_message(
            ctx.msg.chat_id, 
            message=f"{UserStr(user)}, you have been temporarily approved for {timespan_fmt}. Use your time wisely ;)"
        )
        
        # Wait for the duration
        await asyncio.sleep(timespan.total_seconds())
        
        # Unapprove the user
        await self.bot.client.send_message(ctx.msg.chat_id, f"/unapprove {user.id}")


    @command.desc("Simple say command")
    @command.usage("[text to say?]", optional=False)
    async def cmd_say(self, ctx: command.Context) -> str:
        chat_id = ctx.msg.chat_id
        text = ctx.msg.text.replace('.say ', '')
        await ctx.msg.delete()
        await self.bot.client.send_message(chat_id, text)

    @command.desc("Send local date and time to chat")
    async def cmd_time(self, ctx: command.Context) -> str:
        """Display the current local time."""
        local_time = datetime.now()
        # TODO: Get timezone from system instead of hardcoding GMT+1
        formatted_time = local_time.strftime("Local Time:\n`%H:%M %p` (`GMT+1`)\n`%d.%m.%Y`")
        return formatted_time