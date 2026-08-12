"""Self-contained config loader for soothe-nano examples."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the standalone repo's `src/` is importable when examples are run with
# a foreign venv whose `soothe_nano` install is a stale flat snapshot missing
# subpackages (e.g. the monorepo venv). Layout: examples/_shared/config.py →
# package root = parents[2], src = parents[2] / "src".
_here = Path(__file__).resolve()
_pkg_root = _here.parents[2]
_src_root = _pkg_root / "src"
if _src_root.is_dir() and str(_src_root) not in sys.path:
    sys.path.insert(0, str(_src_root))

from soothe_nano.config import SOOTHE_HOME, SootheConfig  # noqa: E402


def load_nano_example_config() -> SootheConfig:
    """Load config from ``SOOTHE_HOME``, monorepo develop config, or defaults."""
    home_config = Path(SOOTHE_HOME).expanduser() / "config" / "nano.yml"
    if home_config.is_file():
        return SootheConfig.from_yaml_file(str(home_config))

    # When developing inside the soothe monorepo: .../soothe/packages/soothe-nano/...
    # Layout: examples/_shared/config.py → package root = parents[2], monorepo = parents[4]
    here = Path(__file__).resolve()
    candidates = [here.parents[2]]
    if len(here.parents) > 4:
        candidates.append(here.parents[4])
    for root in candidates:
        dev_config = root / "config" / "develop" / "nano.yml"
        if dev_config.is_file():
            return SootheConfig.from_yaml_file(str(dev_config))

    return SootheConfig()
