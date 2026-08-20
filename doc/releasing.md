# Releasing

A release is a tag. Everything else is automatic — but two of the steps below
are one-time setup on PyPI, and until they are done a tag will build wheels,
check them, and then fail at the upload.

## One-time setup

### 1. Register the trusted publisher on PyPI

The release job uploads with [trusted publishing][tp], so there is no API
token anywhere in this repo and nothing to rotate or leak. PyPI has to be told
which workflow it should trust, and because the project does not exist on PyPI
yet, that is done through the *pending* publisher form:

<https://pypi.org/manage/account/publishing/>

| Field | Value |
| --- | --- |
| PyPI project name | `pyvista-frd-reader` |
| Owner | `pyvista` |
| Repository name | `pyvista-frd-reader` |
| Workflow name | `native.yml` |
| Environment name | `pypi` |

The environment name is not optional. The release job declares
`environment: pypi`, and a publisher registered without it will reject the
upload.

### 2. Nothing else

The `pypi` environment already exists on the repository and is restricted to
tags matching `v*`. That restriction is deliberate belt-and-braces: the
workflow's own `if:` already limits the job to tag pushes, but the environment
policy is enforced by GitHub rather than by a condition someone could edit in
a pull request. Adding a required reviewer to that environment is a
reasonable further step if releases should not be able to happen unattended.

## Cutting a release

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
```

The version comes from the tag via `setuptools-scm`; there is no version
string in the source to bump, and therefore no way for one to disagree with
the tag.

The tag push runs the full matrix, and `release` runs only if all of it
passes: the gtest tier on five runners, the sanitizers, the fuzzer, the
WebAssembly cross-check, every wheel, and the sdist's from-source build. It
then publishes **the artefacts those jobs built**, downloaded from the run,
rather than rebuilding on the release runner — a release job that rebuilds is
publishing something no test has ever run against.

## What stops a partial release

`tools/check_dist.sh` requires a wheel for each platform we publish plus an
sdist, and the `bundle` job runs it on **every push**, not only on tags. PyPI
keeps whatever it is given: a release that uploaded five wheels out of six
cannot be fixed by uploading the sixth later under the same version, and every
user of the missing platform falls through to a source build in the meantime.

That job also runs the check against an empty directory first and requires it
to fail. A gate whose first execution is the release is a gate nobody has
watched pass, and "the check passed" would otherwise have two explanations.

## If the upload fails anyway

`skip-existing: true` is set, so re-running the release job after a partial
upload uploads only what is missing rather than failing on the files already
there. Deleting a release from PyPI does not free the filename: a re-upload
needs a new version, which means a new tag.

[tp]: https://docs.pypi.org/trusted-publishers/
