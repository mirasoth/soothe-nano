"""soothe-nano — batteries-included SootheNanoAgent."""

from __future__ import annotations

import importlib.metadata

from soothe_sdk.protocols.core_agent import CoreAgentCapabilities

from soothe_nano.agent import LazyCoreAgent, SootheNanoAgent
from soothe_nano.agent.core_agent import ephemeral_execute_stream_enabled
from soothe_nano.agent.dual_mode import DualModeCoreAgent, create_dual_mode_nano_agent
from soothe_nano.agent.factory import create_nano_agent
from soothe_nano.agent.interaction_mode import InteractionMode
from soothe_nano.agent.subagent_catalog import spec_subagent_name
from soothe_nano.config import SootheConfig

try:
    __version__ = importlib.metadata.version("soothe-nano")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "CoreAgentCapabilities",
    "DualModeCoreAgent",
    "InteractionMode",
    "LazyCoreAgent",
    "SootheConfig",
    "SootheNanoAgent",
    "create_dual_mode_nano_agent",
    "create_nano_agent",
    "ephemeral_execute_stream_enabled",
    "spec_subagent_name",
    "__version__",
]
