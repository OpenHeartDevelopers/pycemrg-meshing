"""Smoke test: package imports cleanly."""

import pycemrg_meshing


def test_version_exposed() -> None:
    assert isinstance(pycemrg_meshing.__version__, str)


def test_public_exports() -> None:
    assert hasattr(pycemrg_meshing, "MeshingParameters")
    assert hasattr(pycemrg_meshing, "MeshtoolsRunner")
    assert hasattr(pycemrg_meshing, "LaplaceRunner")
