"""Telegram Channel Implementation

Provides Telegram integration for the Agent Framework.
Inspired by openclaw's Telegram channel.
[PHASE5] 通道集成 - TelegramChannel
"""

import asyncio
from typing import Optional, Callable
import logging

from .base import (
    Channel,
    ChannelConfig,
    ChannelMessage,
    ChannelType,
    MessageDirection,
    ChannelCapabilities,
    MessageTranslator,
)


logger = logging.getLogger(__name__)

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE5] [TelegramChannel] {msg}")


class TelegramChannel(Channel):
    """Telegram channel implementation

    Supports both polling and webhook modes for receiving messages.
    """

    def __init__(self, config: ChannelConfig):
        super().__init__(config)

        self.bot_token = config.bot_token
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"

        self._update_offset = 0
        self._poll_task: Optional[asyncio.Task] = None
        self._webhook_secret: str = ""

        # Set capabilities
        self.capabilities = ChannelCapabilities(
            supports_media=True,
            supports_typing=True,
            supports_read_receipts=False,
            supports_reactions=True,
            supports_threads=False,
            supports_reply=True,
            supports_edit=False,
            supports_delete=True,
            supports_webhook=True,
            supports_polling=True,
            max_message_length=4096,
            max_caption_length=1024,
        )

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.TELEGRAM

    async def connect(self) -> bool:
        """Connect to Telegram Bot API

        Returns:
            True if connection successful
        """
        try:
            # Verify bot token by getting bot info
            import aiohttp

            async with aiohttp.ClientSession() as session:
                url = f"{self.api_url}/getMe"
                async with session.post(url) as response:
                    if response.status != 200:
                        logger.error(f"Telegram API error: {response.status}")
                        return False

                    data = await response.json()
                    if not data.get("ok"):
                        logger.error(f"Telegram getMe failed: {data}")
                        return False

                    bot_info = data.get("result", {})
                    logger.info(f"Connected to Telegram as @{bot_info.get('username')}")

            return True

        except Exception as e:
            logger.error(f"Failed to connect to Telegram: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from Telegram"""
        if self._poll_task:
            self._poll_task.cancel()
            self._poll_task = None

    async def send_message(self, message: ChannelMessage) -> str:
        """Send a message through Telegram

        Args:
            message: ChannelMessage to send

        Returns:
            Telegram message ID
        """
        import aiohttp

        url = f"{self.api_url}/sendMessage"

        payload = {
            "chat_id": message.chat_id,
            "text": message.content,
        }

        if message.reply_to_id:
            payload["reply_to_message_id"] = message.reply_to_id

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    data = await response.json()

                    if data.get("ok"):
                        return str(data["result"]["message_id"])
                    else:
                        raise Exception(f"Telegram API error: {data}")

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            raise

    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit a message (Telegram supports editing within 48 hours)

        Args:
            message_id: Telegram message ID
            new_content: New message content

        Returns:
            True if edit successful
        """
        import aiohttp

        url = f"{self.api_url}/editMessageText"

        payload = {
            "chat_id": 0,  # Would need to track chat_id
            "message_id": int(message_id),
            "text": new_content,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    data = await response.json()
                    return data.get("ok", False)

        except Exception as e:
            logger.error(f"Failed to edit Telegram message: {e}")
            return False

    async def delete_message(self, message_id: str) -> bool:
        """Delete a message

        Args:
            message_id: Telegram message ID

        Returns:
            True if deletion successful
        """
        import aiohttp

        url = f"{self.api_url}/deleteMessage"

        payload = {
            "chat_id": 0,  # Would need to track chat_id
            "message_id": int(message_id),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    data = await response.json()
                    return data.get("ok", False)

        except Exception as e:
            logger.error(f"Failed to delete Telegram message: {e}")
            return False

    async def send_typing(self, is_typing: bool) -> None:
        """Send typing status

        Args:
            is_typing: True if typing, False to stop
        """
        import aiohttp

        url = f"{self.api_url}/sendChatAction"

        payload = {
            "chat_id": 0,  # Would need to track chat_id
            "action": "typing" if is_typing else "cancel",
        }

        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json=payload)
        except Exception as e:
            logger.error(f"Failed to send Telegram typing status: {e}")

    async def set_webhook(self, url: str, secret: str = "") -> bool:
        """Set webhook URL for incoming updates

        Args:
            url: Webhook URL
            secret: Optional secret for verification

        Returns:
            True if webhook set successfully
        """
        import aiohttp

        self._webhook_secret = secret
        url = f"{self.api_url}/setWebhook"

        payload = {"url": url}
        if secret:
            payload["secret_token"] = secret

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    data = await response.json()
                    return data.get("ok", False)

        except Exception as e:
            logger.error(f"Failed to set Telegram webhook: {e}")
            return False

    async def start_polling(self) -> None:
        """Start polling for updates (alternative to webhook)"""
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        """Poll Telegram for updates"""
        import aiohttp

        url = f"{self.api_url}/getUpdates"

        while self._running:
            try:
                payload = {
                    "offset": self._update_offset,
                    "timeout": 30,
                }

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=35) as response:
                        if response.status != 200:
                            await asyncio.sleep(5)
                            continue

                        data = await response.json()

                        if not data.get("ok"):
                            await asyncio.sleep(5)
                            continue

                        for update in data.get("result", []):
                            await self._handle_update(update)
                            self._update_offset = update["update_id"] + 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
                await asyncio.sleep(5)

    async def _handle_update(self, update: dict) -> None:
        """Handle an incoming Telegram update

        Args:
            update: Telegram update object
        """
        if "message" not in update:
            return

        message = update["message"]
        channel_message = ChannelMessage(
            id=str(message["message_id"]),
            channel_type=ChannelType.TELEGRAM,
            direction=MessageDirection.INCOMING,
            content=message.get("text", ""),
            sender_id=str(message["from"]["id"]),
            sender_name=f"{message['from'].get('first_name', '')} {message['from'].get('last_name', '')}".strip(),
            chat_id=str(message["chat"]["id"]),
            timestamp=message["date"],
            reply_to_id=str(message.get("reply_to_message", {}).get("message_id", "")),
            metadata={
                "update_id": update["update_id"],
                "chat_type": message["chat"].get("type", "private"),
            },
        )

        self._emit_message(channel_message)

    async def handle_webhook(self, request_data: dict) -> None:
        """Handle an incoming webhook request

        Args:
            request_data: Webhook payload from Telegram
        """
        await self._handle_update(request_data)

    # Note: This is a simplified implementation
    # A full implementation would need proper webhook handling,
    # error recovery, batch processing, etc.
