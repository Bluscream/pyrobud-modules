import asyncio, json, re
from datetime import datetime, timedelta
from enum import Enum, auto
from random import choice, randint, randrange
from typing import TYPE_CHECKING, List, Any, Optional
from urllib import parse
import telethon as tg

if TYPE_CHECKING:
    from pyrobud.module import Module
    from pyrobud.core.bot import Bot
    from pyrobud import util
    

# region enums
class Command(Enum):
    NEXT_CHAT = auto()
    LEAVE_CHAT = auto() 
    NEW_CHAT = auto()
    REVOKE_MESSAGE = auto()
    STOP_SEARCHING = auto()
    SETTINGS = auto()
    LANGUAGE = auto()
    HELP = auto()
class Regex(Enum):
    SESSION_SEARCHING = auto()
    SESSION_START = auto()
    SESSION_END = auto()
    SESSION_URL = auto()
    PARTNER_AGE = auto()
    PARTNER_DISTANCE = auto()
    PARTNER_GENDER = auto()
    MESSAGE_PARTNER = auto()
    MESSAGE_AUTHOR = auto()
    MESSAGE_GENDER = auto()
class Gender(Enum):
    Unknown = auto()
    Unspecified = auto()
    Male = auto()
    Female = auto()
    Nonbinary = auto()
class SessionState(Enum):
    Unknown = auto()
    Searching = auto()
    Active = auto()
    Ended = auto()
class SessionCloser(Enum):
    You = auto()
    Partner = auto()
# endregion enums

# region subclasses
class Partner(object):
    def __init__(self):
        self.gender: Optional[Gender] = None
        self.age: Optional[int] = None
        self.location: Optional[tg.tl.custom.inlineresult.InlineResult.LOCATION] = None
        self.vip: Optional[bool] = None
        self._distance_km: Optional[int] = None
    
    @property
    def distance_km(self) -> Optional[int]:
        return self._distance_km
    
    @distance_km.setter
    def distance_km(self, value: Optional[int]):
        self._distance_km = value
    
    def __str__(self) -> str:
        parts = []
        if self.gender is not None:
            parts.append(f"Gender: {self.gender.name}")
        if self.age is not None:
            parts.append(f"Age: {self.age}")
        if self.distance_km is not None:
            parts.append(f"Distance: {self.distance_km}km")
        if self.vip is not None:
            parts.append(f"VIP: {self.vip}")
        return "\n".join(parts) if parts else "Unknown Partner"

    # def setGender(self, gender: str):
    #     if not self.partner: self.partner = Partner()
    #     if self.partner.gender: return
    #     if gender == Emojis.Gender.Unknown:
    #         self.partner_gender = Gender.Unspecified
    #     elif gender == Emojis.Gender.Female:
    #         self.partner_gender = Gender.Female
    #     elif gender == Emojis.Gender.Male:
    #         self.partner_gender = Gender.Male
    #     # else: self.partner_gender = Gender.Unknown

class Session(object):
    def __init__(self, chatbot: "ChatBot"):
        self.bot: "ChatBot" = chatbot
        self.state: SessionState = SessionState.Unknown
        self.partner: Partner = Partner()
        self.starttime: datetime = datetime.now()
        self.endtime: Optional[datetime] = None
        self.reopen_url: Optional[parse.ParseResult] = None
        self.messages: List[int] = []
        self.closer: Optional[SessionCloser] = None
        self.greeted: str = ""

    @property
    def duration(self) -> Optional[timedelta]:
        if self.endtime and self.starttime:
            return self.endtime - self.starttime
        return None

    def __str__(self) -> str:
        pp = "State: " + str(self.state)
        if self.partner is not None: 
            pp += "\nPartner: " + str(self.partner)
        if self.starttime is not None: 
            pp += "\nStarttime: " + str(self.starttime)
        if self.endtime is not None: 
            pp += "\nEndtime: " + str(self.endtime)
        if self.duration is not None:
            pp += "\nDuration: " + str(self.duration)
        if self.reopen_url is not None: 
            pp += "\nURL: " + str(self.reopen_url)
        pp += "\n" + str(len(self.messages)) + " Messages: " + str(self.messages)
        if self.closer is not None: 
            pp += "\nCloser: " + str(self.closer)
        if self.greeted: 
            pp += "\nGreeted with: " + str(self.greeted)
        return pp

    def close(self):
        """Close the session and set the end time."""
        self.endtime = datetime.now()
        self.state = SessionState.Ended


class Settings(object):
    def __init__(self):
        self.language: Optional[str] = None
        self.use_keyboards: bool = True
        self.own_gender: Optional[Gender] = None
        self.partner_gender: Optional[Gender] = None
        self.location: Optional[tg.tl.custom.inlineresult.InlineResult.LOCATION] = None
        self.birthdate: Optional[datetime] = None
        self.partner_age_min: Optional[int] = None
        self.partner_age_max: Optional[int] = None
        self.reopen_requests_enabled: bool = False
# endregion subclasses

class ChatBot(object):
    # Class-level defaults (will be overridden per subclass)
    name: str = "ChatBot"
    id: int = 0
    prefix: str = "/"
    commands: dict[Command, str] = {}
    regexes: dict[Regex, re.Pattern] = {}
    genders: dict[Gender, str] = {}
    
    def __init__(self, mod: "Module"):
        self.module: "Module" = mod
        # Instance-level attributes to avoid sharing between instances
        self.sessions: List[Session] = []
        self.log_channels: dict[int, str] = {-1001344802682: "ChatIncognitoBotLog"}
        self.settings: dict[str, Any] = {
            "enabled": True,
            "greet": True,
            "greeting": "{r;Hallo|Hi|Hey|Was geht|Yo|Jo} {r;;:3|:D|<3|♥|👌|✌|c:|?}",
            "check_for_media": False,
            "add_info": False
        }
        # Greeting components (can be overridden in subclasses)
        self.greeting_prefixes: List[str] = ["Hallo", "Hi", "Hey", "Yo"]
        self.greeting_suffixes: List[str] = [":3", ":D", "<3", "♥", "👌", "✌"]

# region methods

    def __str__(self):
        return f"`{self.name}` (`{self.id}`)\nPrefix: `{self.prefix}`\nCommands: `{len(self.commands)}`\nPatterns: `{len(self.regexes)}`\nSessions: `{len(self.sessions)}`" # Greeting Combinations: `{len(self.greeting_prefixes)*len(self.greeting_suffixes)}
    
    def print(self, *args, **kwargs):
        print(f"[{self.name}]", *args, **kwargs)

    def getCurrentSession(self) -> Session:
        if len(self.sessions) < 1: self.sessions.append(Session(self))
        return self.sessions[-1]

    def updateCurrentSession(self,
                      state: SessionState = None, closer: SessionCloser = None, 
                      gender: Gender = None, age: int = None, distance_km: int = None, vip: bool = None, greeted: str = None
        ):
        session = self.getCurrentSession()
        if state is not None:
            session.state = state
            match state:
                case SessionState.Active:
                    session.starttime = datetime.now()
                case SessionState.Ended:
                    session.endtime = datetime.now()
        if closer is not None: session.closer = closer
        if greeted is not None: session.greeted = greeted
        if not session.partner: session.partner = Partner()
        if gender is not None: session.partner.gender = gender
        if age is not None: session.partner.age = age
        if distance_km is not None: session.partner.distance_km = distance_km
        if vip is not None: session.partner.vip = vip
        self.print(f"Updated Session: {session}")

    async def greet(self):
        """Send a greeting message to the partner."""
        if not self.settings.get("greet", True):
            return
        
        session = self.getCurrentSession()
        if session.greeted or session.state != SessionState.Active or not self.id:
            return
        
        # Wait a random amount before greeting
        await asyncio.sleep(randrange(1, 3))
        
        # Build greeting
        prefix: str = choice(self.greeting_prefixes)
        if choice((True, False)):
            prefix = prefix.lower()
        greeting = f"{prefix} {choice(self.greeting_suffixes)}"
        
        # Add info if enabled
        if self.settings.get("add_info", False):
            greeting += "\n\n(Additional info not implemented)"
        
        await self.send_text(greeting)
        session.greeted = greeting

    def get_gender(self, txt: str):
        for gender, gender_txt in self.genders.items():
            if gender_txt == txt:
                return gender
        return Gender.Unknown
    
    def get_match_group(self, match: re.Match, name: str, _as: Optional[type] = None):
        """Extract a named group from a regex match and optionally convert to a type."""
        if not name or name not in match.groupdict():
            return None
        ret = match.group(name)
        if ret is None:
            return None
        if _as is None:
            return ret
        # Convert to the requested type
        try:
            if _as == bool:
                return bool(ret)
            elif _as == float:
                return float(ret)
            elif _as == int:
                return int(ret)
            elif _as == str:
                return str(ret)
            else:
                return ret
        except (ValueError, TypeError):
            return None

    async def send_text(self, text: str, delete_after_s: Optional[int] = None):
        """Send a text message to the bot."""
        self.print(f"send_text(\"{text}\", delete_after_s={delete_after_s})")
        msg = await self.module.bot.client.send_message(self.id, text)
        self.print(f"Message sent: {msg.id}")
        if delete_after_s is not None:
            await asyncio.sleep(delete_after_s)
            try:
                await msg.delete()
            except Exception as ex:
                self.print(f"Failed to delete message: {ex}")

    async def send_command(self, command: Command, delete_after_s: int = 5):
        """Send a command to the bot."""
        if command not in self.commands:
            self.print(f"Command {command} not found in commands dict")
            return
        cmd = self.prefix + self.commands[command]
        self.print(f"send_command(\"{cmd}\", delete_after_s={delete_after_s})")
        await self.send_text(cmd, delete_after_s)

    def match(self, pattern: Regex, text: str) -> Optional[re.Match]:
        """Try to match a regex pattern against text with various flag combinations."""
        if pattern not in self.regexes or not text:
            return None
        
        regex = self.regexes[pattern]
        
        # Try different flag combinations
        for flags in [
            re.MULTILINE | re.UNICODE | re.DOTALL,
            re.MULTILINE | re.UNICODE,
            re.MULTILINE,
            0  # No flags
        ]:
            match = regex.search(text) if flags == 0 else regex.search(text)
            if match:
                return match
        
        return None
# endregion methods

# region events
    async def on_message_from_bot(self, message: tg.tl.custom.message.Message) -> None:
        partner_match = self.match(Regex.MESSAGE_PARTNER, message.text)
        session_start_match = self.match(Regex.SESSION_START, message.text)
        session_end_match = self.match(Regex.SESSION_END, message.text)
        session_search_match = self.match(Regex.SESSION_SEARCHING, message.text)
        self.print(f"on_message_from_bot (partner: {partner_match}, started={session_start_match}, ended={session_end_match}, searching={session_search_match})\n\"{message.text}\"")
        if partner_match:
            gender = self.get_match_group(partner_match, 'sex')
            msg = self.get_match_group(partner_match, 'msg')
            self.print(f"Got message from {gender} partner: {msg}")
            self.updateCurrentSession(SessionState.Active, None, gender)
            return
        if session_end_match:
            self.updateCurrentSession(SessionState.Ended)
            await asyncio.sleep(randint(1,10))
            self.sessions.remove(self.getCurrentSession())
            await self.send_command(Command.NEW_CHAT)
            await self.module.db.inc("sessions_ended")
        if session_start_match:
            # Extract gender from match
            gender_str = self.get_match_group(session_start_match, 'sex')
            gender = self.get_gender(gender_str) if gender_str else None
            
            self.updateCurrentSession(
                SessionState.Active, None,
                gender,
                self.get_match_group(session_start_match, 'age', int),
                self.get_match_group(session_start_match, 'distance', int),
                self.get_match_group(session_start_match, 'vip', bool),
                greeted=None
            )
            await self.greet()
            await self.module.db.inc("sessions_started")
        elif session_search_match:
            self.updateCurrentSession(SessionState.Searching)
        elif self.match(Regex.MESSAGE_AUTHOR, message.text):
            self.print("Got author message, deleting: \"{message.text}\"")
            try:
                if message.is_reply: await self.module.bot.client.delete_messages(message.chat_id, message.reply_to_msg_id)
            except Exception as ex: self.print(ex)
            await message.delete()

    async def on_message_to_bot(self, message: tg.tl.custom.message.Message) -> None:
        """Handle messages sent to the bot (commands from the user)."""
        self.print(f"on_message_to_bot: \"{message.text}\"")
        
        if not message.text:
            return
            
        lower_txt = message.text.lower()
        
        if lower_txt == "/session":
            lines = []
            lines.append(f"**Bot:** `{self.name}` (`{self.id}`)")
            lines.append(f"**Media check:** `{self.settings.get('check_for_media', False)}`")
            lines.append(f"**Sessions:** `{len(self.sessions)}`")
            if self.sessions:
                current = self.getCurrentSession()
                lines.append(f"\n**Current Session:**")
                lines.append(f"State: `{current.state.name}`")
                if current.partner and current.partner.gender:
                    lines.append(f"Partner: `{current.partner.gender.name}`")
                if current.starttime:
                    lines.append(f"Started: `{current.starttime.strftime('%H:%M:%S')}`")
            await message.edit("\n".join(lines))
            
        elif lower_txt == "/media":
            current = self.settings.get("check_for_media", False)
            self.settings["check_for_media"] = not current
            new_state = self.settings["check_for_media"]
            response = f"You are {'no longer allowed to send media ❌' if new_state else 'allowed to send media now ✔'}"
            await message.reply(response)
            await asyncio.sleep(15)
            try:
                await message.delete()
            except:
                pass
                
        elif lower_txt.startswith("/setting "):
            args = lower_txt.replace("/setting ", "").split(" ")
            if args and args[0] in self.settings:
                self.settings[args[0]] = not self.settings[args[0]]
                state = "Enabled" if self.settings[args[0]] else "Disabled"
                await message.edit(f"{state} `{args[0]}` for `{self.name}` (`{self.id}`)")
            else:
                await message.edit(f"Unknown setting. Available: {', '.join(self.settings.keys())}")
                
        elif lower_txt == "/toggleinfo":
            current = self.settings.get("add_info", False)
            self.settings["add_info"] = not current
            state = "Enabled" if self.settings["add_info"] else "Disabled"
            await message.edit(f"{state} info for `{self.name}` (`{self.id}`)")
            
        elif lower_txt == "/stats":
            sessions_started = await self.module.db.get("sessions_started", 0)
            sessions_ended = await self.module.db.get("sessions_ended", 0)
            active_sessions = len([s for s in self.sessions if s.state == SessionState.Active])
            await message.edit(
                f"**{self.name}** (`{self.id}`):\n\n"
                f"Sessions started: `{sessions_started}`\n"
                f"Sessions ended: `{sessions_ended}`\n"
                f"Currently active: `{active_sessions}`"
            )

    async def on_message_edited(self, message: tg.tl.custom.message.Message):
        pass # self.print(f"on_message_edited")

    async def on_self_message_edited(self, message: tg.tl.custom.message.Message):
        self.print(f"on_self_message_edited")
        if Command.REVOKE_MESSAGE in self.commands and not message.text.startswith("/") and not message.text.startswith("."):
            await self.send_command(Command.REVOKE_MESSAGE, delete_after_s=5)
            await self.send_text(message.text)
            await message.delete()
# endregion events
