from pyrobud import command, module

import re, json, http.client
# import telethon as tg


class Bluscream(module.Module):
    name = "Bluscream"
    disabled = False

    # async def on_message(self, msg: tg.custom.Message):
    #     if msg.chat_id is not None and msg.chat_id == self.bot.uid:
    #         await msg.forward_to(-280032537)
