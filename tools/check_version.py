#!/usr/bin/env python3
"""Fail unless every artefact in a directory carries one version, optionally a named one.

This guards a failure that is unusually expensive because it cannot be undone.
``pyproject.toml`` sets ``fallback_version = "0.0.0.dev0"``, so setuptools-scm
answers with a plausible-looking version rather than an error whenever it
cannot see the repository -- a source tree without ``.git``, a build container
where git refuses the mounted checkout as dubiously owned, an export from a
tarball. On a tagged run that produces wheels named ``0.0.0.dev0`` instead of
the tag, and the publish step has ``skip-existing: true``, so it uploads them
without complaint. PyPI does not let a version be reused, so the fix is a new
tag and a permanently wrong artefact on the index.

The fallback is still the right default: it keeps a source build working for
someone who has only the sdist. What it must not do is reach a release.

Two questions, deliberately separate:

* With no ``--expected``: do all the artefacts agree with each other? This one
  can run on any push, and it catches the case that motivated the script --
  the sdist built on the runner sees the repository and the wheels built
  inside a container do not, so the bundle carries two versions at once.
* With ``--expected``: is that shared version the one we meant to release?
  Only a tag knows the answer, but the code path is the same one the control
  arm exercises on every push.

Comparison is exact, not PEP 440-normalised. Normalising would let ``0.1.0``
and ``0.1.0.dev0`` compare unequal but ``0.1.0`` and ``0.1.0.post0`` read as
near-misses worth tolerating; there is nothing to tolerate here. The version
that comes from tag ``v0.1.0`` is the string ``0.1.0``, and anything else is
the bug this script exists to find.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# name-version-python-abi-platform, with an optional build tag after the
# version; and name-version for an sdist.
WHEEL_FIELDS = 5
SDIST_FIELDS = 2


def version_of(name: str) -> str | None:
    """Return the version field of a wheel or sdist filename, or None if it is neither.

    Both formats put the version immediately after the distribution name,
    separated by a hyphen, and neither the distribution name nor the version
    may itself contain one.
    """
    if name.endswith('.whl'):
        parts = name[: -len('.whl')].split('-')
        return parts[1] if len(parts) >= WHEEL_FIELDS else None
    if name.endswith('.tar.gz'):
        parts = name[: -len('.tar.gz')].split('-')
        return parts[1] if len(parts) == SDIST_FIELDS else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument(
        '--expected',
        help='the version every artefact must carry, normally the tag without its leading v',
    )
    args = parser.parse_args()

    found: dict[str, list[str]] = {}
    for path in sorted(args.directory.iterdir()):
        version = version_of(path.name)
        if version is not None:
            found.setdefault(version, []).append(path.name)

    if not found:
        print(
            f'::error::no wheel or sdist in {args.directory}; '
            f'a version check that sees nothing to check is not a passing check',
            file=sys.stderr,
        )
        return 1

    if len(found) > 1:
        print(
            f'::error::{args.directory} holds {len(found)} different versions at once, '
            f'so at least one build did not see the repository it was built from',
            file=sys.stderr,
        )
        for version, names in sorted(found.items()):
            print(f'  {version}: {" ".join(names)}', file=sys.stderr)
        return 1

    (version,) = found
    count = len(next(iter(found.values())))

    if args.expected is not None and version != args.expected:
        print(
            f'::error::the artefacts say {version} and the release says {args.expected}. '
            f'Refusing to publish: PyPI will not let this version be replaced later.',
            file=sys.stderr,
        )
        return 1

    print(f'{count} artefact(s), all at version {version}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
