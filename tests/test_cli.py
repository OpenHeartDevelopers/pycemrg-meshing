"""CLI tests: Click wiring for init-par / run, including --set and overrides."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from pycemrg_meshing import cli as cli_module
from pycemrg_meshing.cli import cli
from pycemrg_meshing.tools.parameters import MeshingOverrides


class _RecordingRunner:
    """Stand-in for MeshtoolsRunner that records what the CLI passed."""

    last: dict | None = None

    def __init__(self, binary_path=None) -> None:  # noqa: ANN001 - test double
        self.binary_path = binary_path

    def run(self, parfile, *, cwd=None, overrides=None):  # noqa: ANN001 - test double
        type(self).last = {
            "parfile": Path(parfile),
            "cwd": cwd,
            "overrides": overrides,
        }
        return Path("/tmp/out")


# --------------------------------------------------------------------- init-par


def test_init_par_writes_file_with_set_override(tmp_path: Path) -> None:
    out = tmp_path / "heart.par"
    result = CliRunner().invoke(
        cli, ["init-par", "-o", str(out), "--set", "meshing.cell_size=1.5"]
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "cell_size = 1.5" in out.read_text()


def test_init_par_rejects_malformed_set(tmp_path: Path) -> None:
    out = tmp_path / "heart.par"
    result = CliRunner().invoke(
        cli, ["init-par", "-o", str(out), "--set", "no_equals_sign"]
    )
    assert result.exit_code != 0
    assert "SECTION.KEY=VALUE" in result.output
    assert not out.exists()


def test_init_par_unknown_key_fails_loudly(tmp_path: Path) -> None:
    out = tmp_path / "heart.par"
    result = CliRunner().invoke(
        cli, ["init-par", "-o", str(out), "--set", "meshing.not_a_key=1"]
    )
    assert result.exit_code != 0


# -------------------------------------------------------------------------- run


def test_run_forwards_overrides_to_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_module, "MeshtoolsRunner", _RecordingRunner)
    parfile = tmp_path / "heart.par"
    parfile.write_text("[output]\noutdir = ./x\n")

    result = CliRunner().invoke(
        cli,
        ["run", str(parfile), "--seg-dir", "/data/case3", "--out-name", "run3"],
    )

    assert result.exit_code == 0, result.output
    assert _RecordingRunner.last is not None
    overrides = _RecordingRunner.last["overrides"]
    assert isinstance(overrides, MeshingOverrides)
    assert overrides.seg_dir == "/data/case3"
    assert overrides.out_name == "run3"
    assert overrides.seg_name is None and overrides.out_dir is None
    assert "outdir=" in result.output


def test_run_missing_parfile_exits_nonzero() -> None:
    result = CliRunner().invoke(cli, ["run", "/no/such/heart.par"])
    assert result.exit_code != 0


def test_run_help_lists_override_flags() -> None:
    result = CliRunner().invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    for flag in ("--seg-dir", "--seg-name", "--out-dir", "--out-name"):
        assert flag in result.output
