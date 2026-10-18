"""Duck-typed daemon/CLI config protocols for host-side consumers."""

from typing import Protocol


class WebSocketConfigProtocol(Protocol):
    """Protocol for WebSocket transport configuration."""

    host: str
    port: int


class DaemonTransportConfigProtocol(Protocol):
    """Protocol for daemon transport configuration."""

    websocket: WebSocketConfigProtocol


class DaemonConfigProtocol(Protocol):
    """Protocol for daemon configuration."""

    transports: DaemonTransportConfigProtocol


class CliConfigProtocol(Protocol):
    """Protocol for CLI configuration (minimal interface).

    This allows CLI to load just the websocket settings without
    requiring the full SootheConfig from the daemon package.
    """

    daemon: DaemonConfigProtocol


__all__ = [
    "CliConfigProtocol",
    "DaemonConfigProtocol",
    "DaemonTransportConfigProtocol",
    "WebSocketConfigProtocol",
]
