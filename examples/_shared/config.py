"""Self-contained config loader for soothe-nano examples."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.config import SOOTHE_HOME, SootheConfig


def load_nano_example_config() -> SootheConfig:
    """Load config from ``SOOTHE_HOME``, monorepo develop config, or defaults."""
    home_config = Path(SOOTHE_HOME).expanduser() / "config" / "config.yml"
    if home_config.is_file():
        return SootheConfig.from_yaml_file(str(home_config))

    # When developing inside the soothe monorepo: .../soothe/packages/soothe-nano/...
    # Layout: examples/_shared/config.py → package root = parents[2], monorepo = parents[4]
    here = Path(__file__).resolve()
    candidates = [here.parents[2]]
    if len(here.parents) > 4:
        candidates.append(here.parents[4])
    for root in candidates:
        dev_config = root / "config" / "develop" / "config.yml"
        if dev_config.is_file():
            return SootheConfig.from_yaml_file(str(dev_config))

    return SootheConfig()
