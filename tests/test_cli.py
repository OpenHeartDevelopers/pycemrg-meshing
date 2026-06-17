"""CLI tests: Click wiring for init-par / run / laplace, including overrides."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from pycemrg_meshing import cli as cli_module
from pycemrg_meshing.cli import cli
from pycemrg_meshing.logic.job import LaplaceSolveJob, MeshingJob
from pycemrg_meshing.logic.results import LaplaceSolveResult, MeshingResult
from pycemrg_meshing.tools.parameters import LaplaceSolveOptions, MeshingOverrides


class _RecordingMeshtoolsRunner:
    """Stand-in for MeshtoolsRunner that records what the CLI passed."""

    last: dict | None = None

    def __init__(self, binary_path=None) -> None:  # noqa: ANN001 - test double
        self.binary_path = binary_path

    def run(self, job, *, cwd=None, overrides=None):  # noqa: ANN001 - test double
        type(self).last = {"job": job, "cwd": cwd, "overrides": overrides}
        return MeshingResult(outdir=Path("/tmp/out"), outputs=[], stdout="")


class _RecordingLaplaceRunner:
    """Stand-in for LaplaceRunner that records what the CLI passed."""

    last: dict | None = None

    def __init__(self, binary_path=None) -> None:  # noqa: ANN001 - test double
        self.binary_path = binary_path

    def run(self, job, *, options=None, cwd=None):  # noqa: ANN001 - test double
        type(self).last = {"job": job, "options": options, "cwd": cwd}
        return LaplaceSolveResult(outdir=Path("/tmp/out"), outputs=[], stdout="")


# --------------------------------------------------------------------- init-par


def test_init_par_writes_file_with_set_override(tmp_path: Path) -> None:
    out = tmp_path / "heart.par"
    result = CliRunner().invoke(
        cli, ["init-par", "-o", str(out), "--set", "meshing.cell_size=1.5"]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "cell_size = 1.5" in out.read_text()


def test_init_par_rejects_malformed_set(tmp_path: Path) -> None:
    out = tmp_path / "heart.par"
    result = CliRunner().invoke(
        cli, ["init-par", "-o", str(out), "--set", "no_equals_sign"]
    )
    assert result.exit_code != 0
    assert "SECTION.KEY=VALUE" in result.output
    assert not out.exists()


def test_init_par_unknown_key_fails_loudly(tmp_path: Path) -> None:
    out = tmp_path / "heart.par"
    result = CliRunner().invoke(
        cli, ["init-par", "-o", str(out), "--set", "meshing.not_a_key=1"]
    )
    assert result.exit_code != 0


def test_init_par_extended_key_only_appears_when_set(tmp_path: Path) -> None:
    """§2.6 keys are valid via --set but absent from a bare init-par file."""
    bare = tmp_path / "bare.par"
    CliRunner().invoke(cli, ["init-par", "-o", str(bare)])
    assert "readTheMesh" not in bare.read_text()

    with_ext = tmp_path / "ext.par"
    result = CliRunner().invoke(
        cli, ["init-par", "-o", str(with_ext), "--set", "meshing.readTheMesh=1"]
    )
    assert result.exit_code == 0, result.output
    assert "readTheMesh = 1" in with_ext.read_text()


# -------------------------------------------------------------------------- run


def test_run_forwards_overrides_to_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "MeshtoolsRunner", _RecordingMeshtoolsRunner)
    parfile = tmp_path / "heart.par"
    parfile.write_text("[output]\noutdir = ./x\n")

    result = CliRunner().invoke(
        cli,
        ["run", str(parfile), "--seg-dir", "/data/case3", "--out-name", "run3"],
    )

    assert result.exit_code == 0, result.output
    assert _RecordingMeshtoolsRunner.last is not None
    job = _RecordingMeshtoolsRunner.last["job"]
    assert isinstance(job, MeshingJob)
    assert job.parfile_path == parfile
    overrides = _RecordingMeshtoolsRunner.last["overrides"]
    assert isinstance(overrides, MeshingOverrides)
    assert overrides.seg_dir == "/data/case3"
    assert overrides.out_name == "run3"
    assert overrides.seg_name is None and overrides.out_dir is None
    assert "outdir=" in result.output


def test_run_missing_parfile_exits_nonzero() -> None:
    result = CliRunner().invoke(cli, ["run", "/no/such/heart.par"])
    assert result.exit_code != 0


def test_run_help_lists_override_flags() -> None:
    result = CliRunner().invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    for flag in ("--seg-dir", "--seg-name", "--out-dir", "--out-name"):
        assert flag in result.output


# ---------------------------------------------------------------------- laplace


def test_laplace_builds_job_and_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "LaplaceRunner", _RecordingLaplaceRunner)
    zero = tmp_path / "base.vtx"
    one = tmp_path / "apex.vtx"
    zero.touch()
    one.touch()

    result = CliRunner().invoke(
        cli,
        [
            "laplace",
            "--mesh-dir", str(tmp_path / "mesh"),
            "--mesh-name", "heart",
            "--out-dir", str(tmp_path / "OUT"),
            "--out-name", "phi",
            "--zero-bc", str(zero),
            "--one-bc", str(one),
            "--potential",
            "--no-thickness",
            "--thickness-algo", "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert _RecordingLaplaceRunner.last is not None
    job = _RecordingLaplaceRunner.last["job"]
    assert isinstance(job, LaplaceSolveJob)
    assert job.mesh_name == "heart"
    assert job.output_name == "phi"
    assert job.zero_bc == (zero,)
    assert job.one_bc == (one,)
    options = _RecordingLaplaceRunner.last["options"]
    assert isinstance(options, LaplaceSolveOptions)
    assert options.potential is True
    assert options.no_thickness is True
    assert options.thickness_algorithm == 2
    assert "outdir=" in result.output


def test_laplace_requires_mesh_and_output(tmp_path: Path) -> None:
    """mesh/output identifiers are required (no .par fallback for laplace)."""
    result = CliRunner().invoke(cli, ["laplace", "--mesh-dir", str(tmp_path)])
    assert result.exit_code != 0


def test_laplace_help_lists_bc_flags() -> None:
    result = CliRunner().invoke(cli, ["laplace", "--help"])
    assert result.exit_code == 0
    for flag in ("--zero-bc", "--one-bc", "--potential", "--vtk", "--no-thickness"):
        assert flag in result.output
