"""Channel Base Classes

Defines the interface for channel implementations.
Inspired by openclaw's channel plugins.
[PHASE5] 通道集成 - ChannelBase
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, Callable
import time

# Debug print helper
def _debug(msg: str):
    print(f"[PHASE5] [ChannelBase] {msg}")


class ChannelType(Enum):
    """Supported channel types"""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    SIGNAL = "signal"
    EMAIL = "email"
    CLI = "cli"
    WEB = "web"
    API = "api"


class MessageDirection(Enum):
    """Message direction"""
    INCOMING = "incoming"  # User to agent
    OUTGOING = "outgoing"  # Agent to user


@dataclass
class ChannelConfig:
    """Configuration for a channel"""
    channel_type: ChannelType
    enabled: bool = True

    # Bot/Client configuration
    bot_token: str = ""
    api_key: str = ""
    api_secret: str = ""

    # Connection settings
    webhook_url: str = ""
    callback_url: str = ""

    # Rate limiting
    rate_limit: int = 60  # Messages per minute
    burst_limit: int = 10  # Max burst size

    # Custom settings per channel
    custom: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelConfig":
        """Create config from dictionary"""
        channel_type = ChannelType(data.get("type", "cli"))
        config = cls(channel_type=channel_type)

        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)

        return config

    def to_dict(self) -> dict:
        """Convert config to dictionary"""
        result = {
            "type": self.channel_type.value,
            "enabled": self.enabled,
        }

        # Add all non-default fields
        for key in ["bot_token", "api_key", "api_secret", "webhook_url",
                    "callback_url", "rate_limit", "burst_limit", "custom"]:
            if hasattr(self, key):
                value = getattr(self, key)
                if value:
                    result[key] = value

        return result


@dataclass
class ChannelMessage:
    """Represents a message in a channel"""
    id: str  # Platform-specific message ID
    channel_type: ChannelType
    direction: MessageDirection

    # Content
    content: str
    content_type: str = "text"  # text, image, audio, video, file

    # Sender/Recipient
    sender_id: str = ""
    sender_name: str = ""
    recipient_id: str = ""

    # Chat/Room info
    chat_id: str = ""
    room_id: str = ""

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    # Timestamps
    timestamp: float = field(default_factory=time.time)
    edited_at: float = None

    # Reply context
    reply_to_id: str = ""

    def to_dict(self) -> dict:
        """Convert message to dictionary"""
        return {
            "id": self.id,
            "channel_type": self.channel_type.value,
            "direction": self.direction.value,
            "content": self.content,
            "content_type": self.content_type,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "recipient_id": self.recipient_id,
            "chat_id": self.chat_id,
            "room_id": self.room_id,
            "metadata": self.metadata,
            "attachments": self.attachments,
            "timestamp": self.timestamp,
            "edited_at": self.edited_at,
            "reply_to_id": self.reply_to_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelMessage":
        """Create message from dictionary"""
        return cls(
            id=data["id"],
            channel_type=ChannelType(data.get("channel_type", "cli")),
            direction=MessageDirection(data.get("direction", "incoming")),
            content=data.get("content", ""),
            content_type=data.get("content_type", "text"),
            sender_id=data.get("sender_id", ""),
            sender_name=data.get("sender_name", ""),
            recipient_id=data.get("recipient_id", ""),
            chat_id=data.get("chat_id", ""),
            room_id=data.get("room_id", ""),
            metadata=data.get("metadata", {}),
            attachments=data.get("attachments", []),
            timestamp=data.get("timestamp", time.time()),
            edited_at=data.get("edited_at"),
            reply_to_id=data.get("reply_to_id", ""),
        )


@dataclass
class ChannelCapabilities:
    """Capabilities of a channel"""
    supports_media: bool = False
    supports_typing: bool = False
    supports_read_receipts: bool = False
    supports_reactions: bool = False
    supports_threads: bool = False
    supports_reply: bool = False
    supports_edit: bool = False
    supports_delete: bool = False
    supports_webhook: bool = False
    supports_polling: bool = False
    max_message_length: int = 4000
    max_caption_length: int = 1000


class Channel(ABC):
    """Abstract base class for channel implementations

    All channel implementations must inherit from this class
    and implement the required methods.
    """

    def __init__(self, config: ChannelConfig):
        self.config = config
        self.capabilities = ChannelCapabilities()
        self._running = False
        self._message_handler: Optional[Callable] = None
        self._status_handler: Optional[Callable] = None

    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        """Return the channel type"""
        pass

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the channel

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the channel"""
        pass

    @abstractmethod
    async def send_message(self, message: ChannelMessage) -> str:
        """Send a message through the channel

        Args:
            message: Message to send

        Returns:
            Platform-specific message ID of the sent message
        """
        pass

    @abstractmethod
    async def edit_message(self, message_id: str, new_content: str) -> bool:
        """Edit an existing message

        Args:
            message_id: ID of message to edit
            new_content: New message content

        Returns:
            True if edit successful
        """
        pass

    @abstractmethod
    async def delete_message(self, message_id: str) -> bool:
        """Delete a message

        Args:
            message_id: ID of message to delete

        Returns:
            True if deletion successful
        """
        pass

    @abstractmethod
    async def send_typing(self, is_typing: bool) -> None:
        """Send typing indicator

        Args:
            is_typing: True if user is typing, False if stopped
        """
        pass

    async def set_webhook(self, url: str) -> bool:
        """Set webhook URL for incoming messages

        Args:
            url: Webhook URL

        Returns:
            True if webhook set successfully
        """
        return False

    def on_message(self, handler: Callable[[ChannelMessage], None]) -> None:
        """Register a handler for incoming messages

        Args:
            handler: Callback function that receives ChannelMessage
        """
        self._message_handler = handler

    def on_status(self, handler: Callable[[str, str], None]) -> None:
        """Register a handler for status updates

        Args:
            handler: Callback function(status, message)
        """
        self._status_handler = handler

    def _emit_message(self, message: ChannelMessage) -> None:
        """Internal: Emit a received message to the handler"""
        if self._message_handler:
            try:
                self._message_handler(message)
            except Exception as e:
                print(f"Message handler error: {e}")

    def _emit_status(self, status: str, message: str = "") -> None:
        """Internal: Emit a status update"""
        if self._status_handler:
            try:
                self._status_handler(status, message)
            except Exception as e:
                print(f"Status handler error: {e}")

    @property
    def is_connected(self) -> bool:
        """Check if channel is connected"""
        return self._running

    async def start(self) -> bool:
        """Start the channel (connect + start listening)

        Returns:
            True if started successfully
        """
        if self._running:
            return True

        success = await self.connect()
        if success:
            self._running = True
            self._emit_status("connected", f"Connected to {self.channel_type.value}")
        else:
            self._emit_status("error", f"Failed to connect to {self.channel_type.value}")

        return success

    async def stop(self) -> None:
        """Stop the channel (stop listening + disconnect)"""
        if not self._running:
            return

        await self.disconnect()
        self._running = False
        self._emit_status("disconnected", f"Disconnected from {self.channel_type.value}")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} type={self.channel_type.value} connected={self._running}>"


class MessageTranslator:
    """Translates between channel-specific formats and ChannelMessage

    Provides a standard interface for converting between
    platform-specific message formats and the framework's
    canonical message format.
    """

    @staticmethod
    def to_standard(platform: str, platform_message: Any) -> ChannelMessage:
        """Convert a platform-specific message to ChannelMessage

        Args:
            platform: Platform name (e.g., "telegram", "discord")
            platform_message: Platform-specific message object

        Returns:
            ChannelMessage in standard format
        """
        translators = {
            "telegram": MessageTranslator._from_telegram,
            "discord": MessageTranslator._from_discord,
            "slack": MessageTranslator._from_slack,
        }

        translator = translators.get(platform.lower())
        if translator:
            return translator(platform_message)

        # Default: try to extract basic fields
        return ChannelMessage(
            id=str(getattr(platform_message, "message_id", getattr(platform_message, "id", "unknown"))),
            channel_type=ChannelType(platform.lower()),
            direction=MessageDirection.INCOMING,
            content=str(platform_message),
        )

    @staticmethod
    def from_standard(platform: str, message: ChannelMessage) -> Any:
        """Convert a ChannelMessage to platform-specific format

        Args:
            platform: Platform name
            message: ChannelMessage in standard format

        Returns:
            Platform-specific message object
        """
        # For now, just return the message content as a string
        # Subclasses can override for platform-specific formatting
        return message.content

    @staticmethod
    def _from_telegram(tg_message) -> ChannelMessage:
        """Convert Telegram message to ChannelMessage"""
        return ChannelMessage(
            id=str(tg_message.message_id),
            channel_type=ChannelType.TELEGRAM,
            direction=MessageDirection.INCOMING,
            content=tg_message.text or "",
            sender_id=str(tg_message.from_user.id if tg_message.from_user else ""),
            sender_name=tg_message.from_user.full_name if tg_message.from_user else "",
            chat_id=str(tg_message.chat.id),
            timestamp=tg_message.date.timestamp() if tg_message.date else time.time(),
        )

    @staticmethod
    def _from_discord(dc_message) -> ChannelMessage:
        """Convert Discord message to ChannelMessage"""
        return ChannelMessage(
            id=str(dc_message.id),
            channel_type=ChannelType.DISCORD,
            direction=MessageDirection.INCOMING,
            content=dc_message.content,
            sender_id=str(dc_message.author.id),
            sender_name=dc_message.author.name,
            chat_id=str(dc_message.channel.id),
            timestamp=dc_message.created_at.timestamp(),
        )

    @staticmethod
    def _from_slack(slack_message) -> ChannelMessage:
        """Convert Slack message to ChannelMessage"""
        return ChannelMessage(
            id=slack_message.get("ts", ""),
            channel_type=ChannelType.SLACK,
            direction=MessageDirection.INCOMING,
            content=slack_message.get("text", ""),
            sender_id=slack_message.get("user", ""),
            chat_id=slack_message.get("channel", ""),
            timestamp=float(slack_message.get("ts", time.time())),
        )
