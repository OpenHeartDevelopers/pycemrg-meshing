"""High-level job contract for a meshtools3d run.

Bundles the four paths an orchestrator nearly always needs together:
the segmentation, the output directory, the output basename (no extension),
and the parameter-file path. Provides helpers to render the matching
``.par`` file and to enumerate the output files the run will produce, given
the ``[output] out_*`` flags.

This module is **orchestration**: it touches the filesystem (``write_parfile``)
and constructs paths from conventions (``expected_outputs``). The pure
schema lives in ``pycemrg_meshing.tools.parameters``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Union

from pycemrg_meshing.tools.parameters import LaplaceSolveOptions, MeshingParameters

PathLike = Union[str, Path]
Overrides = Mapping[str, Mapping[str, object]]


@dataclass(frozen=True)
class MeshingJob:
    """Description of a single meshtools3d / laplace_solver run.

    All paths are stored as ``Path`` objects but accept ``str`` at
    construction via ``MeshingJob.create``. ``output_name`` is the basename
    without extension (matches ``[output] name`` in the parameter file).
    """

    segmentation_path: Path
    output_dir: Path
    output_name: str
    parfile_path: Path

    # ------------------------------------------------------------- Construction

    @classmethod
    def create(
        cls,
        segmentation_path: PathLike,
        output_dir: PathLike,
        output_name: str,
        parfile_path: PathLike,
    ) -> MeshingJob:
        """Build a job, normalising ``str`` paths to ``Path`` and expanding ``~``."""
        return cls(
            segmentation_path=Path(segmentation_path).expanduser(),
            output_dir=Path(output_dir).expanduser(),
            output_name=output_name,
            parfile_path=Path(parfile_path).expanduser(),
        )

    @classmethod
    def from_segmentation(
        cls,
        segmentation_path: PathLike,
        output_dir: PathLike,
        output_name: str,
        parfile_path: PathLike,
        *,
        converter: Optional[Callable[[Path, Path], Path]] = None,
    ) -> MeshingJob:
        """Build a job from any segmentation, optionally converting to ``.inr``.

        If ``segmentation_path`` does not end in ``.inr`` and ``converter`` is
        supplied, the converter is called as ``converter(src, dst)`` and is
        expected to return the path to the produced ``.inr`` file. The
        converted file is placed alongside ``parfile_path``.

        ``converter`` is dependency-injected: this package never imports image
        I/O libraries. Pass e.g. ``pycemrg_image_analysis.to_inr``.
        """
        seg = Path(segmentation_path).expanduser()
        if seg.suffix.lower() != ".inr":
            if converter is None:
                raise ValueError(
                    f"segmentation is not .inr ({seg.suffix!r}) and no "
                    f"converter was supplied; pass converter=... to convert."
                )
            target = Path(parfile_path).expanduser().parent / (seg.stem + ".inr")
            seg = Path(converter(seg, target))
        return cls.create(seg, output_dir, output_name, parfile_path)

    @classmethod
    def from_parfile(cls, parfile_path: PathLike) -> MeshingJob:
        """Build a job by reading an existing ``.par`` file.

        ``[segmentation] seg_dir`` + ``seg_name`` are joined into
        ``segmentation_path``; ``[output] outdir`` / ``name`` become
        ``output_dir`` / ``output_name``. Useful for the CLI, which hands the
        runner a parfile the user already authored.
        """
        path = Path(parfile_path).expanduser()
        params = MeshingParameters(config_file=path)
        seg_dir = params.get("segmentation", "seg_dir")
        seg_name = params.get("segmentation", "seg_name")
        return cls.create(
            segmentation_path=Path(seg_dir) / seg_name,
            output_dir=params.get("output", "outdir"),
            output_name=params.get("output", "name"),
            parfile_path=path,
        )

    # ------------------------------------------------------------- Parameters

    def to_parameters(
        self,
        *,
        base: MeshingParameters | None = None,
        overrides: Overrides | None = None,
    ) -> MeshingParameters:
        """Return ``MeshingParameters`` populated from this job, plus overrides.

        ``segmentation_path`` is split into ``[segmentation] seg_dir`` +
        ``seg_name``. ``output_dir`` and ``output_name`` populate
        ``[output] outdir`` and ``[output] name``. Caller-supplied
        ``overrides`` win over both.
        """
        params = base if base is not None else MeshingParameters()
        params.set("segmentation", "seg_dir", str(self.segmentation_path.parent))
        params.set("segmentation", "seg_name", self.segmentation_path.name)
        params.set("output", "outdir", str(self.output_dir))
        params.set("output", "name", self.output_name)
        for section, kvs in (overrides or {}).items():
            for key, value in kvs.items():
                params.set(section, key, value)
        return params

    def write_parfile(
        self,
        *,
        base: MeshingParameters | None = None,
        overrides: Overrides | None = None,
    ) -> Path:
        """Render ``to_parameters`` to ``self.parfile_path`` and return it."""
        params = self.to_parameters(base=base, overrides=overrides)
        return params.save(self.parfile_path)

    # --------------------------------------------------------- Output catalog

    def expected_outputs(
        self,
        params: MeshingParameters,
        *,
        output_dir: PathLike | None = None,
        output_name: str | None = None,
    ) -> list[Path]:
        """Files this job is expected to produce, given the parameters' flags.

        Only files whose corresponding ``out_*`` flag is ``"1"`` are
        included. Conservative: covers the well-known formats only
        (CARP ASCII triplet, VTK ASCII, MEDIT). Binary CARP/VTK and the
        Laplace potential field are not enumerated here — extend if/when
        the upstream filenames are documented.

        ``output_dir`` / ``output_name`` override this job's own values so the
        runner can re-base the prediction onto the *effective* output location
        when a :class:`MeshingOverrides` redirects it. Defaults reproduce the
        job's own paths.
        """
        outputs: list[Path] = []
        base_dir = Path(output_dir) if output_dir is not None else self.output_dir
        base = base_dir / (output_name if output_name is not None else self.output_name)

        def flag(key: str) -> bool:
            return params.get("output", key) == "1"

        if flag("out_carp"):
            outputs.extend(
                [base.with_suffix(".elem"), base.with_suffix(".pts"), base.with_suffix(".lon")]
            )
        if flag("out_vtk"):
            outputs.append(base.with_suffix(".vtk"))
        if flag("out_medit"):
            outputs.append(base.with_suffix(".mesh"))
        return outputs


@dataclass(frozen=True)
class LaplaceSolveJob:
    """Description of a single ``laplace_solver`` run.

    Unlike :class:`MeshingJob`, the input is an *existing CARP mesh*
    (``mesh_dir`` + ``mesh_name``), and the boundary conditions
    (``zero_bc`` / ``one_bc`` vtx node-sets) are first-class inputs with no
    analogue in meshtools3d. ``parfile_path`` is optional: the ``-f`` file only
    carries ``[laplacesolver]`` tolerances, so a run can proceed without one.

    Because there is no ``.par`` carrying the mesh / output / BC paths, the job
    renders them itself via :meth:`as_cli_args` — that is the *only* place those
    flags come from.
    """

    mesh_dir: Path
    mesh_name: str
    output_dir: Path
    output_name: str
    zero_bc: tuple[Path, ...] = ()
    one_bc: tuple[Path, ...] = ()
    parfile_path: Optional[Path] = None

    @classmethod
    def create(
        cls,
        mesh_dir: PathLike,
        mesh_name: str,
        output_dir: PathLike,
        output_name: str,
        *,
        zero_bc: tuple[PathLike, ...] = (),
        one_bc: tuple[PathLike, ...] = (),
        parfile_path: Optional[PathLike] = None,
    ) -> LaplaceSolveJob:
        """Build a job, normalising ``str`` paths to ``Path`` and expanding ``~``."""
        return cls(
            mesh_dir=Path(mesh_dir).expanduser(),
            mesh_name=mesh_name,
            output_dir=Path(output_dir).expanduser(),
            output_name=output_name,
            zero_bc=tuple(Path(p).expanduser() for p in zero_bc),
            one_bc=tuple(Path(p).expanduser() for p in one_bc),
            parfile_path=Path(parfile_path).expanduser() if parfile_path is not None else None,
        )

    def as_cli_args(self) -> list[str]:
        """Render the mesh / output / BC flags this run requires.

        These are mandatory inputs (the binary has no ``.par`` fallback for
        them), so they are always emitted. BC flags repeat, one per node-set.
        """
        args: list[str] = [
            "-mesh_dir", str(self.mesh_dir),
            "-mesh_name", self.mesh_name,
            "-out_dir", str(self.output_dir),
            "-out_name", self.output_name,
        ]
        for vtx in self.zero_bc:
            args.extend(["--zero-bc", str(vtx)])
        for vtx in self.one_bc:
            args.extend(["--one-bc", str(vtx)])
        return args

    def expected_outputs(
        self,
        options: LaplaceSolveOptions | None = None,
        *,
        output_dir: PathLike | None = None,
        output_name: str | None = None,
    ) -> list[Path]:
        """Files this run is expected to produce, given the options' flags.

        Enumerated from ``m3d_api.md`` §laplace_solver "Expected outputs":

        - thickness evaluation (ON by default; off with ``no_thickness``) emits
          ``<name>.grad`` / ``.cpts`` / ``.tris``;
        - ``vtk`` emits ``<name>.vtk``;
        - ``potential`` *without* ``vtk`` emits ``<name>_potential.dat``;
        - thickness *without* ``vtk`` emits ``<name>_thickness.dat``.

        ``output_dir`` / ``output_name`` override this job's own values so the
        runner can re-base onto the effective output location.
        """
        base_dir = Path(output_dir) if output_dir is not None else self.output_dir
        name = output_name if output_name is not None else self.output_name
        base = base_dir / name

        thickness_ran = options is None or not options.no_thickness
        vtk = options is not None and options.vtk
        potential = options is not None and options.potential

        outputs: list[Path] = []
        if thickness_ran:
            outputs.extend(
                [base.with_suffix(".grad"), base.with_suffix(".cpts"), base.with_suffix(".tris")]
            )
        if vtk:
            outputs.append(base.with_suffix(".vtk"))
        if potential and not vtk:
            outputs.append(base.with_name(f"{name}_potential.dat"))
        if thickness_ran and not vtk:
            outputs.append(base.with_name(f"{name}_thickness.dat"))
        return outputs


__all__ = ["MeshingJob", "LaplaceSolveJob"]
