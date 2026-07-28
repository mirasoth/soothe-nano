"""Tests for host-agnostic nano logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from soothe_nano.config import SootheConfig
from soothe_nano.logging.setup import (
    COMMUNITY_LOGGER_NAME,
    PACKAGE_LOGGER_NAMES,
    resolve_package_logger_names,
    setup_logging,
)


@pytest.fixture(autouse=True)
def clear_logger_handlers() -> None:
    names = (*PACKAGE_LOGGER_NAMES, "soothe", "my_host")
    for name in names:
        logging.getLogger(name).handlers.clear()
    yield
    for name in names:
        logging.getLogger(name).handlers.clear()


def test_package_logger_names_are_nano_owned_only() -> None:
    assert PACKAGE_LOGGER_NAMES == ("soothe_nano", COMMUNITY_LOGGER_NAME)
    assert "soothe" not in PACKAGE_LOGGER_NAMES


def test_resolve_package_logger_names_merges_host_extras() -> None:
    assert resolve_package_logger_names(("soothe",)) == (
        "soothe_nano",
        COMMUNITY_LOGGER_NAME,
        "soothe",
    )
    assert resolve_package_logger_names(("soothe_nano", "my_host")) == (
        "soothe_nano",
        COMMUNITY_LOGGER_NAME,
        "my_host",
    )


def test_setup_logging_does_not_attach_unknown_host_by_default(tmp_path: Path) -> None:
    log_file = tmp_path / "nano.log"
    cfg = SootheConfig(
        observability={
            "log_file_level": "INFO",
            "log_file_path": str(log_file),
        }
    )
    setup_logging(cfg)

    nano = logging.getLogger("soothe_nano")
    host = logging.getLogger("soothe")
    assert any(isinstance(h, RotatingFileHandler) for h in nano.handlers)
    assert not any(isinstance(h, RotatingFileHandler) for h in host.handlers)


def test_setup_logging_attaches_extra_logger_names(tmp_path: Path) -> None:
    log_file = tmp_path / "shared.log"
    cfg = SootheConfig(
        observability={
            "log_file_level": "INFO",
            "log_file_path": str(log_file),
        }
    )
    setup_logging(cfg, extra_logger_names=("my_host",))

    host = logging.getLogger("my_host")
    file_handlers = [h for h in host.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename) == log_file
