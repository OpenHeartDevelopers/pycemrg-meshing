"""Runners that orchestrate process invocation of the meshtools3d binaries.

This module is **orchestration**: it touches the filesystem, spawns processes,
and composes environment variables. Stateless transformation lives in
``pycemrg_meshing.tools``.

Both runners share a small base that:

1. Resolves the binary — either an explicit ``binary_path`` override, or via
   ``pycemrg.ModelManager.get_model_path`` against the bundled ``models.yaml``.
2. Injects the platform-appropriate library-path env var
   (``DYLD_LIBRARY_PATH`` on macOS, ``LD_LIBRARY_PATH`` on Linux) so the
   bundled ``lib/`` ships its dylibs alongside ``bin/``.
3. Reads ``[output] outdir`` from the supplied ``.par`` file and returns the
   resolved absolute path on success.

Per the v0.1 ticket: no ``MESHTOOLS3D_BIN`` env var, no ``shutil.which``
fallback. Discovery is exactly: explicit override → ModelManager.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import ClassVar, Sequence, Union

from pycemrg.models.manager import ModelManager
from pycemrg.system import CommandRunner

from pycemrg_meshing.tools.binaries import (
    BinaryName,
    bundled_manifest_path,
    model_name_for,
)
from pycemrg_meshing.tools.parameters import MeshingParameters

PathLike = Union[str, Path]


class _BinaryRunner:
    """Shared logic for the meshtools3d / laplace_solver runners."""

    binary_name: ClassVar[BinaryName]

    def __init__(
        self,
        binary_path: PathLike | None = None,
        *,
        model_manager: ModelManager | None = None,
        runner: CommandRunner | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._binary_path: Path | None = (
            Path(binary_path).expanduser().resolve()
            if binary_path is not None
            else None
        )
        self._model_manager = model_manager
        self._runner = runner if runner is not None else CommandRunner(logger=logger)

    # -------------------------------------------------------------- Discovery

    def resolve_binary(self) -> Path:
        """Return the absolute path to the binary this runner will invoke."""
        if self._binary_path is not None:
            if not self._binary_path.is_file():
                raise FileNotFoundError(
                    f"binary_path does not exist: {self._binary_path}"
                )
            return self._binary_path
        mm = self._model_manager or ModelManager(manifest_path=bundled_manifest_path())
        return Path(mm.get_model_path(model_name_for(self.binary_name)))

    # --------------------------------------------------------------- Execution

    def run(
        self,
        par_path: PathLike,
        *,
        cwd: PathLike | None = None,
        extra_args: Sequence[str] | None = None,
    ) -> Path:
        """Invoke the binary against the given parameter file.

        Returns the resolved ``[output] outdir`` from the parameter file. If
        ``outdir`` is relative, it is resolved against the parent of
        ``par_path`` (matching the convention CLI users expect).
        """
        par_path = Path(par_path).expanduser().resolve()
        if not par_path.is_file():
            raise FileNotFoundError(f"parameter file not found: {par_path}")

        binary = self.resolve_binary()
        env = self._library_env(binary)
        cmd: list[str] = [str(binary)]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(str(par_path))

        self._runner.run(
            cmd,
            cwd=Path(cwd).expanduser().resolve() if cwd is not None else None,
            env=env,
        )
        return self._resolve_outdir(par_path)

    # ----------------------------------------------------------------- Helpers

    @staticmethod
    def _library_env(binary: Path) -> dict[str, str]:
        """Return ``os.environ`` extended with the bundled ``lib/`` dir.

        ``CommandRunner.run(env=...)`` *replaces* the entire environment, so
        we always start from ``os.environ.copy()``.
        """
        env = os.environ.copy()
        # Bundled tarballs lay out as <root>/bin/<binary> + <root>/lib/*.
        lib_dir = binary.parent.parent / "lib"
        if lib_dir.is_dir():
            var = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
            existing = env.get(var, "")
            env[var] = (
                f"{lib_dir}{os.pathsep}{existing}" if existing else str(lib_dir)
            )
        return env

    @staticmethod
    def _resolve_outdir(par_path: Path) -> Path:
        params = MeshingParameters(config_file=par_path)
        outdir = Path(params.get("output", "outdir"))
        if not outdir.is_absolute():
            outdir = (par_path.parent / outdir).resolve()
        return outdir


class MeshtoolsRunner(_BinaryRunner):
    """Run the ``meshtools3d`` mesh generator."""

    binary_name: ClassVar[BinaryName] = "meshtools3d"


class LaplaceRunner(_BinaryRunner):
    """Run the standalone ``laplace_solver``."""

    binary_name: ClassVar[BinaryName] = "laplace_solver"


__all__ = ["MeshtoolsRunner", "LaplaceRunner"]
