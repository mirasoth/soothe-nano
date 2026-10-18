"""ArcBox E2E tests (docs/arcbox-backend.md §12) — require a live ArcBox daemon.

Opt-in: ``uv run pytest tests/integration/test_arcbox_e2e.py --run-integration``.
The guest template must ship a working ``python3`` (all ``BaseSandbox``-derived
file tools run ``python3 -c`` stdlib scripts) plus GNU coreutils, ``setsid``
(util-linux) and a ``kill`` that accepts ``-- -PGID`` (procps). The canonical
template definition lives at ``docker/templates/e2e/Dockerfile``::

    abctl sandbox template build soothe-nano-e2e \
        --from-dockerfile docker/templates/e2e/Dockerfile

Override the template via ``ARCBOX_E2E_TEMPLATE``.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

from soothe_nano.sandbox.arcbox import ArcBoxBackend

pytestmark = pytest.mark.integration

WORKSPACE = "/workspace"
_DEFAULT_TEMPLATE = "soothe-nano-e2e"


@pytest.fixture(scope="session")
def arcbox_env() -> Any:
    """Connect to the daemon, create one sandbox, tear it down afterwards."""
    import arcbox

    client = arcbox.ArcBox()
    try:
        try:
            client.capabilities()
        except Exception as exc:  # noqa: BLE001 -- any connect failure = skip
            pytest.skip(f"ArcBox daemon not reachable: {exc}")

        template = os.environ.get("ARCBOX_E2E_TEMPLATE", _DEFAULT_TEMPLATE)
        try:
            sandbox = client.create(template, wait_until_ready=True)
        except arcbox.errors.TemplateNotFoundError as exc:
            pytest.skip(
                f"ArcBox template '{template}' not built; "
                f"build it with `abctl sandbox template build {template} ...`: {exc}"
            )
        except arcbox.errors.NotFoundError as exc:
            pytest.skip(f"ArcBox template/sandbox resource not found: {exc}")
        try:
            yield SimpleNamespace(client=client, sandbox=sandbox)
        finally:
            try:
                sandbox.kill()
            except Exception:  # noqa: BLE001 -- teardown best-effort
                pass
    finally:
        client.close()


@pytest.fixture()
def backend(arcbox_env: Any) -> ArcBoxBackend:
    return ArcBoxBackend(
        sandbox_id=arcbox_env.sandbox.id,
        workspace_root=WORKSPACE,
        default_timeout=60,
    )


class TestImagePrerequisites:
    """§12.4-2: guest image must ship python3 + the tool set the code paths use."""

    def test_python3_works(self, backend: ArcBoxBackend) -> None:
        response = backend.execute("python3 -c 'print(40 + 2)'")
        assert response.exit_code == 0
        assert "42" in response.output

    def test_required_binaries_present(self, backend: ArcBoxBackend) -> None:
        response = backend.execute(
            "for b in setsid nohup tail head kill sh ls mkdir cat mv rm; do "
            'command -v "$b" >/dev/null || { echo "missing: $b"; exit 1; }; done'
        )
        assert response.exit_code == 0, response.output


class TestExecuteSemantics:
    """§12.4-3/5: basic execution, exit codes, output merge, timeout convention."""

    def test_pwd_is_workspace(self, backend: ArcBoxBackend) -> None:
        response = backend.execute("pwd")
        assert response.exit_code == 0
        assert response.output.strip() == WORKSPACE

    def test_uname_and_stderr_merge(self, backend: ArcBoxBackend) -> None:
        response = backend.execute("uname -s; echo to-stderr >&2")
        assert response.exit_code == 0
        assert "Linux" in response.output
        assert "to-stderr" in response.output

    def test_nonzero_exit_code_preserved(self, backend: ArcBoxBackend) -> None:
        response = backend.execute("exit 7")
        assert response.exit_code == 7

    def test_timeout_maps_to_124(self, backend: ArcBoxBackend) -> None:
        response = backend.execute("sleep 30", timeout=3)
        assert response.exit_code == 124
        assert "timeout" in response.output.lower()


class TestFsShellConsistency:
    """§12.4-4/6: FS tools and shell share the guest workspace."""

    def test_fs_write_visible_to_shell(self, backend: ArcBoxBackend) -> None:
        assert backend.write(f"{WORKSPACE}/e2e-fs.txt", "fs-marker-42").error is None
        response = backend.execute("cat e2e-fs.txt")
        assert "fs-marker-42" in response.output

    def test_shell_write_visible_to_fs(self, backend: ArcBoxBackend) -> None:
        assert backend.execute("echo shell-marker-42 > e2e-shell.txt").exit_code == 0
        read = backend.read(f"{WORKSPACE}/e2e-shell.txt")
        assert read.error is None
        assert "shell-marker-42" in read.file_data["content"]

    def test_glob_grep_edit_delete_roundtrip(self, backend: ArcBoxBackend) -> None:
        assert backend.write(f"{WORKSPACE}/e2e/a.txt", "alpha needle\n").error is None
        assert backend.write(f"{WORKSPACE}/e2e/b.txt", "beta\n").error is None

        glob = backend.glob("*.txt", f"{WORKSPACE}/e2e")
        assert glob.error is None
        assert len(glob.matches) >= 2

        grep = backend.grep("needle", path=f"{WORKSPACE}/e2e")
        assert grep.error is None
        assert grep.matches

        edit = backend.edit(f"{WORKSPACE}/e2e/a.txt", "needle", "replaced")
        assert edit.error is None
        read = backend.read(f"{WORKSPACE}/e2e/a.txt")
        assert "replaced" in read.file_data["content"]

        delete = backend.delete(f"{WORKSPACE}/e2e/b.txt")
        assert delete.error is None
        assert backend.read(f"{WORKSPACE}/e2e/b.txt").error is not None


class TestCaptureOffload:
    """§12.4-7: large output is offloaded with the exit code preserved."""

    def test_large_output_offloaded_exit_code_kept(self, arcbox_env: Any) -> None:
        backend = ArcBoxBackend(
            sandbox_id=arcbox_env.sandbox.id,
            workspace_root=WORKSPACE,
            default_timeout=60,
            enable_capture_offload=True,
        )
        assert (
            backend.write(
                f"{WORKSPACE}/gen_big.py", "import sys\nsys.stdout.write('x' * 300000)\n"
            ).error
            is None
        )
        offloaded = backend.execute_with_offload(
            "python3 gen_big.py",
            f"{WORKSPACE}/.soothe/captures/e2e-big.log",
            max_inline_bytes=1000,
            timeout=60,
        )
        assert offloaded.response.exit_code == 0
        # Preview is a bounded head/tail window (may exceed max_inline_bytes);
        # the contract is: offloaded=True, full capture left in the guest.
        assert getattr(offloaded, "offloaded", None) is True
        assert len(offloaded.response.output) < 300000


class TestLifecycleSafety:
    """§12.4-8/9: no sandbox leaks; stopped-sandbox operations error as data."""

    def test_repeated_calls_create_no_extra_sandboxes(self, arcbox_env: Any) -> None:
        before = len(list(arcbox_env.client.list()))
        backend = ArcBoxBackend(sandbox_id=arcbox_env.sandbox.id, workspace_root=WORKSPACE)
        for _ in range(5):
            assert backend.execute("true").exit_code == 0
        after = len(list(arcbox_env.client.list()))
        assert after == before

    def test_stopped_sandbox_errors_as_data(self, arcbox_env: Any) -> None:
        sandbox = arcbox_env.client.create(
            os.environ.get("ARCBOX_E2E_TEMPLATE", _DEFAULT_TEMPLATE),
            wait_until_ready=True,
        )
        backend = ArcBoxBackend(sandbox_id=sandbox.id, workspace_root=WORKSPACE)
        try:
            assert backend.execute("true").exit_code == 0
        finally:
            sandbox.kill()
        response = backend.execute("true")
        assert response.exit_code is None
        assert response.output.startswith("Error")


class TestCredentialsNeverReachGuest:
    """§12.4-10: no model credentials in the guest environment."""

    def test_guest_env_has_no_api_keys(self, backend: ArcBoxBackend) -> None:
        response = backend.execute(
            "env | grep -iE 'api_key|apikey|anthropic|openai|secret' || true"
        )
        assert response.output.strip() == ""
        assert backend.execute("env | grep -c 'sk-' || true").output.strip() == "0"


class TestAgentBuildAcceptance:
    """§12.5: agent builds against the live backend; shell routes to the guest."""

    def test_create_nano_agent_with_backend(self, arcbox_env: Any) -> None:
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        from soothe_nano import create_nano_agent
        from soothe_nano.config import SootheConfig

        backend = ArcBoxBackend(
            sandbox_id=arcbox_env.sandbox.id,
            workspace_root=WORKSPACE,
            default_timeout=60,
        )
        agent = create_nano_agent(
            SootheConfig(),
            model=FakeListChatModel(responses=["ok"]),
            backend=backend,
        )
        assert agent.list_capabilities().metadata.get("sandbox") is True

    def test_shell_executor_routes_to_guest(self, arcbox_env: Any) -> None:
        from soothe_nano.toolkits.shell import BackendShellExecutor

        backend = ArcBoxBackend(
            sandbox_id=arcbox_env.sandbox.id,
            workspace_root=WORKSPACE,
            default_timeout=60,
        )
        executor = BackendShellExecutor(backend, workspace_root=WORKSPACE)
        outcome = executor.run(
            "echo e2e-shell-route && python3 -c 'print(6*7)'", cwd=None, timeout=30
        )
        assert outcome.error is None
        assert outcome.exit_code == 0
        assert "e2e-shell-route" in outcome.stdout
        assert "42" in outcome.stdout
