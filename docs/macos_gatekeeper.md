# Running meshtools3d on macOS (Apple Silicon)

On Apple Silicon, macOS SIGKILLs the prebuilt `meshtools3d` arm64 binaries the
first time you run them:

```
zsh: killed     ./meshtools3d-2.0.0-macos-arm64/bin/meshtools3d
```

This is not a crash in meshtools3d. The arm64 kernel refuses to execute a binary
without a valid code signature, and the released tarballs are currently
**unsigned**. Removing the quarantine attribute alone is not enough — the dylibs
and binaries must also be ad-hoc re-signed.

## Why pycemrg-meshing stops instead of auto-fixing

`pycemrg-meshing` deliberately does **not** sign the binaries for you. Doing so
would mean the library shells out to `codesign`/`xattr` to mutate files it did
not build — hidden, side-effecting behavior we would rather keep out of the
package. Instead, when the automatic `ModelManager` download path is used on
macOS, the runner stops with a `MacOSGatekeeperError` that prints the exact
commands below and the path of the extracted install.

## Preferred workflow: install, sign once, pass the path

The recommended macOS workflow is to install meshtools3d yourself, sign it once,
and hand the path to the runner via an explicit override (which skips
`ModelManager` entirely):

```bash
# 1. Download + extract the macOS tarball from the meshtools3d release page, e.g.
#    https://github.com/OpenHeartDevelopers/meshtools3d/releases
DIR=$PWD/meshtools3d-2.0.0-macos-arm64

# 2. Strip quarantine and ad-hoc sign the dylibs and binaries
xattr -dr com.apple.quarantine "$DIR"
for f in "$DIR"/lib/*.dylib; do [ -L "$f" ] && continue; codesign --force --sign - "$f"; done
for b in "$DIR"/bin/*; do codesign --force --sign - "$b"; done

# 3. Confirm it runs
"$DIR"/bin/meshtools3d
```

The `[ -L "$f" ] && continue` skips symlinked dylibs (sign the real files only).
The `bin/*` loop covers every shipped binary — `meshtools3d`, `laplace_solver`,
and `parfile_builder`.

Then point the runner at the signed binary:

```bash
pycemrg-meshing run heart.par --binary "$DIR/bin/meshtools3d"
pycemrg-meshing laplace heart.par --binary "$DIR/bin/laplace_solver"
```

```python
from pycemrg_meshing import MeshtoolsRunner

runner = MeshtoolsRunner(binary_path="/path/to/meshtools3d-2.0.0-macos-arm64/bin/meshtools3d")
runner.run("heart.par")
```

Once signed and passed explicitly, the run proceeds normally — the
`ModelManager` download path (and its Gatekeeper stop) is never reached again.

## Long-term fix

The proper fix lives upstream in the **meshtools3d release CI**: sign the
binaries with a Developer ID certificate and notarize the tarballs. When that
ships, downloaded builds will run directly and the `MacOSGatekeeperError` guard
in `logic/runners.py` can be removed.
