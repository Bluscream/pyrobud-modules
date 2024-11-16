from datetime import timedelta
import telethon as tg
from telethon.tl.types import ChannelParticipantsAdmins
from .. import command, module, util

class LoggerModule(module.Module):
    name = "Logger"
    disabled = True
    notify = True

    async def on_load(self):
        pass

    async def on_chat_action(self, action: tg.events.chataction.ChatAction.Event):
        if self.disabled: return
        if hasattr(action, "user_id") and action.user_id is not None and action.user_id != self.bot.uid: return
        if hasattr(action, "original_update") and isinstance(action.original_update, tg.types.UpdatePinnedChannelMessages): return
        txt = action.stringify()
        notify = self.notify
        if action.user_joined or action.user_left:
            _action = "⤵ Joined" if action.user_joined else "🔙 Left"
            txt = f"{action.action_message.date}\n{_action} {util.bluscream.ChatStr(action.chat)}"
            if action.user_joined:
                admins = await self.bot.client.get_participants(action.chat, filter=ChannelParticipantsAdmins)
                _admins = len(admins)
                if _admins > 0:
                    txt += f"\n\n**Admins ({_admins}):**"
                    for admin in admins: txt += f"\n{util.bluscream.UserStr(admin, True)}"
                notify = False
        await self.bot.client.send_message(self.bot.user, txt.strip(),
                                           schedule=timedelta(seconds=10) if notify else None)

    @command.desc("Toggle selflog")
    async def cmd_selflog(self, msg):
        self.disabled = not self.disabled
        status = "enabled" if not self.disabled else "disabled"
        return f"Selflog is now **{status}**."
