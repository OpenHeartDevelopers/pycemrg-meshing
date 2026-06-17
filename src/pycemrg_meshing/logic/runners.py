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
from typing import ClassVar, Union, cast

from pycemrg.models.manager import ModelManager
from pycemrg.system import CommandRunner

from pycemrg_meshing.logic.job import LaplaceSolveJob, MeshingJob
from pycemrg_meshing.logic.results import LaplaceSolveResult, MeshingResult, OutputFile
from pycemrg_meshing.tools.binaries import (
    BinaryName,
    bundled_manifest_path,
    model_name_for,
)
from pycemrg_meshing.tools.parameters import (
    LaplaceSolveOptions,
    MeshingOverrides,
    MeshingParameters,
)

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

    # ------------------------------------------------------------ Plumbing

    def _invoke(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        expected_outputs: Sequence[Path],
    ) -> str:
        """Resolve the binary, compose env, run, and return captured stdout.

        ``expected_outputs`` is forwarded to ``CommandRunner.run``, which raises
        ``FileNotFoundError`` post-run if any are missing — fail-fast on a
        silent-success binary. The whole pycemrg suite behaves this way.
        """
        binary = self.resolve_binary()
        env = self._library_env(binary)
        cmd: list[str] = [str(binary), *argv]
        # CommandRunner is untyped (no py.typed); it returns captured stdout.
        return cast(
            str,
            self._runner.run(
                cmd, expected_outputs=list(expected_outputs), cwd=cwd, env=env
            ),
        )

    @staticmethod
    def _collect_outputs(paths: Sequence[Path]) -> list[OutputFile]:
        """Stat each produced path into an :class:`OutputFile` (size in bytes).

        Existence is already guaranteed by ``_invoke``'s fail-fast check on a
        real run; a missing path here (size ``0``) only arises under a test
        double that skips the binary.
        """
        return [
            OutputFile(path=p, size=p.stat().st_size if p.exists() else 0)
            for p in paths
        ]

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
    def _pick_cwd(
        primary_dir_value: str | None,
        *,
        cwd: PathLike | None,
        parfile: Path | None,
    ) -> Path:
        """Pick the working directory the binary runs in.

        The binary resolves its relative input/output paths against this
        directory. ``primary_dir_value`` is the effective primary *input*
        directory (``seg_dir`` for meshtools3d, ``mesh_dir`` for laplace).
        Resolution order:

        - an explicit ``cwd`` always wins;
        - otherwise an *absolute* primary input dir becomes the cwd, so outputs
          co-locate with the data (and the binary never double-applies a
          relative dir on top);
        - otherwise the parfile's parent (the only stable anchor a relative
          path can mean), or the process cwd if there is no parfile.
        """
        if cwd is not None:
            return Path(cwd).expanduser().resolve()
        if primary_dir_value:
            primary = Path(primary_dir_value).expanduser()
            if primary.is_absolute():
                return primary.resolve()
        if parfile is not None:
            return parfile.parent
        return Path.cwd()

    @staticmethod
    def _resolve_outdir(out_dir_value: str, run_cwd: Path) -> Path:
        """Resolve the effective output dir against the working directory."""
        outdir = Path(out_dir_value).expanduser()
        if not outdir.is_absolute():
            outdir = (run_cwd / outdir).resolve()
        return outdir


class MeshtoolsRunner(_BinaryRunner):
    """Run the ``meshtools3d`` mesh generator."""

    binary_name: ClassVar[BinaryName] = "meshtools3d"

    def run(
        self,
        job: MeshingJob,
        *,
        overrides: MeshingOverrides | None = None,
        cwd: PathLike | None = None,
    ) -> MeshingResult:
        """Run meshtools3d for ``job`` and return a :class:`MeshingResult`.

        The job's ``parfile_path`` must already exist — authoring parameters
        (``job.write_parfile(...)``) is a separate, explicit step. ``overrides``
        are passed to the binary as its native ``-seg_dir`` / ``-seg_name`` /
        ``-out_dir`` / ``-out_name`` flags (plus ``--thickness-algorithm`` /
        ``--verbose``), overwriting the matching ``.par`` values without
        modifying the file. The ``.par`` file via ``-f`` is the binary's
        parameter source; passing it positionally is silently ignored.

        The effective output directory / name (override-or-``.par``) drive both
        the reported ``outdir`` and the expected-output prediction, so they
        match where the binary actually wrote.
        """
        par_path = job.parfile_path.expanduser().resolve()
        if not par_path.is_file():
            raise FileNotFoundError(f"parameter file not found: {par_path}")
        params = MeshingParameters(config_file=par_path)

        seg_dir_value = (
            overrides.seg_dir
            if overrides and overrides.seg_dir
            else params.get("segmentation", "seg_dir")
        )
        run_cwd = self._pick_cwd(seg_dir_value, cwd=cwd, parfile=par_path)

        out_dir_value = (
            overrides.out_dir
            if overrides and overrides.out_dir
            else params.get("output", "outdir")
        )
        outdir = self._resolve_outdir(out_dir_value, run_cwd)
        out_name = (
            overrides.out_name
            if overrides and overrides.out_name
            else params.get("output", "name")
        )

        candidates = job.expected_outputs(params, output_dir=outdir, output_name=out_name)

        argv: list[str] = ["-f", str(par_path)]
        if overrides is not None:
            argv.extend(overrides.as_cli_args())

        stdout = self._invoke(argv, cwd=run_cwd, expected_outputs=candidates)
        return MeshingResult(
            outdir=outdir, outputs=self._collect_outputs(candidates), stdout=stdout
        )


class LaplaceRunner(_BinaryRunner):
    """Run the standalone ``laplace_solver``."""

    binary_name: ClassVar[BinaryName] = "laplace_solver"

    def run(
        self,
        job: LaplaceSolveJob,
        *,
        options: LaplaceSolveOptions | None = None,
        cwd: PathLike | None = None,
    ) -> LaplaceSolveResult:
        """Run laplace_solver for ``job`` and return a :class:`LaplaceSolveResult`.

        The mesh / output / boundary-condition flags come from the job itself
        (there is no ``.par`` carrying them); ``options`` adds the behavioural
        toggles. A ``parfile_path`` is optional — when set it is passed via
        ``-f`` and must exist. The working directory is anchored on the
        effective ``mesh_dir`` (the binary's primary input).
        """
        par_path: Path | None = None
        if job.parfile_path is not None:
            par_path = job.parfile_path.expanduser().resolve()
            if not par_path.is_file():
                raise FileNotFoundError(f"parameter file not found: {par_path}")

        run_cwd = self._pick_cwd(str(job.mesh_dir), cwd=cwd, parfile=par_path)
        outdir = self._resolve_outdir(str(job.output_dir), run_cwd)

        candidates = job.expected_outputs(
            options, output_dir=outdir, output_name=job.output_name
        )

        argv: list[str] = []
        if par_path is not None:
            argv.extend(["-f", str(par_path)])
        argv.extend(job.as_cli_args())
        if options is not None:
            argv.extend(options.as_cli_args())

        stdout = self._invoke(argv, cwd=run_cwd, expected_outputs=candidates)
        return LaplaceSolveResult(
            outdir=outdir, outputs=self._collect_outputs(candidates), stdout=stdout
        )


__all__ = ["MeshtoolsRunner", "LaplaceRunner", "MacOSGatekeeperError"]
