"""Parameter-file authoring for meshtools3d.

Vendored from ``cemrg_heartbuilder.MeshingParameters`` per the v0.1 ticket
scope — no dependency on ``cemrg_heartbuilder``. The schema (sections, keys,
defaults) mirrors ``m3d_python_params.md`` §1/§3 verbatim.

Stateless w.r.t. its environment: state is the in-memory ``ConfigParser`` only.
Same input always produces the same on-disk output.
"""

from __future__ import annotations

import configparser
import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Union

PathLike = Union[str, Path]
ParamDict = Dict[str, Dict[str, str]]


@dataclass(frozen=True)
class MeshingOverrides:
    """Run-time overrides for meshtools3d's path parameters.

    Each field, when not ``None``, is passed to the ``meshtools3d`` binary as
    its native override flag (``-seg_dir`` etc.), which the binary documents as
    *overwriting* the value in the ``.par`` data file — the supported way to
    reuse one parameter file across many runs. ``None`` means "use the value in
    the ``.par`` file". This is a stateless carrier: paths are stored verbatim,
    not expanded or resolved (the orchestration layer decides that).
    """

    seg_dir: str | None = None
    seg_name: str | None = None
    out_dir: str | None = None
    out_name: str | None = None
    thickness_algorithm: int | None = None
    verbose: bool = False

    def as_cli_args(self) -> list[str]:
        """Return the ``-flag value`` tokens for the fields that are set."""
        mapping = {
            "-seg_dir": self.seg_dir,
            "-seg_name": self.seg_name,
            "-out_dir": self.out_dir,
            "-out_name": self.out_name,
        }
        args: list[str] = []
        for flag, value in mapping.items():
            if value is not None:
                args.extend([flag, value])
        if self.thickness_algorithm is not None:
            args.extend(["--thickness-algorithm", str(self.thickness_algorithm)])
        if self.verbose:
            args.append("--verbose")
        return args


@dataclass(frozen=True)
class LaplaceSolveOptions:
    """Behavioural toggles for the ``laplace_solver`` binary.

    This is the HOW, not the WHAT: the mesh, output, and boundary-condition
    *paths* live on :class:`pycemrg_meshing.logic.job.LaplaceSolveJob` and are
    rendered there. Unlike ``meshtools3d``, ``laplace_solver`` has no ``.par``
    carrying those paths (the ``-f`` file holds only ``[laplacesolver]``
    tolerances), so there is nothing to *override* — only solver behaviour to
    select. Stateless carrier: same input always renders the same flags.
    """

    no_thickness: bool = False
    swap_regions: bool = False
    thickness_algorithm: int | None = None
    vtk: bool = False
    vtk_binary: bool = False
    potential: bool = False
    verbose: bool = False

    def as_cli_args(self) -> list[str]:
        """Return the flag tokens for the toggles that are enabled."""
        args: list[str] = []
        if self.no_thickness:
            args.append("--no-thickness")
        if self.swap_regions:
            args.append("--swap-regions")
        if self.thickness_algorithm is not None:
            args.extend(["--thickness-algorithm", str(self.thickness_algorithm)])
        if self.vtk:
            args.append("--vtk")
        if self.vtk_binary:
            args.append("--vtk-binary")
        if self.potential:
            args.append("--potential")
        if self.verbose:
            args.append("--verbose")
        return args


# Defaults table — mirrors m3d_python_params.md §1 / §3.
# All values are strings: the C++ side parses them. Case must be preserved
# (rescaleFactor, dimKrilovSp) — see ``optionxform = str`` below.
DEFAULT_VALUES: ParamDict = {
    "segmentation": {
        "seg_dir": "./",
        "seg_name": "seg_final_smooth_corrected.inr",
        "mesh_from_segmentation": "1",
        "boundary_relabeling": "0",
    },
    "meshing": {
        "facet_angle": "30",
        "facet_size": "0.8",
        "facet_distance": "4",
        "cell_rad_edge_ratio": "2.0",
        "cell_size": "0.8",
        "rescaleFactor": "1000",
    },
    "laplacesolver": {
        "abs_toll": "1e-6",
        "rel_toll": "1e-6",
        "itr_max": "700",
        "dimKrilovSp": "500",
        "verbose": "1",
    },
    "others": {
        "eval_thickness": "0",
    },
    "output": {
        "outdir": "./myocardium_OUT",
        "name": "heart_mesh",
        "out_medit": "0",
        "out_carp": "1",
        "out_carp_binary": "0",
        "out_vtk": "1",
        "out_vtk_binary": "0",
        "out_potential": "0",
    },
}


# Extended schema — m3d_api.md §2.6. These keys are VALID (set/get accept them,
# get returns these defaults when unset) but are NOT seeded into the config or
# written by ``save`` unless explicitly set. This mirrors the reference
# ``parfile_builder``, which emits §2.1–§2.5 only and leaves §2.6 to ``--set``
# or hand-editing. Case matters: ``readTheMesh`` is camelCase; ``swapregions`` /
# ``thickalgo`` are lowercase (see ``optionxform = str``).
EXTENDED_DEFAULTS: ParamDict = {
    "meshing": {
        "readTheMesh": "0",
        "mesh_dir": "./",
        "mesh_name": "mesh",
    },
    "others": {
        "swapregions": "0",
        "thickalgo": "1",
    },
    "output": {
        "debug_output": "0",
        "debug_frequency": "100",
    },
}


def _valid_options(section: str) -> set[str]:
    """All accepted keys for a section: core (§2.1–§2.5) ∪ extended (§2.6)."""
    return set(DEFAULT_VALUES.get(section, {})) | set(EXTENDED_DEFAULTS.get(section, {}))


def _require_valid(section: str, option: str) -> None:
    """Raise ``KeyError`` unless ``section``/``option`` is in the union schema."""
    if section not in DEFAULT_VALUES:
        raise KeyError(f"unknown section: {section!r}")
    if option not in _valid_options(section):
        raise KeyError(f"unknown key: [{section}] {option!r}")


class MeshingParameters:
    """In-memory representation of a meshtools3d ``.par`` file.

    Construct with defaults; optionally seed from an existing file. ``set``
    validates that both the section and the key exist in the schema — the C++
    side does not fill in missing keys, so silent typos are a real risk.
    """

    def __init__(self, config_file: PathLike | None = None) -> None:
        self._cfg = self._fresh_config()
        if config_file is not None:
            self.load(config_file)

    # ------------------------------------------------------------------ I/O

    def load(self, path: PathLike) -> None:
        """Read an existing ``.par`` / ``.ini`` file into this instance.

        Validates that no unknown section or key sneaks in via the file.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"parameter file not found: {path}")
        cfg = self._fresh_config_empty()
        with path.open("r") as fh:
            cfg.read_file(fh)
        self._validate_against_schema(cfg, source=str(path))
        # Merge over defaults so the result always has every key.
        merged = self._fresh_config()
        for section in cfg.sections():
            for key, value in cfg.items(section):
                merged[section][key] = value
        self._cfg = merged

    def save(self, path: PathLike) -> Path:
        """Write the current state to disk. Returns the resolved path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as fh:
            self._cfg.write(fh)
        return path

    # -------------------------------------------------------------- Mutation

    def set(self, section: str, option: str, value: object) -> None:
        """Set one key. Raises ``KeyError`` if section or option is unknown.

        Validates against the union of the core (§2.1–§2.5) and extended (§2.6)
        schemas. Setting an extended key writes it into the config, so it will
        then be emitted by :meth:`save`.
        """
        _require_valid(section, option)
        self._cfg[section][option] = str(value)

    def get(self, section: str, option: str) -> str:
        """Read one value as string. Raises ``KeyError`` on unknown name.

        An extended (§2.6) key that has not been set is not present in the
        config; its documented default from ``EXTENDED_DEFAULTS`` is returned so
        ``get`` stays total for every valid key.
        """
        _require_valid(section, option)
        cfg_section = self._cfg[section]
        if option in cfg_section:
            return cfg_section[option]
        return EXTENDED_DEFAULTS[section][option]

    def reset_to_defaults(self) -> None:
        """Restore the schema-default values."""
        self._cfg = self._fresh_config()

    # ----------------------------------------------------------- Inspection

    def create_dict(self) -> ParamDict:
        """Snapshot to a plain nested ``dict[str, dict[str, str]]``."""
        return {
            section: dict(self._cfg.items(section))
            for section in self._cfg.sections()
        }

    # -------------------------------------------------------------- Helpers

    @staticmethod
    def _fresh_config_empty() -> configparser.ConfigParser:
        cfg = configparser.ConfigParser()
        # Preserve case (rescaleFactor, dimKrilovSp).
        cfg.optionxform = str  # type: ignore[assignment]
        return cfg

    @classmethod
    def _fresh_config(cls) -> configparser.ConfigParser:
        cfg = cls._fresh_config_empty()
        cfg.read_dict(copy.deepcopy(DEFAULT_VALUES))
        return cfg

    @staticmethod
    def _validate_against_schema(
        cfg: configparser.ConfigParser, *, source: str
    ) -> None:
        for section in cfg.sections():
            if section not in DEFAULT_VALUES:
                raise KeyError(f"{source}: unknown section {section!r}")
            valid = _valid_options(section)
            for key in cfg[section]:
                if key not in valid:
                    raise KeyError(
                        f"{source}: unknown key [{section}] {key!r}"
                    )

    # --------------------------------------------------------------- Pythonic

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MeshingParameters):
            return NotImplemented
        return self.create_dict() == other.create_dict()

    def __repr__(self) -> str:
        sections = ", ".join(self._cfg.sections())
        return f"MeshingParameters(sections=[{sections}])"


def default_parameters() -> ParamDict:
    """Return a deep copy of the schema defaults — useful for tests."""
    return copy.deepcopy(DEFAULT_VALUES)


__all__ = [
    "MeshingParameters",
    "MeshingOverrides",
    "LaplaceSolveOptions",
    "DEFAULT_VALUES",
    "EXTENDED_DEFAULTS",
    "default_parameters",
    "ParamDict",
]
