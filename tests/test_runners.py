"""Tests for binary discovery and execution in logic.runners.

Covers the macOS guard, command construction, cwd/outdir resolution, overrides,
and that the job's expected outputs are threaded into CommandRunner (fail-fast).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycemrg_meshing.logic.job import LaplaceSolveJob, MeshingJob
from pycemrg_meshing.logic.results import LaplaceSolveResult, MeshingResult
from pycemrg_meshing.logic.runners import (
    LaplaceRunner,
    MacOSGatekeeperError,
    MeshtoolsRunner,
)
from pycemrg_meshing.tools.parameters import (
    LaplaceSolveOptions,
    MeshingOverrides,
    MeshingParameters,
)


class _FakeModelManager:
    """Stand-in for pycemrg.ModelManager that returns a fixed path."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get_model_path(self, name: str) -> str:  # noqa: D401 - test double
        return str(self._path)


class _FakeCommandRunner:
    """Captures what ``run`` received instead of executing it; returns stdout."""

    def __init__(self, stdout: str = "") -> None:
        self.cmd: list[str] | None = None
        self.cwd = None
        self.expected_outputs: list[Path] = []
        self._stdout = stdout

    def run(self, cmd, *, expected_outputs=None, cwd=None, env=None):  # noqa: ANN001
        self.cmd = list(cmd)
        self.cwd = cwd
        self.expected_outputs = list(expected_outputs) if expected_outputs else []
        return self._stdout


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


# ----------------------------------------------------- meshtools3d construction


def _meshtools_runner(tmp_path: Path) -> tuple[MeshtoolsRunner, _FakeCommandRunner]:
    binary = tmp_path / "bin" / "meshtools3d"
    binary.parent.mkdir(parents=True)
    binary.touch()
    fake_runner = _FakeCommandRunner()
    return MeshtoolsRunner(binary_path=binary, runner=fake_runner), fake_runner


def test_run_passes_parfile_with_f_flag(tmp_path: Path) -> None:
    """The parameter file must be passed via ``-f``, not positionally."""
    parfile = MeshingParameters().save(tmp_path / "heart.par")
    runner, fake_runner = _meshtools_runner(tmp_path)

    result = runner.run(MeshingJob.from_parfile(parfile))

    assert isinstance(result, MeshingResult)
    assert fake_runner.cmd is not None
    assert fake_runner.cmd[1] == "-f"
    assert fake_runner.cmd[2] == str(parfile.resolve())
    assert fake_runner.cmd.index(str(parfile.resolve())) == 2


def test_run_threads_expected_outputs_into_command_runner(tmp_path: Path) -> None:
    """The job's expected outputs reach CommandRunner for fail-fast verification."""
    par_dir = tmp_path / "case"
    par_dir.mkdir()
    parfile = MeshingParameters().save(par_dir / "heart.par")  # default: carp+vtk on
    runner, fake_runner = _meshtools_runner(tmp_path)

    runner.run(MeshingJob.from_parfile(parfile))

    out = par_dir / "myocardium_OUT" / "heart_mesh"
    expected = {p.resolve() for p in fake_runner.expected_outputs}
    assert out.with_suffix(".elem").resolve() in expected
    assert out.with_suffix(".pts").resolve() in expected
    assert out.with_suffix(".lon").resolve() in expected
    assert out.with_suffix(".vtk").resolve() in expected


# --------------------------------------------------------------- cwd resolution


def test_relative_seg_dir_uses_par_parent_as_cwd(tmp_path: Path) -> None:
    """A relative seg_dir anchors cwd (and outdir) to the par file's parent."""
    par_dir = tmp_path / "case"
    par_dir.mkdir()
    params = MeshingParameters()
    params.set("segmentation", "seg_dir", "./seg/")
    params.set("output", "outdir", "./myocardium_OUT")
    parfile = params.save(par_dir / "heart.par")

    runner, fake_runner = _meshtools_runner(tmp_path)
    result = runner.run(MeshingJob.from_parfile(parfile))

    assert fake_runner.cwd == par_dir
    assert result.outdir == (par_dir / "myocardium_OUT").resolve()


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

    runner, fake_runner = _meshtools_runner(tmp_path)
    result = runner.run(MeshingJob.from_parfile(parfile))

    assert fake_runner.cwd == data_dir.resolve()
    assert result.outdir == (data_dir / "myocardium_OUT").resolve()


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

    runner, fake_runner = _meshtools_runner(tmp_path)
    result = runner.run(MeshingJob.from_parfile(parfile), cwd=override)

    assert fake_runner.cwd == override.resolve()
    assert result.outdir == (override / "myocardium_OUT").resolve()


# ------------------------------------------------------------ meshtools3d overrides


def test_overrides_are_appended_as_native_flags(tmp_path: Path) -> None:
    """seg_dir/seg_name/out_dir/out_name overrides reach the binary as -flags."""
    parfile = MeshingParameters().save(tmp_path / "heart.par")
    runner, fake_runner = _meshtools_runner(tmp_path)

    runner.run(
        MeshingJob.from_parfile(parfile),
        overrides=MeshingOverrides(
            seg_dir="/data/case2", seg_name="seg.inr", out_dir="OUT", out_name="run2"
        ),
    )

    assert fake_runner.cmd is not None
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
    parfile = MeshingParameters().save(par_dir / "heart.par")

    runner, fake_runner = _meshtools_runner(tmp_path)
    result = runner.run(
        MeshingJob.from_parfile(parfile), overrides=MeshingOverrides(seg_dir=str(data_dir))
    )

    assert fake_runner.cwd == data_dir.resolve()
    assert result.outdir == (data_dir / "myocardium_OUT").resolve()


def test_out_dir_override_is_reflected_in_reported_outdir(tmp_path: Path) -> None:
    """Overriding out_dir changes the reported path AND the predicted outputs."""
    par_dir = tmp_path / "case"
    par_dir.mkdir()
    parfile = MeshingParameters().save(par_dir / "heart.par")

    runner, fake_runner = _meshtools_runner(tmp_path)
    result = runner.run(
        MeshingJob.from_parfile(parfile), overrides=MeshingOverrides(out_dir="custom_OUT")
    )

    assert result.outdir == (par_dir / "custom_OUT").resolve()
    # Expected outputs are re-based onto the overridden outdir, not the .par one.
    predicted = {p.resolve() for p in fake_runner.expected_outputs}
    assert (par_dir / "custom_OUT" / "heart_mesh.elem").resolve() in predicted


def test_thickness_and_verbose_overrides_render(tmp_path: Path) -> None:
    parfile = MeshingParameters().save(tmp_path / "heart.par")
    runner, fake_runner = _meshtools_runner(tmp_path)

    runner.run(
        MeshingJob.from_parfile(parfile),
        overrides=MeshingOverrides(thickness_algorithm=2, verbose=True),
    )

    assert fake_runner.cmd is not None
    assert "--thickness-algorithm" in fake_runner.cmd
    assert fake_runner.cmd[fake_runner.cmd.index("--thickness-algorithm") + 1] == "2"
    assert "--verbose" in fake_runner.cmd


def test_missing_parfile_raises(tmp_path: Path) -> None:
    runner, _ = _meshtools_runner(tmp_path)
    job = MeshingJob.create(
        segmentation_path=tmp_path / "seg.inr",
        output_dir=tmp_path / "out",
        output_name="m",
        parfile_path=tmp_path / "does_not_exist.par",
    )
    with pytest.raises(FileNotFoundError):
        runner.run(job)


# ------------------------------------------------------------- laplace_solver


def _laplace_runner(tmp_path: Path) -> tuple[LaplaceRunner, _FakeCommandRunner]:
    binary = tmp_path / "bin" / "laplace_solver"
    binary.parent.mkdir(parents=True)
    binary.touch()
    fake_runner = _FakeCommandRunner()
    return LaplaceRunner(binary_path=binary, runner=fake_runner), fake_runner


def test_laplace_renders_job_flags_and_options(tmp_path: Path) -> None:
    """laplace argv carries the job's mesh/output/BC flags plus option toggles."""
    mesh_dir = tmp_path / "mesh"
    mesh_dir.mkdir()
    zero = tmp_path / "base.vtx"
    one = tmp_path / "apex.vtx"
    zero.touch()
    one.touch()
    runner, fake_runner = _laplace_runner(tmp_path)

    job = LaplaceSolveJob.create(
        mesh_dir=mesh_dir,
        mesh_name="heart",
        output_dir=tmp_path / "OUT",
        output_name="phi",
        zero_bc=(zero,),
        one_bc=(one,),
    )
    result = runner.run(job, options=LaplaceSolveOptions(potential=True, no_thickness=True))

    assert isinstance(result, LaplaceSolveResult)
    cmd = fake_runner.cmd
    assert cmd is not None
    # No parfile, so argv starts straight at the job flags.
    assert "-mesh_dir" in cmd and cmd[cmd.index("-mesh_dir") + 1] == str(mesh_dir)
    assert "-mesh_name" in cmd and cmd[cmd.index("-mesh_name") + 1] == "heart"
    assert "--zero-bc" in cmd and cmd[cmd.index("--zero-bc") + 1] == str(zero)
    assert "--one-bc" in cmd and cmd[cmd.index("--one-bc") + 1] == str(one)
    assert "--potential" in cmd
    assert "--no-thickness" in cmd
    # cwd anchored on the absolute mesh_dir; outdir resolved against it.
    assert fake_runner.cwd == mesh_dir.resolve()
    assert result.outdir == (tmp_path / "OUT").resolve()


def test_laplace_parfile_optional_and_passed_with_f(tmp_path: Path) -> None:
    mesh_dir = tmp_path / "mesh"
    mesh_dir.mkdir()
    parfile = MeshingParameters().save(tmp_path / "laplace.par")
    runner, fake_runner = _laplace_runner(tmp_path)

    job = LaplaceSolveJob.create(
        mesh_dir=mesh_dir,
        mesh_name="heart",
        output_dir=tmp_path / "OUT",
        output_name="phi",
        parfile_path=parfile,
    )
    runner.run(job)

    cmd = fake_runner.cmd
    assert cmd is not None
    assert cmd[1] == "-f"
    assert cmd[2] == str(parfile.resolve())
