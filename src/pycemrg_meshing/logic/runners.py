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
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar, Union

from pycemrg.models.manager import ModelManager
from pycemrg.system import CommandRunner

from pycemrg_meshing.tools.binaries import (
    BinaryName,
    bundled_manifest_path,
    model_name_for,
)
from pycemrg_meshing.tools.parameters import MeshingOverrides, MeshingParameters

PathLike = Union[str, Path]


class MacOSGatekeeperError(RuntimeError):
    """Raised on macOS when a ``ModelManager``-downloaded binary cannot be run.

    Apple Silicon SIGKILLs the prebuilt arm64 binaries until they are ad-hoc
    signed, so we refuse to invoke a freshly downloaded build. The message
    tells the user exactly how to sign the extracted install and re-invoke with
    an explicit ``--binary`` / ``binary_path=`` override (which skips
    ``ModelManager`` entirely). See ``docs/macos_gatekeeper.md``.
    """

    def __init__(self, binary: Path) -> None:
        self.binary = binary
        self.install_root = binary.parent.parent
        super().__init__(self._build_message(binary, self.install_root))

    @staticmethod
    def _build_message(binary: Path, root: Path) -> str:
        return (
            f"meshtools3d was downloaded to:\n"
            f"    {root}\n"
            f"but macOS will SIGKILL it until it is ad-hoc signed. Sign it once:\n\n"
            f'    xattr -dr com.apple.quarantine "{root}"\n'
            f'    for f in "{root}"/lib/*.dylib; do [ -L "$f" ] && continue; '
            f'codesign --force --sign - "$f"; done\n'
            f'    for b in "{root}"/bin/*; do codesign --force --sign - "$b"; done\n\n'
            f"Then re-run with the signed binary, e.g.:\n"
            f'    pycemrg-meshing run PARFILE --binary "{binary}"\n'
            f"or in Python:\n"
            f'    MeshtoolsRunner(binary_path="{binary}")\n\n'
            f"See docs/macos_gatekeeper.md for details."
        )


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
        binary = Path(mm.get_model_path(model_name_for(self.binary_name)))
        # macOS Gatekeeper SIGKILLs the unsigned downloaded arm64 build. The
        # download path is intentionally a stop, not a run: route the user to
        # sign the install once and pass it back via an explicit override.
        if sys.platform == "darwin":
            raise MacOSGatekeeperError(binary)
        return binary

    # --------------------------------------------------------------- Execution

    def run(
        self,
        par_path: PathLike,
        *,
        cwd: PathLike | None = None,
        overrides: MeshingOverrides | None = None,
        extra_args: Sequence[str] | None = None,
    ) -> Path:
        """Invoke the binary against the given parameter file.

        ``overrides`` are passed to the binary as its native ``-seg_dir`` /
        ``-seg_name`` / ``-out_dir`` / ``-out_name`` flags, which overwrite the
        matching ``.par`` values — the documented way to reuse one parameter
        file across runs. The ``.par`` file itself is never modified.

        The binary resolves the relative paths (the ``segmentation`` input and
        the ``[output] outdir``) against its working directory, so the chosen
        ``cwd`` decides where files are read and written. Resolution order, using
        the *effective* ``seg_dir`` (override if given, else the ``.par`` value):

        - an explicit ``cwd`` always wins;
        - otherwise, if the effective ``seg_dir`` is absolute, it becomes the
          ``cwd`` so outputs co-locate with the segmentation data;
        - otherwise the parent of ``par_path`` is used, which is the only
          stable anchor a relative ``seg_dir`` / ``outdir`` can mean.

        Returns the resolved effective ``out_dir``, computed against the same
        ``cwd`` so the reported path matches where the binary actually wrote.
        """
        par_path = Path(par_path).expanduser().resolve()
        if not par_path.is_file():
            raise FileNotFoundError(f"parameter file not found: {par_path}")

        run_cwd = self._resolve_cwd(par_path, cwd, overrides)

        binary = self.resolve_binary()
        env = self._library_env(binary)
        # Both meshtools3d and laplace_solver take the parameter file via the
        # ``-f <data_file>`` flag, not positionally (v2.0.0 CLI). Passing it
        # positionally is silently ignored and the binary falls back to its
        # built-in defaults (e.g. looking for ``./image.inr``).
        cmd: list[str] = [str(binary), "-f", str(par_path)]
        if overrides is not None:
            cmd.extend(overrides.as_cli_args())
        if extra_args:
            cmd.extend(extra_args)

        self._runner.run(cmd, cwd=run_cwd, env=env)
        return self._resolve_outdir(par_path, run_cwd, overrides)

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
    def _resolve_cwd(
        par_path: Path, cwd: PathLike | None, overrides: MeshingOverrides | None
    ) -> Path:
        """Pick the working directory the binary runs in.

        See :meth:`run` for the resolution order. The binary applies the
        effective ``seg_dir`` on top of this directory, so an explicit ``cwd``
        wins, an absolute effective ``seg_dir`` co-locates outputs with the
        data, and a relative one falls back to the par file's parent (the only
        stable anchor, and the one cwd that never double-applies ``seg_dir``).
        """
        if cwd is not None:
            return Path(cwd).expanduser().resolve()
        seg_dir_value = overrides.seg_dir if overrides and overrides.seg_dir else None
        if seg_dir_value is None:
            params = MeshingParameters(config_file=par_path)
            seg_dir_value = params.get("segmentation", "seg_dir")
        seg_dir = Path(seg_dir_value).expanduser()
        if seg_dir.is_absolute():
            return seg_dir.resolve()
        return par_path.parent

    @staticmethod
    def _resolve_outdir(
        par_path: Path, run_cwd: Path, overrides: MeshingOverrides | None
    ) -> Path:
        out_dir_value = overrides.out_dir if overrides and overrides.out_dir else None
        if out_dir_value is None:
            params = MeshingParameters(config_file=par_path)
            out_dir_value = params.get("output", "outdir")
        outdir = Path(out_dir_value).expanduser()
        if not outdir.is_absolute():
            outdir = (run_cwd / outdir).resolve()
        return outdir


class MeshtoolsRunner(_BinaryRunner):
    """Run the ``meshtools3d`` mesh generator."""

    binary_name: ClassVar[BinaryName] = "meshtools3d"


class LaplaceRunner(_BinaryRunner):
    """Run the standalone ``laplace_solver``."""

    binary_name: ClassVar[BinaryName] = "laplace_solver"


__all__ = ["MeshtoolsRunner", "LaplaceRunner", "MacOSGatekeeperError"]
