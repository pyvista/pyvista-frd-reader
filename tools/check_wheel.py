#!/usr/bin/env python3
"""Check an installed wheel, not a source tree, from outside the source tree.

cibuildwheel runs this in a temporary directory against the wheel it just
built, so an import that accidentally resolved to ``src/`` would fail here --
which is the point. What it asserts:

* the native library loaded, and it is the one inside the installed package
  rather than something else that happened to be on the loader path;
* that library reads a real CalculiX file end to end and produces a grid with
  points, cells, and the derived arrays.

The gtest tier builds its own library with its own flags and never sees this
artefact. "The library loaded" and "the library works" are separate claims,
and this is the only place the second one is made about a shipped wheel.

Usage: check_wheel.py FIXTURE.frd
"""

from __future__ import annotations

import pathlib
import sys

import pyvista_frd


def main() -> int:
    try:
        (fixture,) = sys.argv[1:]
    except ValueError:
        raise SystemExit(__doc__) from None

    library = pathlib.Path(pyvista_frd.library_path())
    if not library.exists():
        print(f'::error::library_path() points at {library}, which does not exist')
        return 1
    if 'pyvista_frd' not in library.parts:
        print(f'::error::loaded {library}, which is not the bundled library')
        return 1

    mesh = pyvista_frd.read(fixture)
    if mesh.n_points == 0 or mesh.n_cells == 0:
        print(f'::error::read {fixture} to an empty grid: {mesh.n_points} points')
        return 1
    if 'original_node_ids' not in mesh.point_data:
        print('::error::original_node_ids missing from the grid')
        return 1

    derived = [name for name in mesh.point_data if name.endswith(('_Mises', '_PS1'))]
    if not derived:
        print(f'::error::no derived arrays in {sorted(mesh.point_data)}')
        return 1

    print(f'{library.name} read {mesh.n_points} points, {mesh.n_cells} cells')
    print(f'derived arrays present: {sorted(derived)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
