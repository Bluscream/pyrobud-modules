from typing import TYPE_CHECKING, List
import telethon as tg

from pyrobud import command, module, util
from .util.bluscream import get_id
from .classes.ChatBot import ChatBot
from .classes.ChatBots import ChatIncognitoBot, BetaIncognitoBot, ChattismoBot, RandomChatssBot, AnonimeChatBot

if TYPE_CHECKING:
    from pyrobud.core.bot import Bot


class ChatBots(module.Module):
    name = "ChatBots"
    disabled = False
    
    def __init__(self, bot: "Bot"):
        super().__init__(bot)
        self.bot: "Bot" = bot
        self.db: util.db.AsyncDB = None  # Will be initialized in on_load
        self.bots: List[ChatBot] = []  # Instance-level to avoid sharing between instances

    async def on_load(self) -> None:
        """Initialize database and load all chatbot instances."""
        self.db = self.bot.get_db(self.name)
        
        # Initialize all chatbot instances
        self.bots = [
            ChatIncognitoBot.Bot(self),
            BetaIncognitoBot.Bot(self),
            ChattismoBot.Bot(self),
            RandomChatssBot.Bot(self),
            AnonimeChatBot.Bot(self)
        ]
        
        print(f"Loaded {len(self.bots)} chatbots: {', '.join([b.name for b in self.bots])}")
        for bot in self.bots:
            print(f"  - {bot}")

    async def on_message(self, event: tg.events.NewMessage.Event) -> None:
        """Route messages to the appropriate chatbot handler."""
        if self.disabled:
            return
        
        if not event.message or not event.message.text:
            return
        
        chat_id = get_id(event.message.peer_id)
        to_id = get_id(event.message.to_id)
        
        # Find the bot this message belongs to
        for bot in self.bots:
            if chat_id != bot.id:
                continue
            
            # Route message to appropriate handler
            try:
                if to_id == bot.id:
                    await bot.on_message_to_bot(event.message)
                else:
                    await bot.on_message_from_bot(event.message)
            except Exception as ex:
                print(f"[{bot.name}] Error handling message: {ex}")
            
            break  # Only process for one bot

    async def on_message_edit(self, event: tg.events.MessageEdited.Event):
        """Route edited messages to the appropriate chatbot handler."""
        if self.disabled:
            return
        
        if not event.message:
            return
        
        chat_id = get_id(event.message.peer_id)
        from_id = get_id(event.message.from_id) or event.message.sender_id
        
        for bot in self.bots:
            if chat_id != bot.id:
                continue
            
            try:
                if from_id == self.bot.uid:
                    await bot.on_self_message_edited(event.message)
                else:
                    await bot.on_message_edited(event.message)
            except Exception as ex:
                print(f"[{bot.name}] Error handling edited message: {ex}")
            
            break  # Only process for one bot

    @command.desc("List all active chatbot sessions")
    @command.alias("chatbotsessions", "csessions")
    async def cmd_cs(self, ctx: command.Context) -> str:
        """Display all active sessions across all chatbots."""
        lines = ["**ChatBot Sessions:**\n"]
        total_sessions = 0
        
        for bot in self.bots:
            if not bot.sessions:
                continue
            
            lines.append(f"\n**{bot.name}** ({len(bot.sessions)} sessions):")
            for session in bot.sessions:
                total_sessions += 1
                lines.append(f"```")
                lines.append(str(session))
                lines.append(f"```")
        
        if total_sessions == 0:
            return "No active sessions"
        
        return f"Total: **{total_sessions}** sessions\n\n" + "\n".join(lines)