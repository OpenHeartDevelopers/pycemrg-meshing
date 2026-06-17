"""Typed results returned by the runners.

This module is **orchestration**: a result describes what a run produced on the
filesystem, so an orchestrator can consume the outputs without reconstructing
the binary's naming convention. The runners verify existence via
``CommandRunner(expected_outputs=...)`` (fail-fast: a missing file raises before
a result is ever built), so every path listed here is one the run was asked to
produce; ``size`` is the on-disk byte size at collection time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OutputFile:
    """A single produced file and its on-disk size in bytes."""

    path: Path
    size: int


@dataclass(frozen=True)
class MeshingResult:
    """Outcome of a ``meshtools3d`` run.

    ``outdir`` is the effective output directory (override-or-``.par``, resolved
    against the working directory the binary actually ran in). ``outputs`` are
    the produced files whose ``[output] out_*`` flag was enabled. ``stdout`` is
    the binary's captured standard output.
    """

    outdir: Path
    outputs: list[OutputFile]
    stdout: str


@dataclass(frozen=True)
class LaplaceSolveResult:
    """Outcome of a ``laplace_solver`` run.

    Same shape as :class:`MeshingResult`, but ``outputs`` are derived from the
    :class:`~pycemrg_meshing.tools.parameters.LaplaceSolveOptions` flags rather
    than a ``.par`` ``[output]`` section.
    """

    outdir: Path
    outputs: list[OutputFile]
    stdout: str


__all__ = ["OutputFile", "MeshingResult", "LaplaceSolveResult"]
