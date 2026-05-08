# pycemrg-meshing

Python wrapper for the [meshtools3d](https://github.com/OpenHeartDevelopers/meshtools3d)
C++ binaries. Lets Python users:

1. Author meshtools3d parameter files programmatically.
2. Fetch versioned binaries automatically from the meshtools3d GitHub Releases.
3. Run `meshtools3d` and `laplace_solver` with structured output handling.

Built on top of [`pycemrg`](https://github.com/OpenHeartDevelopers/pycemrg)
(`CommandRunner`, `ModelManager`).

> **Status:** v0.1 in development. API may shift before the first tagged release.

## Install

```bash
pip install pycemrg-meshing
```

## Quick start

```python
from pycemrg_meshing import MeshingParameters, MeshtoolsRunner

params = MeshingParameters()
params.set("meshing", "facet_size", 0.5)
params.set("output", "outdir", "/data/case01/mesh")
params.save("heart.par")

runner = MeshtoolsRunner()           # binary fetched via ModelManager
runner.run("heart.par")
```

## CLI

```
pycemrg-meshing init-par [-o PATH]
pycemrg-meshing run     PARFILE [--binary PATH] [--cwd D]
pycemrg-meshing laplace PARFILE [--binary PATH] [--cwd D]
```

## License

MIT.
