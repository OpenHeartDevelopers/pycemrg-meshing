"""Tests for binary discovery in logic.runners, including the macOS guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycemrg_meshing.logic.runners import MacOSGatekeeperError, MeshtoolsRunner
from pycemrg_meshing.tools.parameters import MeshingParameters


class _FakeModelManager:
    """Stand-in for pycemrg.ModelManager that returns a fixed path."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get_model_path(self, name: str) -> str:  # noqa: D401 - test double
        return str(self._path)


class _FakeCommandRunner:
    """Captures the command list passed to ``run`` instead of executing it."""

    def __init__(self) -> None:
        self.cmd: list[str] | None = None

    def run(self, cmd, *, cwd=None, env=None):  # noqa: ANN001 - test double
        self.cmd = list(cmd)


# ----------------------------------------------------------- ModelManager path


def test_darwin_modelmanager_path_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "meshtools3d-2.0.0-macos-arm64" / "bin" / "meshtools3d"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr("pycemrg_meshing.logic.runners.sys.platform", "darwin")

    runner = MeshtoolsRunner(model_manager=_FakeModelManager(binary))
    with pytest.raises(MacOSGatekeeperError) as exc:
        runner.resolve_binary()

    message = str(exc.value)
    assert str(binary.parent.parent) in message  # the install root
    assert "codesign" in message
    assert exc.value.install_root == binary.parent.parent


def test_linux_modelmanager_path_returns_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = tmp_path / "meshtools3d-2.0.0-linux-x86_64" / "bin" / "meshtools3d"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr("pycemrg_meshing.logic.runners.sys.platform", "linux")

    runner = MeshtoolsRunner(model_manager=_FakeModelManager(binary))
    assert runner.resolve_binary() == binary


# ----------------------------------------------------------- Explicit override


def test_darwin_explicit_binary_is_not_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user-signed install passed explicitly must never trip the guard."""
    binary = tmp_path / "bin" / "meshtools3d"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setattr("pycemrg_meshing.logic.runners.sys.platform", "darwin")

    runner = MeshtoolsRunner(binary_path=binary)
    assert runner.resolve_binary() == binary.resolve()


# --------------------------------------------------------- Command construction


def test_run_passes_parfile_with_f_flag(tmp_path: Path) -> None:
    """The parameter file must be passed via ``-f``, not positionally."""
    binary = tmp_path / "bin" / "meshtools3d"
    binary.parent.mkdir(parents=True)
    binary.touch()
    parfile = MeshingParameters().save(tmp_path / "heart.par")

    fake_runner = _FakeCommandRunner()
    runner = MeshtoolsRunner(binary_path=binary, runner=fake_runner)
    runner.run(parfile)

    assert fake_runner.cmd is not None
    # binary, then "-f", then the resolved parfile path.
    assert fake_runner.cmd[1] == "-f"
    assert fake_runner.cmd[2] == str(parfile.resolve())
    # The parfile is never passed positionally (as the last bare token).
    assert fake_runner.cmd[-1] == str(parfile.resolve())
    assert fake_runner.cmd.index(str(parfile.resolve())) == 2
