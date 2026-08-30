"""Back-compat shim re-exporting `soothe_nano.llm`. New code should import from `soothe_nano.llm` directly."""

from __future__ import annotations

from soothe_nano.llm import *  # noqa: F401,F403
from soothe_nano.llm import __all__ as _llm_all  # noqa: F401

# Back-compat aliases for the removed wrapper types.
from soothe_nano.llm.provider import ChatLitellmModel

OpenAICompatModelWrapper = ChatLitellmModel
JsonSchemaModelWrapper = ChatLitellmModel

__all__ = list(_llm_all) + ["OpenAICompatModelWrapper", "JsonSchemaModelWrapper"]
