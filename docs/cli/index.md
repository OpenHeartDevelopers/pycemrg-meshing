# CLI Reference

`pycemrg-meshing` installs a single console entry point, a Click group with three
subcommands:

```bash
pycemrg-meshing [-v/--verbose] {init-par | run | laplace} ...
```

The top-level `-v/--verbose` flag enables INFO logging. Use `-h/--help` on the
group or any subcommand for the full, authoritative option list.

---

## `init-par` — write a default parameter file

Generates a meshtools3d `.par` file seeded with the core defaults.

```bash
pycemrg-meshing init-par -o heart.par \
  --set segmentation.seg_dir=/data/case01 \
  --set meshing.facet_angle=30
```

| Option | Description |
|---|---|
| `-o, --output PATH` | Path for the generated parameter file (default: `heart.par`). |
| `--set SECTION.KEY=VALUE` | Override a default parameter. Repeatable. Keys are validated against the schema and a typo raises. |

---

## `run` — run meshtools3d

Builds a `MeshingJob` from an existing `.par` file and runs the `meshtools3d`
binary. The `.par` file is never modified; per-run overrides are passed to the
binary as its native flags.

```bash
pycemrg-meshing run heart.par --seg-dir /data/case01 --out-dir /data/case01/mesh
```

| Argument / Option | Description |
|---|---|
| `PARFILE` | Path to an existing `.par` file (required). |
| `--binary PATH` | Explicit binary path; otherwise resolved via `pycemrg`'s asset manager. |
| `--cwd PATH` | Working directory for the binary (default: derived from `seg_dir`). |
| `--seg-dir` | Override `[segmentation] seg_dir` (binary `-seg_dir`). |
| `--seg-name` | Override `[segmentation] seg_name` (binary `-seg_name`). |
| `--out-dir` | Override `[output] outdir` (binary `-out_dir`). |
| `--out-name` | Override `[output] name` (binary `-out_name`). |

---

## `laplace` — run laplace_solver

Runs the `laplace_solver` binary over a CARP mesh. Unlike `run`, laplace carries
its mesh/output/BC paths directly as flags (there is no `.par` to override); the
optional `-f/--parfile` only supplies `[laplacesolver]` parameters.

```bash
pycemrg-meshing laplace \
  --mesh-dir /data/case01/mesh --mesh-name myo \
  --out-dir /data/case01/laplace --out-name thickness \
  --zero-bc endo.vtx --one-bc epi.vtx --vtk
```

| Option | Description |
|---|---|
| `--mesh-dir` | Directory containing the CARP mesh (required, `-mesh_dir`). |
| `--mesh-name` | CARP mesh basename (required, `-mesh_name`). |
| `--out-dir` | Output directory (required, `-out_dir`). |
| `--out-name` | Output basename (required, `-out_name`). |
| `--zero-bc PATH` | vtx node-set assigned value `0.0`. Repeatable. |
| `--one-bc PATH` | vtx node-set assigned value `1.0`. Repeatable. |
| `-f, --parfile PATH` | Optional GetPot file for `[laplacesolver]` params. |
| `--binary PATH` | Explicit binary path; otherwise resolved via `pycemrg`'s asset manager. |
| `--vtk` | Write VTK output. |
| `--vtk-binary` | Binary VTK; requires `--vtk`. |
| `--potential` | Write potential output. |
| `--no-thickness` | Solve only, skip thickness. |
| `--swap-regions` | Swap endo/epi direction. |
| `--thickness-algo` | Select the thickness algorithm. |
| `--solver-verbose` | Verbose solver output. |
