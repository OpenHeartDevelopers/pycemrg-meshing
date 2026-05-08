"""Platform-key resolution and bundled-manifest accessors.

Pure transformation: given the running platform (or an explicit override),
return the manifest entry name to feed ``pycemrg.ModelManager.get_model_path``.

No file I/O beyond ``importlib.resources.files`` to locate the bundled
``models.yaml`` shipped with this package.
"""

from __future__ import annotations

import platform as _platform
from importlib.resources import files
from pathlib import Path
from typing import Literal

BinaryName = Literal["meshtools3d", "laplace_solver"]

# Maps (system, machine) → the platform suffix used in models.yaml entries.
# Values match the suffix in ``meshtools3d-<suffix>`` / ``laplace_solver-<suffix>``.
_PLATFORM_KEYS: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "linux-x86_64",
    ("Darwin", "arm64"): "macos-arm64",
}

SUPPORTED_BINARIES: tuple[BinaryName, ...] = ("meshtools3d", "laplace_solver")


class UnsupportedPlatformError(RuntimeError):
    """Raised when no manifest entry exists for the running platform."""


def resolve_platform_key(
    system: str | None = None, machine: str | None = None
) -> str:
    """Return the platform suffix for the running (or supplied) platform.

    >>> resolve_platform_key("Linux", "x86_64")
    'linux-x86_64'
    """
    sys_name = system if system is not None else _platform.system()
    mach = machine if machine is not None else _platform.machine()
    try:
        return _PLATFORM_KEYS[(sys_name, mach)]
    except KeyError as exc:
        supported = ", ".join(f"{s}/{m}" for s, m in _PLATFORM_KEYS)
        raise UnsupportedPlatformError(
            f"no meshtools3d build for {sys_name}/{mach}; "
            f"supported: {supported}"
        ) from exc


def model_name_for(binary: BinaryName, platform_key: str | None = None) -> str:
    """Return the ``models.yaml`` entry name for the given binary + platform.

    >>> model_name_for("meshtools3d", "linux-x86_64")
    'meshtools3d-linux-x86_64'
    """
    if binary not in SUPPORTED_BINARIES:
        raise ValueError(
            f"unknown binary {binary!r}; supported: {SUPPORTED_BINARIES}"
        )
    key = platform_key if platform_key is not None else resolve_platform_key()
    return f"{binary}-{key}"


def bundled_manifest_path() -> Path:
    """Return the filesystem path to the ``models.yaml`` shipped with this package."""
    resource = files("pycemrg_meshing").joinpath("data/models.yaml")
    return Path(str(resource))


__all__ = [
    "BinaryName",
    "SUPPORTED_BINARIES",
    "UnsupportedPlatformError",
    "resolve_platform_key",
    "model_name_for",
    "bundled_manifest_path",
]
