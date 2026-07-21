"""Tests for host-registered builtin skill roots."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.config import SootheConfig
from soothe_nano.skills.builtins import (
    is_builtin_skill_directory,
    iter_skill_roots,
    register_builtin_skill_root,
)
from soothe_nano.skills.index import SkillIndex
from soothe_nano.skills.workspace_sync import collect_external_skills_to_mirror


def _make_skill(root: Path, name: str, description: str = "desc") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\ntags: test\n---\n# {name}\n",
        encoding="utf-8",
    )
    return d


def test_register_builtin_skill_root_appears_in_iter(tmp_path: Path) -> None:
    from soothe_nano.config import SOOTHE_HOME

    host = tmp_path / "fj_skills"
    host.mkdir()
    unregister = register_builtin_skill_root(host)
    try:
        roots = iter_skill_roots()
        paths = [p for p, _ in roots]
        resolved = host.resolve()
        assert resolved in paths
        # Host root sits after nano builtins and before SOOTHE_HOME/skills
        assert paths.index(resolved) < paths.index(SOOTHE_HOME / "skills")
        sources = dict(roots)
        assert sources[resolved] == "builtin"
    finally:
        unregister()
    assert host.resolve() not in [p for p, _ in iter_skill_roots()]


def test_register_duplicate_ignored(tmp_path: Path) -> None:
    host = tmp_path / "fj_skills"
    host.mkdir()
    u1 = register_builtin_skill_root(host)
    u2 = register_builtin_skill_root(host)
    try:
        count = sum(1 for p, _ in iter_skill_roots() if p == host.resolve())
        assert count == 1
    finally:
        u1()
        u2()


def test_registered_root_indexed_as_builtin(tmp_path: Path) -> None:
    host = tmp_path / "fj_skills"
    host.mkdir()
    _make_skill(host, "fj-review")
    unregister = register_builtin_skill_root(host)
    try:
        index = SkillIndex()
        entries = index.rebuild_if_stale()
        match = next((e for e in entries if e.name == "fj-review"), None)
        assert match is not None
        assert match.source == "builtin"
        assert is_builtin_skill_directory(match.path)
    finally:
        unregister()


def test_registered_builtin_not_mirrored(tmp_path: Path) -> None:
    ws = tmp_path / "project"
    ws.mkdir()
    host = tmp_path / "fj_skills"
    host.mkdir()
    _make_skill(host, "fj-review")
    unregister = register_builtin_skill_root(host)
    try:
        cfg = SootheConfig()
        to_mirror = collect_external_skills_to_mirror(cfg, ws)
        assert "fj-review" not in to_mirror
    finally:
        unregister()


def test_config_builtin_skill_roots(tmp_path: Path) -> None:
    host = tmp_path / "from_yaml"
    host.mkdir()
    _make_skill(host, "yaml-skill")
    # Validator registers the root; keep an unregister handle via re-register (idempotent).
    unregister = register_builtin_skill_root(host)
    try:
        SootheConfig(builtin_skill_roots=[str(host)])
        assert host.resolve() in [p for p, _ in iter_skill_roots()]
        index = SkillIndex()
        entries = index.rebuild_if_stale()
        assert any(e.name == "yaml-skill" for e in entries)
    finally:
        unregister()
