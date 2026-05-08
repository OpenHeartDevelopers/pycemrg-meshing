"""Unit tests for tools.binaries."""

from __future__ import annotations

import yaml
import pytest

from pycemrg_meshing.tools import binaries
from pycemrg_meshing.tools.binaries import (
    SUPPORTED_BINARIES,
    UnsupportedPlatformError,
    bundled_manifest_path,
    model_name_for,
    resolve_platform_key,
)


# ---------------------------------------------------------- resolve_platform_key


@pytest.mark.parametrize(
    "system, machine, expected",
    [
        ("Linux", "x86_64", "linux-x86_64"),
        ("Darwin", "arm64", "macos-arm64"),
    ],
)
def test_resolve_platform_key_supported(
    system: str, machine: str, expected: str
) -> None:
    assert resolve_platform_key(system, machine) == expected


@pytest.mark.parametrize(
    "system, machine",
    [
        ("Windows", "AMD64"),
        ("Linux", "aarch64"),
        ("Darwin", "x86_64"),  # not in v0.1 scope
        ("Plan9", "alien"),
    ],
)
def test_resolve_platform_key_unsupported(system: str, machine: str) -> None:
    with pytest.raises(UnsupportedPlatformError, match=system):
        resolve_platform_key(system, machine)


def test_resolve_platform_key_uses_runtime_when_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binaries._platform, "system", lambda: "Linux")
    monkeypatch.setattr(binaries._platform, "machine", lambda: "x86_64")
    assert resolve_platform_key() == "linux-x86_64"


# ------------------------------------------------------------- model_name_for


def test_model_name_for_known_binary() -> None:
    assert model_name_for("meshtools3d", "linux-x86_64") == "meshtools3d-linux-x86_64"
    assert model_name_for("laplace_solver", "macos-arm64") == "laplace_solver-macos-arm64"


def test_model_name_for_rejects_unknown_binary() -> None:
    with pytest.raises(ValueError, match="bogus"):
        model_name_for("bogus", "linux-x86_64")  # type: ignore[arg-type]


def test_model_name_for_uses_runtime_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(binaries._platform, "system", lambda: "Darwin")
    monkeypatch.setattr(binaries._platform, "machine", lambda: "arm64")
    assert model_name_for("meshtools3d") == "meshtools3d-macos-arm64"


# ------------------------------------------------------- bundled_manifest_path


def test_bundled_manifest_exists_and_parses() -> None:
    path = bundled_manifest_path()
    assert path.is_file()
    with path.open() as fh:
        manifest = yaml.safe_load(fh)
    # All expected entries are present.
    for binary in SUPPORTED_BINARIES:
        for plat in ("linux-x86_64", "macos-arm64"):
            entry_name = f"{binary}-{plat}"
            assert entry_name in manifest, f"missing manifest entry: {entry_name}"
            entry = manifest[entry_name]
            default_version = entry["default"]
            version = entry["versions"][default_version]
            assert version["url"].startswith("https://github.com/")
            assert len(version["sha256"]) == 64
            assert version["unzipped_target_path"].endswith(f"/bin/{binary}")
