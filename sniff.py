import os
import re
import asyncio
from pathlib import Path
from typing import List, Optional

import telethon as tg
from telethon.tl import types

from .. import command, module


class SniffModule(module.Module):
    name = "Sniff"
    disabled = False

    async def on_load(self) -> None:
        """Initialize module state and create download directory."""
        self.regexes = []
        self.target_chat = None
        
        # Create downloads/listen directory
        self.download_dir = Path("downloads/listen")
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # Load saved data
        await self._load_data()
        
        # Register message handler
        self.bot.add_handler("message", self.on_message)

    async def on_unload(self) -> None:
        """Clean up handlers."""
        try:
            self.bot.remove_handler("message", self.on_message)
        except:
            pass

    async def _load_data(self) -> None:
        """Load regexes and target chat from storage."""
        try:
            self.regexes = self.bot.get("sniff_regexes", [])
            self.target_chat = self.bot.get("sniff_target_chat")
        except Exception:
            self.regexes = []
            self.target_chat = None

    async def _save_data(self) -> None:
        """Save regexes and target chat to storage."""
        try:
            self.bot.set("sniff_regexes", self.regexes)
            self.bot.set("sniff_target_chat", self.target_chat)
        except Exception as e:
            print(f"Error saving sniff data: {e}")

    async def _has_media(self, message) -> bool:
        """Check if message has media attachments."""
        if not message.media:
            return False
        
        # Check for various media types
        media_types = (
            types.MessageMediaPhoto,
            types.MessageMediaVideo,
            types.MessageMediaDocument
        )
        
        return isinstance(message.media, media_types)

    async def _download_media(self, message) -> List[str]:
        """Download media from message and return file paths."""
        downloaded_files = []
        
        if not message.media:
            return downloaded_files
        
        try:
            # Generate filename based on message info
            timestamp = message.date.strftime("%Y%m%d_%H%M%S")
            chat_id = message.chat_id
            msg_id = message.id
            
            # Download the media
            file_path = await self.bot.client.download_media(
                message.media,
                file=str(self.download_dir / f"{chat_id}_{msg_id}_{timestamp}")
            )
            
            if file_path:
                downloaded_files.append(file_path)
                
        except Exception as e:
            print(f"Error downloading media: {e}")
        
        return downloaded_files

    async def _get_message_link(self, message) -> str:
        """Generate a link to the message."""
        try:
            # Try to get public link if chat is public
            if hasattr(message.chat, 'username') and message.chat.username:
                return f"https://t.me/{message.chat.username}/{message.id}"
            else:
                # For private chats, return chat ID and message ID
                return f"https://t.me/{message.chat_id}/{message.id}"
        except Exception:
            return f"Chat {message.chat_id}, Message {message.id}"

    async def _check_regexes(self, message) -> Optional[str]:
        """Check if message text matches any regex patterns."""
        if not message.message:
            return None
        
        text = message.message
        
        for regex_pattern in self.regexes:
            try:
                if re.search(regex_pattern, text, re.IGNORECASE):
                    return regex_pattern
            except re.error as e:
                print(f"Invalid regex pattern '{regex_pattern}': {e}")
                # Remove invalid regex
                self.regexes.remove(regex_pattern)
                await self._save_data()
        
        return None

    async def on_message(self, message) -> None:
        """Handle incoming messages and check for regex matches."""
        # Skip if no target chat set or no regexes configured
        if not self.target_chat or not self.regexes:
            return
        
        # Skip messages from target chat
        if str(message.chat_id) == str(self.target_chat):
            return
        
        # Skip own messages
        if message.out:
            return
        
        # Check for regex match
        matched_regex = await self._check_regexes(message)
        if not matched_regex:
            return
        
        # Check for media
        if not await self._has_media(message):
            return
        
        # Download media
        downloaded_files = await self._download_media(message)
        
        # Get message link
        message_link = await self._get_message_link(message)
        
        # Send notification to target chat
        notification = f"🔍 A regex has been mentioned at {message_link}\n"
        notification += f"📎 Media downloaded: {len(downloaded_files)} file(s)"
        
        if downloaded_files:
            notification += f"\n📁 Files saved to: {self.download_dir}"
        
        try:
            await self.bot.client.send_message(
                self.target_chat,
                notification,
                link_preview=False
            )
        except Exception as e:
            print(f"Error sending notification: {e}")

    @command.desc("Manage regex listening patterns")
    @command.usage("add <regex> | del <index> | list | settarget <chat_id>")
    async def cmd_listen(self, msg: tg.events.newmessage, action: str, *args: str) -> str:
        """Manage regex patterns and target chat for message sniffing."""
        
        if action == "add":
            if not args:
                return "❌ Please provide a regex pattern to add."
            
            regex_pattern = " ".join(args)
            
            # Test if regex is valid
            try:
                re.compile(regex_pattern)
            except re.error as e:
                return f"❌ Invalid regex pattern: {e}"
            
            self.regexes.append(regex_pattern)
            await self._save_data()
            
            return f"✅ Added regex pattern: `{regex_pattern}`\nTotal patterns: {len(self.regexes)}"
        
        elif action == "del":
            if not args:
                return "❌ Please provide the index of the regex to delete."
            
            try:
                index = int(args[0]) - 1  # Convert to 0-based index
                if 0 <= index < len(self.regexes):
                    removed = self.regexes.pop(index)
                    await self._save_data()
                    return f"✅ Removed regex pattern: `{removed}`\nTotal patterns: {len(self.regexes)}"
                else:
                    return f"❌ Invalid index. Use `!listen list` to see all patterns."
            except ValueError:
                return "❌ Please provide a valid number as the index."
        
        elif action == "list":
            if not self.regexes:
                return "📝 No regex patterns configured."
            
            result = "📝 Configured regex patterns:\n"
            for i, pattern in enumerate(self.regexes, 1):
                result += f"  {i}. `{pattern}`\n"
            
            result += f"\n🎯 Target chat: {self.target_chat or 'Not set'}"
            return result
        
        elif action == "settarget":
            if not args:
                return "❌ Please provide a chat ID or username."
            
            target = args[0]
            
            # Try to resolve the chat
            try:
                # Check if it's a username
                if target.startswith("@"):
                    entity = await self.bot.client.get_entity(target)
                    self.target_chat = entity.id
                else:
                    # Try to parse as chat ID
                    self.target_chat = int(target)
                
                await self._save_data()
                return f"✅ Target chat set to: `{self.target_chat}`"
            except (ValueError, Exception) as e:
                return f"❌ Invalid chat ID or username: {e}"
        
        else:
            return """❌ Unknown action. Available actions:
  • `add <regex>` - Add a regex pattern
  • `del <index>` - Remove a regex pattern by index
  • `list` - List all regex patterns and target chat
  • `settarget <chat_id>` - Set target chat for notifications"""
