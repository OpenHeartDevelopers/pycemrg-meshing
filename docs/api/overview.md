# Architecture

`pycemrg-meshing` wraps two C++ binaries — `meshtools3d` and `laplace_solver` —
behind a small, contract-driven Python surface. Its job is to author parameter
files, fetch the correct binary for the host platform, run it with an explicit
environment, and return verified output paths.

## The two layers

The package is split into two directories by responsibility:

| Directory | Responsibility | Contents |
|---|---|---|
| `tools/` | **Stateless transformation.** Pure schema and platform-key logic, no ambient I/O. | `parameters.py`, `binaries.py` |
| `logic/` | **Orchestration.** Touches the filesystem, spawns processes, injects environment variables, builds paths from conventions. | `runners.py`, `job.py`, `results.py` |

!!! note "Naming"
    In this repository, `logic/` is the orchestration layer and `tools/` is the
    stateless layer. Keep new code on the correct side of this split: stateless
    schema belongs in `tools/parameters.py`; anything that writes files or runs
    processes belongs in `logic/`.

## The run flow

A meshtools3d run is an explicit, three-step sequence — authoring the parameter
file is separate from running the binary:

1. **Author parameters.** Build a `MeshingParameters` schema, `set` any overrides,
   and write the `.par` file (`job.write_parfile(...)`). Keys are validated
   against the schema union, so typos raise rather than silently no-op.
2. **Build the job.** A `MeshingJob` bundles the segmentation, output, and parfile
   paths; `MeshingJob.from_parfile()` reconstructs it from an existing `.par`.
3. **Run.** `MeshtoolsRunner.run(job, *, overrides, cwd)` discovers the binary,
   injects the bundled library path, runs it, and returns a frozen
   `MeshingResult`. `LaplaceRunner.run(job, *, options, cwd)` is the analogous
   path for `laplace_solver`.

`run()` requires the parfile to already exist — authoring is a separate, explicit
step, never a side effect of running.

## Core stances

- **Explicit data contracts.** Layers communicate through dataclasses and flag
  carriers — `MeshingJob`, `MeshingOverrides`, `LaplaceSolveOptions` — rather than
  magic strings. `MeshingOverrides` renders meshtools3d's native override flags;
  `LaplaceSolveOptions` carries laplace's behaviour toggles only.
- **`.par` is never mutated by a run.** Per-run overrides are passed as the
  binary's own `-seg_dir` / `-out_dir` / etc. flags; the file on disk is left
  untouched.
- **Fail-fast verification.** The job's `expected_outputs`, re-based onto the
  effective output directory, is handed to the underlying `CommandRunner`, which
  raises `FileNotFoundError` after the run if any expected file is missing.
- **Explicit environment injection.** Runners start from `os.environ.copy()` and
  add `DYLD_LIBRARY_PATH` (macOS) / `LD_LIBRARY_PATH` (Linux) pointing at the
  bundled `lib/` beside the binary — never relying on ambient environment.
- **Deliberate working directory.** Because the binary resolves relative paths
  against its cwd, the runner picks cwd carefully (explicit `--cwd` wins, else an
  absolute effective input dir, else the parfile's parent), and reports `outdir`
  against that same cwd to stay truthful.

## Binary distribution

Binaries are fetched on demand via `pycemrg`'s `ModelManager`, driven by
`data/models.yaml`. Each platform has two entries (`meshtools3d` +
`laplace_solver`) sharing one tarball URL, cached by URL + checksum so the
archive downloads once. Supported platforms are `linux-x86_64` and
`macos-arm64`; anything else raises `UnsupportedPlatformError`.

See the developer guides for [running on macOS](../macos_gatekeeper.md) and
[adding a new binary release](../add_new_m3d_binaries.md).
