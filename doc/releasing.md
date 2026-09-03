# Releasing

Push a version tag to start a release. The workflow builds, tests, checks, and
publishes the existing artifacts.

## PyPI setup

Register a pending trusted publisher at
<https://pypi.org/manage/account/publishing/>:

| Field | Value |
| --- | --- |
| PyPI project name | `pyvista-frd-reader` |
| Owner | `pyvista` |
| Repository name | `pyvista-frd-reader` |
| Workflow name | `native.yml` |
| Environment name | `pypi` |

The environment name must match the `pypi` environment declared by the release
job. The repository environment already restricts deployment to tags matching
`v*`. Trusted publishing does not require a PyPI API token.

## Cut a release

```bash
git tag -a v0.2.2 -m "v0.2.2"
git push origin v0.2.2
```

`setuptools-scm` derives the package version from the tag. Do not add or edit a
source version string.

The tag workflow runs the C++ tests on five runners, sanitizers, fuzz tests,
the WebAssembly cross-check, wheel tests, and the source-distribution build.
The release job downloads and publishes those tested artifacts; it does not
rebuild them.

## Artifact checks

`tools/check_dist.sh` requires one wheel for each supported platform and one
source distribution. The bundle job runs this check on every push. It also
tests known-invalid bundles so a check that stops rejecting incomplete output
fails before a release.

`tools/check_version.py` checks two conditions:

- Without `--expected`, every artifact must contain the same version. This
  catches a build that fell back to `0.0.0.dev0` because it could not inspect
  the Git checkout.
- With `--expected`, the shared artifact version must match the release tag.
  The release job runs this immediately before upload.

## Recover an upload

The upload uses `skip-existing: true`. Rerun the release job after a partial
upload to publish only the missing files.

PyPI does not allow a deleted filename or release artifact to be replaced. If
an incorrect artifact was published, fix the release and use a new version and
tag.
