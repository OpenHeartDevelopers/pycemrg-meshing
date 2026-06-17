"""Tests for binary discovery in logic.runners, including the macOS guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycemrg_meshing.logic.runners import MacOSGatekeeperError, MeshtoolsRunner
from pycemrg_meshing.tools.parameters import MeshingOverrides, MeshingParameters


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
        self.cwd = None

    def run(self, cmd, *, cwd=None, env=None):  # noqa: ANN001 - test double
        self.cmd = list(cmd)
        self.cwd = cwd


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


# --------------------------------------------------------------- cwd resolution


def _runner_for_cwd(tmp_path: Path) -> tuple[MeshtoolsRunner, _FakeCommandRunner]:
    binary = tmp_path / "bin" / "meshtools3d"
    binary.parent.mkdir(parents=True)
    binary.touch()
    fake_runner = _FakeCommandRunner()
    return MeshtoolsRunner(binary_path=binary, runner=fake_runner), fake_runner


def test_relative_seg_dir_uses_par_parent_as_cwd(tmp_path: Path) -> None:
    """A relative seg_dir anchors cwd (and outdir) to the par file's parent."""
    par_dir = tmp_path / "case"
    par_dir.mkdir()
    params = MeshingParameters()
    params.set("segmentation", "seg_dir", "./seg/")
    params.set("output", "outdir", "./myocardium_OUT")
    parfile = params.save(par_dir / "heart.par")

    runner, fake_runner = _runner_for_cwd(tmp_path)
    outdir = runner.run(parfile)

    # cwd is the par file's parent, NOT par_parent/seg (which would make the
    # binary double-apply seg_dir to seg/seg/...).
    assert fake_runner.cwd == par_dir
    assert outdir == (par_dir / "myocardium_OUT").resolve()


def test_absolute_seg_dir_colocates_output_with_data(tmp_path: Path) -> None:
    """An absolute seg_dir becomes the cwd so output lands beside the data."""
    par_dir = tmp_path / "case"
    par_dir.mkdir()
    data_dir = tmp_path / "data" / "case1"
    data_dir.mkdir(parents=True)
    params = MeshingParameters()
    params.set("segmentation", "seg_dir", str(data_dir) + "/")
    params.set("output", "outdir", "./myocardium_OUT")
    parfile = params.save(par_dir / "heart.par")

    runner, fake_runner = _runner_for_cwd(tmp_path)
    outdir = runner.run(parfile)

    assert fake_runner.cwd == data_dir.resolve()
    assert outdir == (data_dir / "myocardium_OUT").resolve()


def test_explicit_cwd_overrides_seg_dir(tmp_path: Path) -> None:
    """An explicit cwd wins over any seg_dir heuristic."""
    par_dir = tmp_path / "case"
    par_dir.mkdir()
    override = tmp_path / "elsewhere"
    override.mkdir()
    params = MeshingParameters()
    params.set("segmentation", "seg_dir", str(tmp_path / "data") + "/")
    params.set("output", "outdir", "./myocardium_OUT")
    parfile = params.save(par_dir / "heart.par")

    runner, fake_runner = _runner_for_cwd(tmp_path)
    outdir = runner.run(parfile, cwd=override)

    assert fake_runner.cwd == override.resolve()
    assert outdir == (override / "myocardium_OUT").resolve()


# ----------------------------------------------------------------- Overrides


def test_overrides_are_appended_as_native_flags(tmp_path: Path) -> None:
    """seg_dir/seg_name/out_dir/out_name overrides reach the binary as -flags."""
    parfile = MeshingParameters().save(tmp_path / "heart.par")
    runner, fake_runner = _runner_for_cwd(tmp_path)

    runner.run(
        parfile,
        overrides=MeshingOverrides(
            seg_dir="/data/case2", seg_name="seg.inr", out_dir="OUT", out_name="run2"
        ),
    )

    assert fake_runner.cmd is not None
    # ... -f <par> -seg_dir /data/case2 -seg_name seg.inr -out_dir OUT -out_name run2
    tail = fake_runner.cmd[3:]
    assert tail == [
        "-seg_dir", "/data/case2", "-seg_name", "seg.inr",
        "-out_dir", "OUT", "-out_name", "run2",
    ]


def test_absolute_seg_dir_override_drives_cwd_and_outdir(tmp_path: Path) -> None:
    """An absolute seg_dir override co-locates cwd and a relative outdir there."""
    par_dir = tmp_path / "case"
    par_dir.mkdir()
    data_dir = tmp_path / "data" / "case2"
    data_dir.mkdir(parents=True)
    # Par file keeps the default relative outdir (./myocardium_OUT).
    parfile = MeshingParameters().save(par_dir / "heart.par")

    runner, fake_runner = _runner_for_cwd(tmp_path)
    outdir = runner.run(parfile, overrides=MeshingOverrides(seg_dir=str(data_dir)))

    assert fake_runner.cwd == data_dir.resolve()
    assert outdir == (data_dir / "myocardium_OUT").resolve()


def test_out_dir_override_is_reflected_in_reported_outdir(tmp_path: Path) -> None:
    """Overriding out_dir changes the reported path, not just the binary flag."""
    par_dir = tmp_path / "case"
    par_dir.mkdir()
    parfile = MeshingParameters().save(par_dir / "heart.par")

    runner, _ = _runner_for_cwd(tmp_path)
    # Relative out_dir override resolves against the cwd (par parent here).
    outdir = runner.run(parfile, overrides=MeshingOverrides(out_dir="custom_OUT"))

    assert outdir == (par_dir / "custom_OUT").resolve()
