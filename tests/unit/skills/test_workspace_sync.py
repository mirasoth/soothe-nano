"""Tests for mirroring external skills into the workspace (virtual mode)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from soothe_nano.config import SootheConfig
from soothe_nano.skills.builtins import SkillRoots
from soothe_nano.skills.catalog import SkillCatalog
from soothe_nano.skills.workspace_sync import WorkspaceSkillMirror

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _write_skill(skill_dir: Path, name: str, body: str = "# Skill\n") -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test\n---\n{body}",
        encoding="utf-8",
    )
    (skill_dir / "extra.txt").write_text("more", encoding="utf-8")


def test_is_builtin_skill_directory() -> None:
    package_builtins = (
        Path(__file__).resolve().parents[3] / "src" / "soothe_nano" / "skills" / "builtin"
    )
    assert package_builtins.is_dir()
    assert SkillRoots.is_builtin_directory(next(package_builtins.iterdir()))
    assert not SkillRoots.is_builtin_directory("/tmp/user-skill")


def test_collect_external_from_host_skill_roots(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """Skills under host roots (e.g. ~/.agents/skills) are collected for mirroring."""
    ws = tmp_path / "project"
    ws.mkdir()
    agents_root = tmp_path / "agents_skills"
    _write_skill(agents_root / "from-agents", "from-agents")

    def fake_builtin_paths(workspace: str | None = None) -> list[str]:
        del workspace
        return [str(agents_root / "from-agents")]

    monkeypatch.setattr(
        "soothe_nano.skills.workspace_sync.SkillRoots.builtin_paths",
        fake_builtin_paths,
    )
    cfg = SootheConfig()
    to_mirror = WorkspaceSkillMirror(cfg, ws).collect_external()
    assert "from-agents" in to_mirror
    assert to_mirror["from-agents"] == (agents_root / "from-agents").resolve()


def test_sync_external_skill_into_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "project"
    ws.mkdir()
    host_skills = tmp_path / "host_skills"
    _write_skill(host_skills / "weather", "weather", body="Forecast rules\n")

    cfg = SootheConfig()
    cfg.skills = [str(host_skills / "weather")]

    mirror = WorkspaceSkillMirror(cfg, ws)
    to_mirror = mirror.collect_external()
    assert "weather" in to_mirror

    mirrored = mirror.sync_all()
    dest = Path(mirrored["weather"])
    assert dest == mirror.mirror_root() / "weather"
    assert (dest / "SKILL.md").is_file()
    assert (dest / "extra.txt").read_text(encoding="utf-8") == "more"
    assert mirror.is_under_workspace(dest)


def test_sync_skips_builtin_and_in_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "project"
    ws.mkdir()
    in_ws = WorkspaceSkillMirror(SootheConfig(), ws).mirror_root() / "local-skill"
    _write_skill(in_ws, "local-skill")

    cfg = SootheConfig()
    mirrored = WorkspaceSkillMirror(cfg, ws).sync_all()
    assert "local-skill" not in mirrored


def test_resolve_prefers_workspace_mirror_after_sync(tmp_path: Path) -> None:
    ws = tmp_path / "project"
    ws.mkdir()
    host = tmp_path / "agents_skills"
    _write_skill(host / "demo", "demo", body="From host\n")

    cfg = SootheConfig()
    cfg.skills = [str(host / "demo")]

    mirror = WorkspaceSkillMirror(cfg, ws)
    mirror.sync_all()
    meta = SkillCatalog(cfg, str(ws)).resolve_skill("demo")
    assert meta is not None
    assert mirror.is_under_workspace(Path(meta["path"]))
    assert "From host" in (host / "demo" / "SKILL.md").read_text(encoding="utf-8")


def test_sync_is_idempotent_without_source_change(tmp_path: Path) -> None:
    ws = tmp_path / "project"
    ws.mkdir()
    host = tmp_path / "host"
    _write_skill(host / "x", "x")

    cfg = SootheConfig()
    cfg.skills = [str(host)]
    mirror = WorkspaceSkillMirror(cfg, ws.resolve())
    first = mirror.sync_skill(host / "x", skill_name="x")
    mtime_first = (first / "SKILL.md").stat().st_mtime
    second = mirror.sync_skill(host / "x", skill_name="x")
    mtime_second = (second / "SKILL.md").stat().st_mtime
    assert mtime_first == mtime_second


def test_build_skill_context_omits_folder_for_builtin() -> None:
    builtin_path = next(
        (
            Path(__file__).resolve().parents[3] / "src" / "soothe_nano" / "skills" / "builtin"
        ).iterdir()
    )
    meta = {
        "name": "builtin-test",
        "description": "d",
        "path": builtin_path,
        "source": "builtin",
    }
    text = SkillCatalog(SootheConfig()).build_context_text(meta, "---\nname: x\n---\nBody\n")
    assert "Skill folder:" not in text
