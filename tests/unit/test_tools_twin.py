"""Twin-drift guard for the soothe_client.tools dual copy.

``soothe_client/tools`` (client axis) is a byte-identical twin of
``soothe_nano/tools`` except the self-import package name. The canonical
source is nano; after editing it, copy both files to
``soothe/client/python/src/soothe_client/tools/`` and bump the pinned sha256
values here and in the client-side twin test.

``__init__.py`` is hashed after normalizing ``soothe_nano`` → ``soothe_client``
(the only permitted difference).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[2] / "src" / "soothe_nano" / "tools"
METADATA_SHA256 = "8e5b03d7a47ccf363f5052e593582922c45ece917032e0fa82377b3db9779147"
INIT_NORMALIZED_SHA256 = "85df3369f5c3595b3a76d2af382aded5afc1d15ab83dd7da59aa55103cbb7116"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_metadata_twin_is_pinned() -> None:
    digest = _sha256((TOOLS_DIR / "metadata.py").read_bytes())
    assert digest == METADATA_SHA256, (
        "tools/metadata.py changed — copy it to "
        "soothe/client/python/src/soothe_client/tools/metadata.py and update "
        "METADATA_SHA256 in BOTH twin tests"
    )


def test_init_twin_is_pinned_up_to_import_path() -> None:
    text = (TOOLS_DIR / "__init__.py").read_text(encoding="utf-8")
    digest = _sha256(text.replace("soothe_nano", "soothe_client").encode("utf-8"))
    assert digest == INIT_NORMALIZED_SHA256, (
        "tools/__init__.py changed beyond the import path — mirror it in "
        "soothe/client/python/src/soothe_client/tools/__init__.py and update "
        "INIT_NORMALIZED_SHA256 in BOTH twin tests"
    )
