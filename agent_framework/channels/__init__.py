"""Channel System for Agent Framework

Provides multi-channel message integration (Telegram, Discord, Slack, etc.).
Inspired by openclaw's channel system.
"""

from .base import (
    Channel,
    ChannelConfig,
    ChannelMessage,
    ChannelType,
    MessageDirection,
)
from .registry import ChannelRegistry, get_channel_registry
from .telegram import TelegramChannel
from .discord import DiscordChannel

__all__ = [
    "Channel",
    "ChannelConfig",
    "ChannelMessage",
    "ChannelType",
    "MessageDirection",
    "ChannelRegistry",
    "get_channel_registry",
    "TelegramChannel",
    "DiscordChannel",
]
