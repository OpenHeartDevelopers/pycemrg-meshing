# pycemrg-meshing

A Python wrapper around the `meshtools3d` and `laplace_solver` C++ binaries.
Maintained by the [Cardiac Electromechanics Research Group (CEMRG)](https://www.cemrg.com/) at Imperial College London.

---

## What this library does

`pycemrg-meshing` is a **thin, contract-driven orchestration layer** over the
meshtools3d toolchain. It authors parameter files, fetches the right prebuilt
binary for your platform, runs it, and hands back verified output paths. It
handles:

- Authoring and validating meshtools3d `.par` parameter files in memory.
- Resolving and fetching versioned binaries (`meshtools3d`, `laplace_solver`)
  from GitHub Releases, cached by URL + checksum.
- Running the binaries with explicit environment injection
  (`DYLD_LIBRARY_PATH` / `LD_LIBRARY_PATH`) and fail-fast output verification.
- Per-run overrides of segmentation/output paths via the binaries' native
  flags, without ever mutating the `.par` file.

---

## Where to go next

- **[Architecture](api/overview.md)** — the orchestration-vs-logic split and the
  end-to-end run flow.
- **[API Reference](api/index.md)** — the module map (`tools/` schema, `logic/`
  orchestration).
- **[CLI Reference](cli/index.md)** — `pycemrg-meshing init-par | run | laplace`.
- **Developer Guides** — [running on macOS](macos_gatekeeper.md) and
  [adding new binary releases](add_new_m3d_binaries.md).

---

## Design principles

| Principle | What it means in practice |
|---|---|
| **Orchestration vs. logic split** | `logic/` holds orchestration (filesystem, processes, env injection, path construction); `tools/` holds stateless transformation (parameter schema, platform-key logic). |
| **Explicit data contracts** | Layers communicate through dataclasses / flag carriers (`MeshingJob`, `MeshingOverrides`, `LaplaceSolveOptions`), never magic strings or positional soup. |
| **Fail-fast verification** | A job's `expected_outputs` is checked after the run; a missing file raises `FileNotFoundError` instead of returning a half-result. |
| **Explicit environment injection** | Runners start from `os.environ.copy()` and inject the bundled `lib/` path; no reliance on ambient environment. |
| **`.par` is never mutated** | Per-run overrides are passed as the binary's native flags; the parameter file on disk is left untouched. |

---

## Key domain terms

| Term | Meaning |
|---|---|
| **`.par`** | meshtools3d INI-style parameter file (sections `segmentation`, `meshing`, `laplacesolver`, `others`, `output`). |
| **`.inr`** | the segmentation image format meshtools3d consumes. |
| **CARP** | cardiac simulation mesh format — the `.elem` / `.pts` / `.lon` triplet. |
| **meshtools3d** | the C++ mesh-generation binary this library wraps. |
| **laplace_solver** | the C++ Laplace / wall-thickness solver binary. |
