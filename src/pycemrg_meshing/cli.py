"""Console entry point for ``pycemrg-meshing`` (Click-based).

Subcommands:

* ``init-par``  — write a default ``.par`` file, optionally with overrides.
* ``run``       — execute ``meshtools3d`` against a parameter file.
* ``laplace``   — execute ``laplace_solver`` against a parameter file.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from pycemrg_meshing.logic.job import LaplaceSolveJob, MeshingJob
from pycemrg_meshing.logic.results import LaplaceSolveResult, MeshingResult
from pycemrg_meshing.logic.runners import LaplaceRunner, MeshtoolsRunner
from pycemrg_meshing.tools.parameters import (
    LaplaceSolveOptions,
    MeshingOverrides,
    MeshingParameters,
)

# ------------------------------------------------------------------- Helpers


def _parse_set(token: str) -> tuple[str, str, str]:
    """Parse a ``--set SECTION.KEY=VALUE`` token, or raise ``BadParameter``."""
    section_key, sep_eq, value = token.partition("=")
    if not sep_eq:
        raise click.BadParameter(
            f"expected SECTION.KEY=VALUE, got: {token!r}", param_hint="--set"
        )
    section, sep_dot, key = section_key.partition(".")
    if not sep_dot or not section or not key:
        raise click.BadParameter(
            f"expected SECTION.KEY=VALUE, got: {token!r}", param_hint="--set"
        )
    return section, key, value


def _expand(value: str | None) -> str | None:
    """Expand a leading ``~`` in a user-supplied path; keep relative paths relative."""
    return str(Path(value).expanduser()) if value is not None else None


def _echo_result(binary: str, result: MeshingResult | LaplaceSolveResult) -> None:
    """Print a run's outdir and the files it produced."""
    click.echo(f"{binary} completed; outdir={result.outdir}")
    for out in result.outputs:
        click.echo(f"  {out.path} ({out.size} bytes)")


# ----------------------------------------------------------------- Top-level


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", is_flag=True, help="enable INFO logging")
def cli(verbose: bool) -> None:
    """Author and execute meshtools3d parameter-file workflows."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


# ----------------------------------------------------------------- Subcommands


@cli.command("init-par")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("heart.par"),
    show_default=True,
    help="path for the generated parameter file",
)
@click.option(
    "--set",
    "set_",
    multiple=True,
    metavar="SECTION.KEY=VALUE",
    help="override a parameter; may be passed multiple times",
)
def init_par(output: Path, set_: tuple[str, ...]) -> None:
    """Write a default meshtools3d parameter file."""
    params = MeshingParameters()
    for token in set_:
        section, key, value = _parse_set(token)
        params.set(section, key, value)
    out = params.save(output)
    click.echo(f"wrote {out}")


@cli.command("run")
@click.argument(
    "parfile", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "--binary",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="explicit binary path; otherwise resolved via pycemrg.AssetManager",
)
@click.option(
    "--cwd",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="working directory for the binary (default: derived from seg_dir)",
)
@click.option("--seg-dir", default=None, help="override [segmentation] seg_dir (-seg_dir)")
@click.option("--seg-name", default=None, help="override [segmentation] seg_name (-seg_name)")
@click.option("--out-dir", default=None, help="override [output] outdir (-out_dir)")
@click.option("--out-name", default=None, help="override [output] name (-out_name)")
def run(
    parfile: Path,
    binary: Path | None,
    cwd: Path | None,
    seg_dir: str | None,
    seg_name: str | None,
    out_dir: str | None,
    out_name: str | None,
) -> None:
    """Run meshtools3d against a parameter file."""
    overrides = MeshingOverrides(
        seg_dir=_expand(seg_dir),
        seg_name=seg_name,
        out_dir=_expand(out_dir),
        out_name=out_name,
    )
    job = MeshingJob.from_parfile(parfile)
    runner = MeshtoolsRunner(binary_path=binary)
    result = runner.run(job, cwd=cwd, overrides=overrides)
    _echo_result("meshtools3d", result)


@cli.command("laplace")
@click.option("--mesh-dir", required=True, help="directory containing the CARP mesh (-mesh_dir)")
@click.option("--mesh-name", required=True, help="CARP mesh basename (-mesh_name)")
@click.option("--out-dir", required=True, help="output directory (-out_dir)")
@click.option("--out-name", required=True, help="output basename (-out_name)")
@click.option(
    "--zero-bc",
    "zero_bc",
    multiple=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="vtx node-set assigned value 0.0 (--zero-bc); repeatable",
)
@click.option(
    "--one-bc",
    "one_bc",
    multiple=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="vtx node-set assigned value 1.0 (--one-bc); repeatable",
)
@click.option(
    "-f",
    "--parfile",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="optional GetPot file for [laplacesolver] params",
)
@click.option(
    "--binary",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="explicit binary path; otherwise resolved via pycemrg.AssetManager",
)
@click.option(
    "--cwd",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="working directory for the binary (default: derived from mesh_dir)",
)
@click.option("--vtk", is_flag=True, help="write VTK output (--vtk)")
@click.option("--vtk-binary", is_flag=True, help="binary VTK; requires --vtk (--vtk-binary)")
@click.option("--potential", is_flag=True, help="write potential output (--potential)")
@click.option("--no-thickness", is_flag=True, help="solve only, skip thickness (--no-thickness)")
@click.option("--swap-regions", is_flag=True, help="swap endo/epi direction (--swap-regions)")
@click.option(
    "--thickness-algo",
    type=int,
    default=None,
    help="thickness algorithm: 1=Bishop, 2=Corrado (--thickness-algorithm)",
)
@click.option("--solver-verbose", is_flag=True, help="verbose solver output (--verbose)")
def laplace(
    mesh_dir: str,
    mesh_name: str,
    out_dir: str,
    out_name: str,
    zero_bc: tuple[Path, ...],
    one_bc: tuple[Path, ...],
    parfile: Path | None,
    binary: Path | None,
    cwd: Path | None,
    vtk: bool,
    vtk_binary: bool,
    potential: bool,
    no_thickness: bool,
    swap_regions: bool,
    thickness_algo: int | None,
    solver_verbose: bool,
) -> None:
    """Run laplace_solver on an existing CARP mesh with boundary conditions."""
    job = LaplaceSolveJob.create(
        mesh_dir=str(Path(mesh_dir).expanduser()),
        mesh_name=mesh_name,
        output_dir=str(Path(out_dir).expanduser()),
        output_name=out_name,
        zero_bc=zero_bc,
        one_bc=one_bc,
        parfile_path=parfile,
    )
    options = LaplaceSolveOptions(
        no_thickness=no_thickness,
        swap_regions=swap_regions,
        thickness_algorithm=thickness_algo,
        vtk=vtk,
        vtk_binary=vtk_binary,
        potential=potential,
        verbose=solver_verbose,
    )
    runner = LaplaceRunner(binary_path=binary)
    result = runner.run(job, options=options, cwd=cwd)
    _echo_result("laplace_solver", result)


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``pycemrg-meshing`` console script."""
    cli.main(args=argv, prog_name="pycemrg-meshing")


if __name__ == "__main__":  # pragma: no cover
    main()
