"""Console entry point for ``pycemrg-meshing``.

Subcommands:

* ``init-par``  — write a default ``.par`` file, optionally with overrides.
* ``run``       — execute ``meshtools3d`` against a parameter file.
* ``laplace``   — execute ``laplace_solver`` against a parameter file.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from pycemrg_meshing.logic.runners import LaplaceRunner, MeshtoolsRunner
from pycemrg_meshing.tools.parameters import MeshingParameters


# ----------------------------------------------------------------- Subcommands


def _cmd_init_par(args: argparse.Namespace) -> int:
    params = MeshingParameters()
    for kv in args.set or []:
        section, key, value = _parse_set(kv)
        params.set(section, key, value)
    out = params.save(args.output)
    print(f"wrote {out}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    runner = MeshtoolsRunner(binary_path=args.binary)
    outdir = runner.run(args.parfile, cwd=args.cwd)
    print(f"meshtools3d completed; outdir={outdir}")
    return 0


def _cmd_laplace(args: argparse.Namespace) -> int:
    runner = LaplaceRunner(binary_path=args.binary)
    outdir = runner.run(args.parfile, cwd=args.cwd)
    print(f"laplace_solver completed; outdir={outdir}")
    return 0


# ------------------------------------------------------------------- Helpers


def _parse_set(token: str) -> tuple[str, str, str]:
    """Parse a ``--set SECTION.KEY=VALUE`` token."""
    section_key, sep_eq, value = token.partition("=")
    if not sep_eq:
        raise SystemExit(f"--set expects SECTION.KEY=VALUE, got: {token!r}")
    section, sep_dot, key = section_key.partition(".")
    if not sep_dot or not section or not key:
        raise SystemExit(f"--set expects SECTION.KEY=VALUE, got: {token!r}")
    return section, key, value


# ----------------------------------------------------------------- Top-level


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pycemrg-meshing",
        description="Author and execute meshtools3d parameter-file workflows.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="enable INFO logging"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser(
        "init-par", help="write a default meshtools3d parameter file"
    )
    init.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("heart.par"),
        help="path for the generated parameter file (default: heart.par)",
    )
    init.add_argument(
        "--set",
        action="append",
        metavar="SECTION.KEY=VALUE",
        help="override a parameter; may be passed multiple times",
    )
    init.set_defaults(func=_cmd_init_par)

    run = sub.add_parser("run", help="run meshtools3d against a parameter file")
    _add_run_args(run)
    run.set_defaults(func=_cmd_run)

    lap = sub.add_parser(
        "laplace", help="run laplace_solver against a parameter file"
    )
    _add_run_args(lap)
    lap.set_defaults(func=_cmd_laplace)

    return parser


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("parfile", type=Path, help="path to the meshtools3d .par file")
    p.add_argument(
        "--binary",
        type=Path,
        default=None,
        help="explicit binary path; otherwise resolved via ModelManager",
    )
    p.add_argument(
        "--cwd",
        type=Path,
        default=None,
        help="working directory for the binary (default: current dir)",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
