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

from pycemrg_meshing.logic.runners import LaplaceRunner, MeshtoolsRunner
from pycemrg_meshing.tools.parameters import MeshingOverrides, MeshingParameters

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
    runner = MeshtoolsRunner(binary_path=binary)
    outdir = runner.run(parfile, cwd=cwd, overrides=overrides)
    click.echo(f"meshtools3d completed; outdir={outdir}")


@cli.command("laplace")
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
def laplace(parfile: Path, binary: Path | None, cwd: Path | None) -> None:
    """Run laplace_solver against a parameter file."""
    runner = LaplaceRunner(binary_path=binary)
    outdir = runner.run(parfile, cwd=cwd)
    click.echo(f"laplace_solver completed; outdir={outdir}")


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ``pycemrg-meshing`` console script."""
    cli.main(args=argv, prog_name="pycemrg-meshing")


if __name__ == "__main__":  # pragma: no cover
    main()
