# Adding a new meshtools3d binary release to `data/models.yaml`

`src/pycemrg_meshing/data/models.yaml` is the manifest that `pycemrg.ModelManager`
reads to download and cache the `meshtools3d` / `laplace_solver` binaries. Every
time meshtools3d cuts a new tagged release (e.g. `v2.0.0`), this manifest must be
updated so users fetch the new build.

This package is linked to meshtools3d development: the release tag, the tarball
naming, and the in-archive `bin/` + `lib/` layout are all produced by the
meshtools3d release CI. If that layout changes, the runners
(`logic/runners.py`) and the `unzipped_target_path` values here must change too.

> **macOS note:** the macOS tarballs are currently **unsigned**, so the
> automatic download path stops with `MacOSGatekeeperError` and users must sign
> and pass the binary manually (see `docs/macos_gatekeeper.md`). The long-term
> fix is to sign with a Developer ID certificate and notarize the tarballs in
> the meshtools3d release CI; once that ships, the guard in `logic/runners.py`
> can be removed.

## What the manifest looks like

There are **two entries per platform** — one for `meshtools3d`, one for
`laplace_solver` — and the two entries **share a single tarball URL** (the
archive contains both binaries; `ModelManager` caches it once by URL + sha256):

```yaml
meshtools3d-<platform>:
  default: "<version>"
  versions:
    "<version>":
      url: "https://github.com/OpenHeartDevelopers/meshtools3d/releases/download/v<version>/meshtools3d-<version>-<platform>.tar.gz"
      sha256: "<64-hex-char digest of that tarball>"
      unzipped_target_path: "meshtools3d-<version>-<platform>/bin/meshtools3d"
```

Supported `<platform>` values today are exactly `linux-x86_64` and
`macos-arm64` (see `tools/binaries.py::_PLATFORM_KEYS`). Adding a brand-new
platform also requires adding it there.

## Step-by-step: adding version `<version>` (e.g. `2.0.0`)

### 1. Confirm the release artifacts exist

Check the GitHub release page has the per-platform tarballs:

```
https://github.com/OpenHeartDevelopers/meshtools3d/releases/tag/v<version>
```

You need one `*.tar.gz` per supported platform, each named
`meshtools3d-<version>-<platform>.tar.gz`.

### 2. Download each tarball and compute its sha256

```bash
VERSION=2.0.0
for PLAT in linux-x86_64 macos-arm64; do
  URL="https://github.com/OpenHeartDevelopers/meshtools3d/releases/download/v${VERSION}/meshtools3d-${VERSION}-${PLAT}.tar.gz"
  curl -sL -o "meshtools3d-${VERSION}-${PLAT}.tar.gz" "$URL"
  shasum -a 256 "meshtools3d-${VERSION}-${PLAT}.tar.gz"   # macOS
  # sha256sum "meshtools3d-${VERSION}-${PLAT}.tar.gz"      # Linux
done
```

Each digest must be **64 hex characters**. The two binaries on a given platform
share the tarball, so the sha256 is identical for both entries on that platform.

### 3. Verify the in-archive path

`unzipped_target_path` must point at the binary *inside* the extracted archive
and **must end with `/bin/<binary>`** (asserted by the test suite). Confirm the
real layout:

```bash
tar -tzf "meshtools3d-${VERSION}-linux-x86_64.tar.gz" | grep -E '/bin/(meshtools3d|laplace_solver)$'
```

Expected:

```
meshtools3d-<version>-linux-x86_64/bin/meshtools3d
meshtools3d-<version>-linux-x86_64/bin/laplace_solver
```

The shared libraries should sit in a sibling `lib/` directory; the runners
inject `DYLD_LIBRARY_PATH` / `LD_LIBRARY_PATH` pointing at it.

### 4. Edit `data/models.yaml`

For each of the four entries (`meshtools3d` + `laplace_solver`, times two
platforms), add the new version under `versions:` and bump `default:` to the
new version. Keep older versions in `versions:` so pinned installs still work.

```yaml
meshtools3d-linux-x86_64:
  default: "2.0.0"            # <- bumped
  versions:
    "2.0.0":                  # <- new block
      url: "https://github.com/OpenHeartDevelopers/meshtools3d/releases/download/v2.0.0/meshtools3d-2.0.0-linux-x86_64.tar.gz"
      sha256: "<linux digest from step 2>"
      unzipped_target_path: "meshtools3d-2.0.0-linux-x86_64/bin/meshtools3d"
    "2.0.0-beta.2":           # <- keep prior versions
      url: "..."
      sha256: "..."
      unzipped_target_path: "..."
```

Repeat for `laplace_solver-linux-x86_64`, `meshtools3d-macos-arm64`, and
`laplace_solver-macos-arm64`. Remember: on each platform, the `meshtools3d` and
`laplace_solver` entries use the **same `url` and `sha256`**, differing only in
`unzipped_target_path` (`.../bin/meshtools3d` vs `.../bin/laplace_solver`).

### 5. Validate

```bash
pytest tests/test_binaries.py
```

`test_bundled_manifest_exists_and_parses` checks that every
`<binary>-<platform>` entry exists, the URL starts with `https://github.com/`,
the sha256 is 64 chars, and `unzipped_target_path` ends with `/bin/<binary>`.

For an end-to-end check that the digest and download actually work:

```bash
pytest -m live          # downloads + runs the real binary (off by default)
```

### 6. Bump the package version (optional)

If the new binary is what users get by default, bump `version` in
`pyproject.toml` and `__version__` in `src/pycemrg_meshing/__init__.py` and tag
a pycemrg-meshing release.

## Checklist

- [ ] Release tarballs exist for every supported platform
- [ ] sha256 computed for each tarball (64 hex chars; shared per platform)
- [ ] `unzipped_target_path` verified against `tar -tzf` output
- [ ] New version block added under `versions:` for all four entries
- [ ] `default:` bumped to the new version for all four entries
- [ ] Prior versions retained
- [ ] `pytest tests/test_binaries.py` passes
- [ ] (optional) `pytest -m live` passes
- [ ] (optional) package version bumped + tagged
