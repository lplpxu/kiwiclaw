"""Channel Registry

Manages channel instances and provides channel lookup.
Inspired by openclaw's channel registry.
"""

from typing import Dict, List, Optional, Callable
from dataclasses import dataclass

from .base import Channel, ChannelConfig, ChannelType, ChannelMessage


@dataclass
class ChannelInfo:
    """Information about a registered channel"""
    name: str
    channel_type: ChannelType
    channel: Channel
    config: ChannelConfig
    enabled: bool = True


class ChannelRegistry:
    """Central registry for channel instances

    Manages channel lifecycle and provides channel lookup by name or type.
    """

    def __init__(self):
        self._channels: Dict[str, ChannelInfo] = {}
        self._channels_by_type: Dict[ChannelType, List[str]] = {}
        self._default_channel: Optional[str] = None
        self._message_router: Optional[Callable] = None

    def register(
        self,
        name: str,
        channel: Channel,
        config: ChannelConfig = None,
        set_default: bool = False
    ) -> bool:
        """Register a channel

        Args:
            name: Unique name for this channel instance
            channel: Channel implementation
            config: Channel configuration
            set_default: Whether this should be the default channel

        Returns:
            True if registration successful
        """
        if name in self._channels:
            return False

        config = config or ChannelConfig(channel_type=channel.channel_type)

        info = ChannelInfo(
            name=name,
            channel_type=channel.channel_type,
            channel=channel,
            config=config,
            enabled=True,
        )

        self._channels[name] = info

        # Index by type
        if channel.channel_type not in self._channels_by_type:
            self._channels_by_type[channel.channel_type] = []
        self._channels_by_type[channel.channel_type].append(name)

        # Set as default if requested or if first channel
        if set_default or len(self._channels) == 1:
            self._default_channel = name

        return True

    def unregister(self, name: str) -> bool:
        """Unregister a channel

        Args:
            name: Name of channel to unregister

        Returns:
            True if unregistration successful
        """
        if name not in self._channels:
            return False

        info = self._channels[name]

        # Remove from type index
        if info.channel_type in self._channels_by_type:
            if name in self._channels_by_type[info.channel_type]:
                self._channels_by_type[info.channel_type].remove(name)

        # Clear default if this was default
        if self._default_channel == name:
            self._default_channel = None

        del self._channels[name]
        return True

    def get(self, name: str) -> Optional[Channel]:
        """Get a channel by name

        Args:
            name: Channel name

        Returns:
            Channel instance or None
        """
        info = self._channels.get(name)
        return info.channel if info else None

    def get_info(self, name: str) -> Optional[ChannelInfo]:
        """Get channel info by name

        Args:
            name: Channel name

        Returns:
            ChannelInfo or None
        """
        return self._channels.get(name)

    def list_channels(self) -> List[ChannelInfo]:
        """List all registered channels

        Returns:
            List of ChannelInfo
        """
        return list(self._channels.values())

    def list_by_type(self, channel_type: ChannelType) -> List[Channel]:
        """List all channels of a specific type

        Args:
            channel_type: Type to filter by

        Returns:
            List of Channel instances
        """
        names = self._channels_by_type.get(channel_type, [])
        return [self._channels[n].channel for n in names if n in self._channels]

    def list_enabled(self) -> List[Channel]:
        """List all enabled channels

        Returns:
            List of enabled Channel instances
        """
        return [info.channel for info in self._channels.values() if info.enabled]

    def list_names(self) -> List[str]:
        """List all channel names

        Returns:
            List of channel names
        """
        return list(self._channels.keys())

    def get_default(self) -> Optional[Channel]:
        """Get the default channel

        Returns:
            Default Channel instance or None
        """
        if not self._default_channel:
            return None
        info = self._channels.get(self._default_channel)
        return info.channel if info else None

    def set_default(self, name: str) -> bool:
        """Set the default channel

        Args:
            name: Channel name

        Returns:
            True if successful
        """
        if name not in self._channels:
            return False
        self._default_channel = name
        return True

    def enable(self, name: str) -> bool:
        """Enable a channel

        Args:
            name: Channel name

        Returns:
            True if successful
        """
        info = self._channels.get(name)
        if not info:
            return False
        info.enabled = True
        return True

    def disable(self, name: str) -> bool:
        """Disable a channel

        Args:
            name: Channel name

        Returns:
            True if successful
        """
        info = self._channels.get(name)
        if not info:
            return False
        info.enabled = False
        return True

    def is_enabled(self, name: str) -> bool:
        """Check if a channel is enabled

        Args:
            name: Channel name

        Returns:
            True if enabled
        """
        info = self._channels.get(name)
        return info.enabled if info else False

    def route_message(self, message: ChannelMessage) -> None:
        """Route a message to the appropriate handler

        Args:
            message: ChannelMessage to route
        """
        if self._message_router:
            self._message_router(message)

    def set_message_router(self, router: Callable[[ChannelMessage], None]) -> None:
        """Set the message router callback

        Args:
            router: Callback that receives ChannelMessage
        """
        self._message_router = router

    async def start_all(self) -> Dict[str, bool]:
        """Start all enabled channels

        Returns:
            Dictionary mapping channel names to success/failure
        """
        results = {}
        for name, info in self._channels.items():
            if info.enabled:
                try:
                    results[name] = await info.channel.start()
                except Exception as e:
                    print(f"Failed to start channel {name}: {e}")
                    results[name] = False
            else:
                results[name] = True  # Skip disabled channels
        return results

    async def stop_all(self) -> None:
        """Stop all channels"""
        for info in self._channels.values():
            try:
                await info.channel.stop()
            except Exception as e:
                print(f"Error stopping channel {info.name}: {e}")


# Global registry instance
_global_registry: Optional[ChannelRegistry] = None


def get_channel_registry() -> ChannelRegistry:
    """Get the global channel registry instance"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ChannelRegistry()
    return _global_registry
