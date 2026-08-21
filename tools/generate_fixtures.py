#!/usr/bin/env python3
"""Author small CalculiX decks, solve them, and keep the FRD that comes out.

Every element fixture under ``tests/fixtures/elements/`` was written by hand,
which means it encodes what this project *believes* CalculiX writes. That is
the wrong direction of evidence for a reader whose entire job is to read what
CalculiX actually writes: a hand-written fixture and a hand-written reader can
agree with each other and both be wrong about the file on disk.

This script closes that loop. The input decks are written here -- they are ours,
and this repository's MIT licence covers them -- and the FRD files are produced
by running CalculiX over them, so the fixtures are genuine solver output.

That distinction is also why CalculiX's own regression suite is not vendored
instead, which would be the obvious shortcut. That suite is GPL. Writing our own
decks and solving them gives authentic output without taking on a licence this
project cannot carry; ``doc/parity.md`` covers the sweep that *does* use the
GPL corpus, out of tree.

Requires ``ccx`` on PATH. Regenerate with:

    python tools/generate_fixtures.py --out tests/fixtures/generated
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import NamedTuple

# Node tables for one element of each type, in CalculiX's (Abaqus') ordering.
# Coordinates are deliberately not on a unit grid: a fixture whose numbers are
# all 0 and 1 cannot catch an axis swap, and several of these types differ from
# each other only in the order their nodes are listed.
CUBE = [
    (0.0, 0.0, 0.0),
    (2.0, 0.0, 0.0),
    (2.0, 3.0, 0.0),
    (0.0, 3.0, 0.0),
    (0.0, 0.0, 5.0),
    (2.0, 0.0, 5.0),
    (2.0, 3.0, 5.0),
    (0.0, 3.0, 5.0),
]


def _mid(a, b):
    return tuple((x + y) / 2 for x, y in zip(a, b, strict=True))


def _hex20():
    c = CUBE
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    return c + [_mid(c[i], c[j]) for i, j in edges]


TET = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 5.0)]


def _tet10():
    t = TET
    edges = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3)]
    return t + [_mid(t[i], t[j]) for i, j in edges]


WEDGE = [
    (0.0, 0.0, 0.0),
    (2.0, 0.0, 0.0),
    (0.0, 3.0, 0.0),
    (0.0, 0.0, 5.0),
    (2.0, 0.0, 5.0),
    (0.0, 3.0, 5.0),
]


def _wedge15():
    w = WEDGE
    edges = [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (0, 3), (1, 4), (2, 5)]
    return w + [_mid(w[i], w[j]) for i, j in edges]


PYRAMID = [
    (0.0, 0.0, 0.0),
    (2.0, 0.0, 0.0),
    (2.0, 3.0, 0.0),
    (0.0, 3.0, 0.0),
    (1.0, 1.5, 5.0),
]


def _pyramid13():
    p = PYRAMID
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4)]
    return p + [_mid(p[i], p[j]) for i, j in edges]


QUAD = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 3.0, 0.0), (0.0, 3.0, 0.0)]


def _quad8():
    q = QUAD
    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
    return q + [_mid(q[i], q[j]) for i, j in edges]


TRI = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0)]


def _tri6():
    t = TRI
    edges = [(0, 1), (1, 2), (2, 0)]
    return t + [_mid(t[i], t[j]) for i, j in edges]


BEAM2 = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)]
BEAM3 = [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (2.5, 0.0, 0.0)]


class Case(NamedTuple):
    """One deck: an element type, the single element's nodes, and how it is held."""

    name: str
    etype: str
    nodes: list[tuple[float, float, float]]
    section: str | None
    fixed: tuple[int, ...]
    loaded: tuple[int, ...]
    steps: int = 1


CASES = [
    Case('hex8', 'C3D8', CUBE, None, (1, 2, 3, 4), (5, 6, 7, 8), 3),
    Case('hex20', 'C3D20', _hex20(), None, (1, 2, 3, 4, 9, 10, 11, 12), (5, 6, 7, 8)),
    Case('tet4', 'C3D4', TET, None, (1, 2, 3), (4,), 3),
    Case('tet10', 'C3D10', _tet10(), None, (1, 2, 3, 5, 6, 7), (4,)),
    Case('wedge6', 'C3D6', WEDGE, None, (1, 2, 3), (4, 5, 6)),
    Case('wedge15', 'C3D15', _wedge15(), None, (1, 2, 3, 7, 8, 9), (4, 5, 6)),
    Case('quad4', 'S4', QUAD, '*SHELL SECTION, ELSET=EALL, MATERIAL=STEEL\n0.1', (1, 4), (2, 3)),
    Case(
        'quad8',
        'S8',
        _quad8(),
        '*SHELL SECTION, ELSET=EALL, MATERIAL=STEEL\n0.1',
        (1, 4, 8),
        (2, 3),
    ),
    Case('tri3', 'S3', TRI, '*SHELL SECTION, ELSET=EALL, MATERIAL=STEEL\n0.1', (1, 3), (2,)),
    Case('tri6', 'S6', _tri6(), '*SHELL SECTION, ELSET=EALL, MATERIAL=STEEL\n0.1', (1, 3, 6), (2,)),
    Case(
        'beam2',
        'B31',
        BEAM2,
        '*BEAM SECTION, ELSET=EALL, MATERIAL=STEEL, SECTION=RECT\n0.1, 0.1\n0.,0.,1.',
        (1,),
        (2,),
    ),
    Case(
        'beam3',
        'B32',
        BEAM3,
        '*BEAM SECTION, ELSET=EALL, MATERIAL=STEEL, SECTION=RECT\n0.1, 0.1\n0.,0.,1.',
        (1,),
        (2,),
    ),
]

# Deliberately absent: C3D5 and C3D13, the pyramids this reader supports as
# PY5 and PY13 by way of pyvista#8936.
#
# CalculiX 2.22 answers `*ERROR reading *ELEMENT: C3D5 is an unknown element
# type` and stops. That is not a quirk of one version or one deck: a census of
# the 688 FRD files solved from CalculiX's own 2.23 regression suite finds 12
# distinct VTK cell types across 295,626 cells and **no pyramid among them**,
# and none of the 673 official decks mentions C3D5 or C3D13 either.
#
# So the pyramid support cannot be given an authentic fixture. Whatever writes
# PY5 and PY13 records into an FRD file, it is not this solver, and the
# hand-written tests/fixtures/elements/PY5.frd and PY13.frd remain the only
# evidence available -- which is worth knowing when reading them, because it
# means they are the one corner of the element table that no official file
# corroborates. See doc/parity.md.


def deck(case: Case) -> str:
    """One element, one material, fixed on one side and pulled on the other."""
    lines = [
        f'** {case.name}: a single {case.etype}, written by tools/generate_fixtures.py',
        '*NODE, NSET=NALL',
    ]
    lines += [f'{i}, {x:.6f}, {y:.6f}, {z:.6f}' for i, (x, y, z) in enumerate(case.nodes, 1)]
    lines.append(f'*ELEMENT, TYPE={case.etype}, ELSET=EALL')
    # CalculiX allows at most 16 comma-separated entries per input line, so a
    # 20-node brick has to continue onto a second. Getting this wrong does not
    # produce a parse error you can read: ccx reports the whole element line
    # back at you as the message, which is why it is spelled out here.
    fields = ['1', *(str(i) for i in range(1, len(case.nodes) + 1))]
    lines.append(', '.join(fields[:16]))
    for start in range(16, len(fields), 16):
        lines.append(', '.join(fields[start : start + 16]))
    lines += ['*MATERIAL, NAME=STEEL', '*ELASTIC', '210000.0, 0.3']
    lines.append(case.section or '*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL')
    lines.append('*BOUNDARY')
    lines += [f'{n}, 1, 3, 0.0' for n in case.fixed]
    for step in range(1, case.steps + 1):
        lines += ['*STEP', '*STATIC', '*CLOAD']
        lines += [f'{n}, 3, {100.0 * step}' for n in case.loaded]
        lines += [
            '*NODE FILE',
            'U',
            '*EL FILE',
            'S, E',
            '*END STEP',
        ]
    return '\n'.join(lines) + '\n'


def solve(source: str, name: str, out: Path) -> tuple[bool, str]:
    """Run ccx over one deck in a scratch directory and keep the FRD."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / f'{name}.inp').write_text(source)
        try:
            run = subprocess.run(
                ['ccx', '-i', name],
                check=False,
                cwd=work,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            return False, 'ccx is not on PATH'
        except subprocess.TimeoutExpired:
            return False, 'ccx timed out'
        frd = work / f'{name}.frd'
        if not frd.exists() or frd.stat().st_size == 0:
            tail = (run.stdout or run.stderr).strip().splitlines()
            return False, tail[-1][:120] if tail else f'no FRD produced (exit {run.returncode})'
        shutil.copy(frd, out / f'{name}.frd')
        return True, f'{frd.stat().st_size} bytes'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('tests/fixtures/generated'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'src').mkdir(exist_ok=True)

    ok = failed = 0
    for case in CASES:
        source = deck(case)
        (args.out / 'src' / f'{case.name}.inp').write_text(source)
        good, detail = solve(source, case.name, args.out)
        print(f'  {"ok  " if good else "FAIL"} {case.name:12s} {case.etype:6s} {detail}')
        ok, failed = (ok + 1, failed) if good else (ok, failed + 1)

    print(f'\n{ok} solved, {failed} failed')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
