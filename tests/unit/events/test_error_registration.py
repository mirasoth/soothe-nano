"""IG-643: nano protocol ERROR is registered in the shared REGISTRY."""

from soothe_sdk.core.events import ERROR
from soothe_sdk.core.registry import REGISTRY

import soothe_nano.events.catalog  # noqa: F401


def test_error_general_event_registered() -> None:
    meta = REGISTRY.get_meta(ERROR)
    assert meta is not None
    assert meta.model.__name__ == "ErrorGeneralEvent"
    assert meta.type_string == "soothe.error.general.failed"
