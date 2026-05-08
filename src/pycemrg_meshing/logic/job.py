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

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Union

from pycemrg_meshing.tools.parameters import MeshingParameters

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
    ) -> "MeshingJob":
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
    ) -> "MeshingJob":
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

    def expected_outputs(self, params: MeshingParameters) -> list[Path]:
        """Files this job is expected to produce, given the parameters' flags.

        Only files whose corresponding ``out_*`` flag is ``"1"`` are
        included. Conservative: covers the well-known formats only
        (CARP ASCII triplet, VTK ASCII, MEDIT). Binary CARP/VTK and the
        Laplace potential field are not enumerated here — extend if/when
        the upstream filenames are documented.
        """
        outputs: list[Path] = []
        base = self.output_dir / self.output_name

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


__all__ = ["MeshingJob"]
