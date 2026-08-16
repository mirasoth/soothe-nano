"""Back-compat shim: re-exports the unified ``soothe_nano.llm`` module.

The canonical LLM layer is :mod:`soothe_nano.llm` (litellm-backed). This
package exists only so the old import path
``from soothe_nano.utils.llm import ...`` keeps working during the migration.
New code must import from ``soothe_nano.llm`` directly.
"""

from __future__ import annotations

from soothe_nano.llm import *  # noqa: F401,F403
from soothe_nano.llm import __all__ as _llm_all  # noqa: F401

# Back-compat aliases for the removed wrapper types.
from soothe_nano.llm.provider import ChatLitellmModel

OpenAICompatModelWrapper = ChatLitellmModel
JsonSchemaModelWrapper = ChatLitellmModel

__all__ = list(_llm_all) + ["OpenAICompatModelWrapper", "JsonSchemaModelWrapper"]
