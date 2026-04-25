"""Discord Channel Implementation

Provides Discord integration for the Agent Framework.
Inspired by openclaw's Discord channel.
[PHASE5] 通道集成 - DiscordChannel
"""

import asyncio
import hmac
import hashlib
import time
import logging
from typing import Optional
from dataclasses import dataclass

from .base import (
    Channel,
    ChannelConfig,
    ChannelMessage,
    ChannelType,
    MessageDirection,
    ChannelCapabilities,
)


logger = logging.getLogger(__name__)

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE5] [DiscordChannel] {msg}")


class DiscordChannel(Channel):
    """Discord channel implementation

    Uses Discord's WebSocket API for receiving messages
    and REST API for sending.
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)

        self.bot_token = config.bot_token
        self.api_url = "https://discord.com/api/v10"
        self.ws_url = "wss://gateway.discord.gg"

        self._session_id: Optional[str] = None
        self._heartbeat_interval: int = 0
        self._sequence: int = 0
        self._ws: Optional[asyncio.WebSocketServerProtocol] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Set capabilities
        self.capabilities = ChannelCapabilities(
            supports_media=True,
            supports_typing=True,
            supports_read_receipts=False,
            supports_reactions=True,
            supports_threads=True,
            supports_reply=True,
            supports_edit=True,
            supports_delete=True,
            supports_webhook=True,
            supports_polling=False,
            max_message_length=2000,
            max_caption_length=2000,
        )

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.DISCORD

    async def connect(self) -> bool:
        """Connect to Discord Gateway

        Returns:
            True if connection successful
        """
        try:
            import aiohttp

            # Verify bot token by getting bot info
            headers = {"Authorization": f"Bot {self.bot_token}"}

            async with aiohttp.ClientSession() as session:
                url = f"{self.api_url}/users/@me"
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Discord API error: {response.status}")
                        return False

                    bot_info = await response.json()
                    logger.info(f"Connected to Discord as {bot_info.get('username')}")

            # Start gateway connection
            await self._start_gateway()

            return True

        except Exception as e:
            logger.error(f"Failed to connect to Discord: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from Discord"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

    async def _start_gateway(self) -> None:
        """Start Discord Gateway connection"""
        import aiohttp

        # Get gateway URL with intents
        headers = {"Authorization": f"Bot {self.bot_token}"}
        url = f"{self.api_url}/gateway/bot"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    raise Exception(f"Failed to get gateway: {response.status}")

                data = await response.json()
                gateway_url = data.get("url", self.ws_url)

        # Connect to gateway
        ws_url = f"{gateway_url}?v=10&encoding=json"

        async with session.ws_connect(ws_url) as ws:
            self._ws = ws
            await self._gateway_loop()

    async def _gateway_loop(self) -> None:
        """Main gateway event loop"""
        while True:
            msg = await self._ws.receive()

            if msg.type == aiohttp.WSMsgType.CLOSED:
                logger.warning("Discord gateway closed")
                break

            if msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"Discord gateway error: {msg.data}")
                break

            if msg.type == aiohttp.WSMsgType.TEXT:
                data = msg.json()
                await self._handle_gateway_message(data)

    async def _handle_gateway_message(self, data: dict) -> None:
        """Handle a gateway message

        Args:
            data: Gateway message payload
        """
        op = data.get("op")

        if op == 10:  # Hello
            # Send identify
            self._heartbeat_interval = data.get("d", {}).get("heartbeat_interval", 45000)
            await self._send_identify()

        elif op == 0:  # Dispatch
            event = data.get("t")
            self._sequence = data.get("s", self._sequence)

            if event == "MESSAGE_CREATE":
                await self._handle_message_create(data["d"])

        elif op == 11:  # Heartbeat ACK
            pass  # Heartbeat acknowledged

    async def _send_identify(self) -> None:
        """Send IDENTIFY payload to gateway"""
        payload = {
            "op": 2,
            "d": {
                "token": self.bot_token,
                "intents": 1 << 0 | 1 << 9,  # Guilds + GuildMessages
                "properties": {
                    "os": "linux",
                    "browser": "agent_framework",
                    "device": "agent_framework",
                },
            },
        }
        await self._ws.send_json(payload)

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self) -> None:
        """Send heartbeats to gateway"""
        while True:
            await asyncio.sleep(self._heartbeat_interval / 1000)
            payload = {"op": 1, "d": self._sequence}
            await self._ws.send_json(payload)

    async def _handle_message_create(self, data: dict) -> None:
        """Handle a message create event

        Args:
            data: Message data
        """
        # Ignore bots
        if data.get("author", {}).get("bot", False):
            return

        # Ignore system messages
        if data.get("type", 0) != 0:
            return

        channel_message = ChannelMessage(
            id=str(data["id"]),
            channel_type=ChannelType.DISCORD,
            direction=MessageDirection.INCOMING,
            content=data.get("content", ""),
            sender_id=str(data["author"]["id"]),
            sender_name=data["author"].get("username", ""),
            chat_id=str(data["channel_id"]),
            room_id=str(data.get("guild_id", "")),
            timestamp=time.time(),
            reply_to_id=str(data.get("referenced_message", {}).get("id", "")),
            metadata={
                "guild_id": data.get("guild_id"),
                "channel_id": data["channel_id"],
                "member": data.get("member"),
            },
        )

        self._emit_message(channel_message)

    async def send_message(self, message: ChannelMessage) -> str:
        """Send a message through Discord

        Args:
            message: ChannelMessage to send

        Returns:
            Discord message ID
        """
        import aiohttp

        url = f"{self.api_url}/channels/{message.chat_id}/messages"

        payload = {"content": message.content}

        if message.reply_to_id:
            payload["message_reference"] = {"message_id": message.reply_to_id}

        headers = {"Authorization": f"Bot {self.bot_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    if response.status not in (200, 201):
                        text = await response.text()
                        raise Exception(f"Discord API error {response.status}: {text}")

                    data = await response.json()
                    return str(data["id"])

        except Exception as e:
            logger.error(f"Failed to send Discord message: {e}")
            raise

    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit a Discord message

        Args:
            message_id: Discord message ID
            new_content: New message content

        Returns:
            True if edit successful
        """
        import aiohttp

        url = f"{self.api_url}/channels/{self._last_channel_id}/messages/{message_id}"

        payload = {"content": new_content}
        headers = {"Authorization": f"Bot {self.bot_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, json=payload, headers=headers) as response:
                    return response.status == 200

        except Exception as e:
            logger.error(f"Failed to edit Discord message: {e}")
            return False

    async def delete_message(self, message_id: str) -> bool:
        """Delete a Discord message

        Args:
            message_id: Discord message ID

        Returns:
            True if deletion successful
        """
        import aiohttp

        url = f"{self.api_url}/channels/{self._last_channel_id}/messages/{message_id}"

        headers = {"Authorization": f"Bot {self.bot_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as response:
                    return response.status == 204

        except Exception as e:
            logger.error(f"Failed to delete Discord message: {e}")
            return False

    async def send_typing(self, is_typing: bool) -> None:
        """Send typing indicator

        Args:
            is_typing: True if typing (actually triggers typing in Discord)
        """
        import aiohttp

        if not is_typing:
            return  # Discord doesn't support stopping typing

        url = f"{self.api_url}/channels/{self._last_channel_id}/typing"

        headers = {"Authorization": f"Bot {self.bot_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, headers=headers)
        except Exception as e:
            logger.error(f"Failed to send Discord typing: {e}")

    async def set_webhook(self, url: str, secret: str = "") -> bool:
        """Discord uses interaction webhooks, not like Telegram

        Args:
            url: Webhook URL (not used directly)
            secret: Not used

        Returns:
            True (Discord uses different mechanism)
        """
        # Discord's webhook verification is different
        # This would be handled by the interaction endpoint
        return True

    # Note: This is a simplified implementation
    # A full implementation would need:
    # - Proper interaction endpoint for slash commands
    # - Reaction handling
    # - Thread management
    # - Rich embeds support
