# API Reference

The module map. `pycemrg-meshing` is split into two layers: **`tools/`** is
stateless transformation (pure schema and platform-key logic, no ambient I/O),
and **`logic/`** is orchestration (filesystem, processes, environment, path
construction). For the design rationale and the end-to-end run sequence, start
with [Architecture](overview.md).

## Tools — stateless transformation

| Module | What it does | Public symbols |
|---|---|---|
| `tools.parameters` | In-memory `ConfigParser` schema for `.par` files; validates section + key against the schema union and raises on typos. Also defines the stateless flag carriers. | `MeshingParameters`, `MeshingOverrides`, `LaplaceSolveOptions` |
| `tools.binaries` | Maps `(system, machine)` to a manifest platform suffix and builds `models.yaml` entry names. | platform-key / entry-name helpers, `UnsupportedPlatformError` |

## Logic — orchestration

| Module | What it does | Public symbols |
|---|---|---|
| `logic.job` | Bundles segmentation / output / parfile paths and enumerates expected outputs; reconstructs a job from an existing `.par`. | `MeshingJob`, `LaplaceSolveJob` |
| `logic.runners` | Binary discovery, library-path injection, cwd/outdir math, invocation, and fail-fast output verification. | `MeshtoolsRunner`, `LaplaceRunner` |
| `logic.results` | Frozen result contracts carrying the verified output files and captured stdout. | `MeshingResult`, `LaplaceSolveResult`, `OutputFile` |

!!! info "Looking for the orchestration pattern?"
    The high-level workflow sequence — author parfile → run → verified results —
    and the core contracts are documented on the [Architecture](overview.md) page.
