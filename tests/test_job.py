"""Tests for the job contracts and disk-verified result collection."""

from __future__ import annotations

from pathlib import Path

from pycemrg_meshing.logic.job import LaplaceSolveJob, MeshingJob
from pycemrg_meshing.logic.results import MeshingResult
from pycemrg_meshing.logic.runners import MeshtoolsRunner
from pycemrg_meshing.tools.parameters import LaplaceSolveOptions, MeshingParameters

# --------------------------------------------------------------- MeshingJob


def test_from_parfile_reconstructs_paths(tmp_path: Path) -> None:
    params = MeshingParameters()
    params.set("segmentation", "seg_dir", "/data/case1")
    params.set("segmentation", "seg_name", "seg.inr")
    params.set("output", "outdir", "/out/case1")
    params.set("output", "name", "mesh1")
    parfile = params.save(tmp_path / "heart.par")

    job = MeshingJob.from_parfile(parfile)

    assert job.segmentation_path == Path("/data/case1/seg.inr")
    assert job.output_dir == Path("/out/case1")
    assert job.output_name == "mesh1"
    assert job.parfile_path == parfile


def test_expected_outputs_default_base(tmp_path: Path) -> None:
    job = MeshingJob.create(
        segmentation_path=tmp_path / "seg.inr",
        output_dir=tmp_path / "OUT",
        output_name="m",
        parfile_path=tmp_path / "heart.par",
    )
    outs = job.expected_outputs(MeshingParameters())  # default: carp + vtk on
    names = {p.name for p in outs}
    assert names == {"m.elem", "m.pts", "m.lon", "m.vtk"}
    assert all(p.parent == (tmp_path / "OUT") for p in outs)


def test_expected_outputs_rebases_onto_override(tmp_path: Path) -> None:
    job = MeshingJob.create(
        segmentation_path=tmp_path / "seg.inr",
        output_dir=tmp_path / "OUT",
        output_name="m",
        parfile_path=tmp_path / "heart.par",
    )
    outs = job.expected_outputs(
        MeshingParameters(), output_dir=tmp_path / "ELSE", output_name="z"
    )
    assert all(p.parent == (tmp_path / "ELSE") for p in outs)
    assert {p.stem for p in outs} == {"z"}


def test_expected_outputs_honours_flags(tmp_path: Path) -> None:
    params = MeshingParameters()
    params.set("output", "out_carp", "0")
    params.set("output", "out_vtk", "0")
    params.set("output", "out_medit", "1")
    job = MeshingJob.create(
        segmentation_path=tmp_path / "seg.inr",
        output_dir=tmp_path / "OUT",
        output_name="m",
        parfile_path=tmp_path / "heart.par",
    )
    outs = job.expected_outputs(params)
    assert [p.name for p in outs] == ["m.mesh"]


# --------------------------------------------------------------- LaplaceSolveJob


def test_laplace_job_create_normalises_and_renders(tmp_path: Path) -> None:
    job = LaplaceSolveJob.create(
        mesh_dir=str(tmp_path / "mesh"),
        mesh_name="heart",
        output_dir=str(tmp_path / "OUT"),
        output_name="phi",
        zero_bc=(str(tmp_path / "a.vtx"),),
        one_bc=(str(tmp_path / "b.vtx"),),
    )
    assert isinstance(job.mesh_dir, Path)
    assert all(isinstance(p, Path) for p in job.zero_bc + job.one_bc)
    assert job.as_cli_args() == [
        "-mesh_dir", str(tmp_path / "mesh"),
        "-mesh_name", "heart",
        "-out_dir", str(tmp_path / "OUT"),
        "-out_name", "phi",
        "--zero-bc", str(tmp_path / "a.vtx"),
        "--one-bc", str(tmp_path / "b.vtx"),
    ]


def _laplace_job(tmp_path: Path) -> LaplaceSolveJob:
    return LaplaceSolveJob.create(
        mesh_dir=tmp_path, mesh_name="h", output_dir=tmp_path / "OUT", output_name="phi"
    )


def test_laplace_outputs_default_thickness_no_vtk(tmp_path: Path) -> None:
    """Default (thickness on, no vtk/potential): grad/cpts/tris + _thickness.dat."""
    outs = _laplace_job(tmp_path).expected_outputs(None)
    assert {p.name for p in outs} == {
        "phi.grad", "phi.cpts", "phi.tris", "phi_thickness.dat"
    }
    assert all(p.parent == (tmp_path / "OUT") for p in outs)


def test_laplace_outputs_vtk_subsumes_dat_files(tmp_path: Path) -> None:
    """With --vtk, the .dat side-channels are not written."""
    opts = LaplaceSolveOptions(vtk=True, potential=True)
    outs = {p.name for p in _laplace_job(tmp_path).expected_outputs(opts)}
    assert outs == {"phi.grad", "phi.cpts", "phi.tris", "phi.vtk"}


def test_laplace_outputs_no_thickness_potential_only(tmp_path: Path) -> None:
    """--no-thickness + --potential (no vtk): just the potential .dat."""
    opts = LaplaceSolveOptions(no_thickness=True, potential=True)
    outs = {p.name for p in _laplace_job(tmp_path).expected_outputs(opts)}
    assert outs == {"phi_potential.dat"}


def test_laplace_outputs_no_thickness_no_potential(tmp_path: Path) -> None:
    opts = LaplaceSolveOptions(no_thickness=True)
    assert _laplace_job(tmp_path).expected_outputs(opts) == []


def test_laplace_outputs_rebase_onto_effective_dir(tmp_path: Path) -> None:
    outs = _laplace_job(tmp_path).expected_outputs(
        LaplaceSolveOptions(no_thickness=True, vtk=True),
        output_dir=tmp_path / "ELSE",
        output_name="z",
    )
    assert {p.name for p in outs} == {"z.vtk"}
    assert all(p.parent == (tmp_path / "ELSE") for p in outs)


# --------------------------------------------------------------- Result sizing


class _FileWritingRunner:
    """Test double that creates each expected output, mimicking a real binary."""

    def __init__(self, payload: bytes = b"xyz") -> None:
        self._payload = payload

    def run(self, cmd, *, expected_outputs=None, cwd=None, env=None):  # noqa: ANN001
        for path in expected_outputs or []:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self._payload)
        return "done"


def test_result_reports_disk_sizes_and_stdout(tmp_path: Path) -> None:
    binary = tmp_path / "bin" / "meshtools3d"
    binary.parent.mkdir(parents=True)
    binary.touch()
    parfile = MeshingParameters().save(tmp_path / "heart.par")

    runner = MeshtoolsRunner(binary_path=binary, runner=_FileWritingRunner(b"abcd"))
    result = runner.run(MeshingJob.from_parfile(parfile))

    assert isinstance(result, MeshingResult)
    assert result.stdout == "done"
    assert len(result.outputs) == 4  # carp triplet + vtk
    assert all(o.size == 4 for o in result.outputs)
    assert all(o.path.exists() for o in result.outputs)
