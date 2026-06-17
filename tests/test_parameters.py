"""Unit tests for MeshingParameters."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

from pycemrg_meshing.tools.parameters import (
    DEFAULT_VALUES,
    EXTENDED_DEFAULTS,
    LaplaceSolveOptions,
    MeshingOverrides,
    MeshingParameters,
    default_parameters,
)

# --------------------------------------------------------------- MeshingOverrides


def test_overrides_default_to_none_and_emit_no_args() -> None:
    ov = MeshingOverrides()
    assert (ov.seg_dir, ov.seg_name, ov.out_dir, ov.out_name) == (None, None, None, None)
    assert ov.as_cli_args() == []


def test_overrides_emit_only_set_fields_as_native_flags() -> None:
    ov = MeshingOverrides(seg_dir="/data/case1", out_name="run7")
    assert ov.as_cli_args() == ["-seg_dir", "/data/case1", "-out_name", "run7"]


def test_overrides_emit_all_four_in_canonical_order() -> None:
    ov = MeshingOverrides(seg_dir="d", seg_name="s.inr", out_dir="o", out_name="n")
    assert ov.as_cli_args() == [
        "-seg_dir", "d", "-seg_name", "s.inr", "-out_dir", "o", "-out_name", "n",
    ]


def test_overrides_emit_thickness_and_verbose() -> None:
    ov = MeshingOverrides(thickness_algorithm=1, verbose=True)
    assert ov.as_cli_args() == ["--thickness-algorithm", "1", "--verbose"]


# ----------------------------------------------------------- LaplaceSolveOptions


def test_laplace_options_default_to_no_args() -> None:
    assert LaplaceSolveOptions().as_cli_args() == []


def test_laplace_options_render_toggles_in_order() -> None:
    opts = LaplaceSolveOptions(
        no_thickness=True,
        swap_regions=True,
        thickness_algorithm=2,
        vtk=True,
        vtk_binary=True,
        potential=True,
        verbose=True,
    )
    assert opts.as_cli_args() == [
        "--no-thickness", "--swap-regions", "--thickness-algorithm", "2",
        "--vtk", "--vtk-binary", "--potential", "--verbose",
    ]


def test_laplace_options_emit_only_enabled() -> None:
    assert LaplaceSolveOptions(potential=True).as_cli_args() == ["--potential"]


# ----------------------------------------------------------------- Defaults


def test_defaults_match_schema_doc() -> None:
    snapshot = default_parameters()
    assert snapshot == DEFAULT_VALUES
    # Mutating the snapshot must not leak into the module-level table.
    snapshot["meshing"]["facet_size"] = "9999"
    assert DEFAULT_VALUES["meshing"]["facet_size"] == "0.8"


def test_create_dict_returns_full_default_table() -> None:
    p = MeshingParameters()
    assert p.create_dict() == DEFAULT_VALUES


# ------------------------------------------------------------- Case preserving


def test_case_preserving_camelcase_keys(tmp_path: Path) -> None:
    p = MeshingParameters()
    out = p.save(tmp_path / "heart.par")
    text = out.read_text()
    # The camelCase keys must survive a round-trip — see m3d_python_params.md §1.
    assert "rescaleFactor" in text
    assert "dimKrilovSp" in text
    # And not be lower-cased by configparser's default optionxform.
    assert "rescalefactor" not in text
    assert "dimkrilovsp" not in text


# --------------------------------------------------------------- Round-trip


def test_round_trip_via_save_then_load(tmp_path: Path) -> None:
    p = MeshingParameters()
    p.set("meshing", "facet_size", 0.5)
    p.set("output", "outdir", "/data/case01/mesh")
    p.set("output", "name", "case01")
    par = p.save(tmp_path / "heart.par")

    q = MeshingParameters(config_file=par)
    assert q.get("meshing", "facet_size") == "0.5"
    assert q.get("output", "outdir") == "/data/case01/mesh"
    assert q.get("output", "name") == "case01"
    assert p == q


def test_load_rejects_unknown_section(tmp_path: Path) -> None:
    bad = tmp_path / "bad.par"
    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # type: ignore[assignment]
    cfg["bogus"] = {"key": "value"}
    with bad.open("w") as fh:
        cfg.write(fh)
    with pytest.raises(KeyError, match="bogus"):
        MeshingParameters(config_file=bad)


def test_load_rejects_unknown_key(tmp_path: Path) -> None:
    bad = tmp_path / "bad.par"
    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # type: ignore[assignment]
    cfg["meshing"] = {"not_a_real_key": "1"}
    with bad.open("w") as fh:
        cfg.write(fh)
    with pytest.raises(KeyError, match="not_a_real_key"):
        MeshingParameters(config_file=bad)


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        MeshingParameters(config_file=tmp_path / "does_not_exist.par")


# --------------------------------------------------------------- Validation


def test_set_unknown_section_raises() -> None:
    p = MeshingParameters()
    with pytest.raises(KeyError, match="bogus"):
        p.set("bogus", "facet_size", 0.5)


def test_set_unknown_key_raises() -> None:
    p = MeshingParameters()
    with pytest.raises(KeyError, match="not_a_real_key"):
        p.set("meshing", "not_a_real_key", 0.5)


def test_get_unknown_key_raises() -> None:
    p = MeshingParameters()
    with pytest.raises(KeyError):
        p.get("meshing", "not_a_real_key")


def test_set_stringifies_numerics() -> None:
    p = MeshingParameters()
    p.set("meshing", "facet_size", 0.5)
    assert p.get("meshing", "facet_size") == "0.5"
    p.set("laplacesolver", "itr_max", 1234)
    assert p.get("laplacesolver", "itr_max") == "1234"


# ---------------------------------------------- Extended (§2.6) schema decouple


def test_extended_key_is_settable_and_gettable() -> None:
    p = MeshingParameters()
    p.set("meshing", "readTheMesh", "1")  # would have raised KeyError before
    assert p.get("meshing", "readTheMesh") == "1"


def test_get_extended_key_returns_default_when_unset() -> None:
    p = MeshingParameters()
    assert p.get("others", "thickalgo") == EXTENDED_DEFAULTS["others"]["thickalgo"]
    assert p.get("output", "debug_frequency") == "100"


def test_unknown_key_still_raises_against_union() -> None:
    p = MeshingParameters()
    with pytest.raises(KeyError, match="still_not_real"):
        p.set("meshing", "still_not_real", "1")


def test_save_omits_extended_keys_by_default(tmp_path: Path) -> None:
    """Bare init-par output matches parfile_builder: §2.1–§2.5 only."""
    text = MeshingParameters().save(tmp_path / "heart.par").read_text()
    assert "readTheMesh" not in text
    assert "swapregions" not in text
    assert "debug_output" not in text


def test_save_includes_extended_key_once_set(tmp_path: Path) -> None:
    p = MeshingParameters()
    p.set("meshing", "readTheMesh", "1")
    text = p.save(tmp_path / "heart.par").read_text()
    assert "readTheMesh = 1" in text
    # Other extended keys still absent (only the one we set is emitted).
    assert "swapregions" not in text


def test_load_accepts_extended_key_and_round_trips(tmp_path: Path) -> None:
    src = MeshingParameters()
    src.set("others", "swapregions", "1")
    par = src.save(tmp_path / "heart.par")

    loaded = MeshingParameters(config_file=par)
    assert loaded.get("others", "swapregions") == "1"
    # Re-saving keeps it (and still does not inject the other §2.6 keys).
    text = loaded.save(tmp_path / "again.par").read_text()
    assert "swapregions = 1" in text
    assert "readTheMesh" not in text


# ---------------------------------------------------------------- Resetting


def test_reset_restores_defaults() -> None:
    p = MeshingParameters()
    p.set("meshing", "facet_size", 0.1)
    assert p.get("meshing", "facet_size") == "0.1"
    p.reset_to_defaults()
    assert p.get("meshing", "facet_size") == DEFAULT_VALUES["meshing"]["facet_size"]


# ----------------------------------------------------- Save creates parent dir


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    p = MeshingParameters()
    out = p.save(tmp_path / "nested" / "deeper" / "heart.par")
    assert out.is_file()
