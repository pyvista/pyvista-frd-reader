#!/usr/bin/env python3
"""Solve the decks the documentation examples read.

Same arrangement as ``tools/generate_fixtures.py`` and for the same reason: the
input decks are ours and MIT, the ``.frd`` files beside them are what CalculiX
produced from them. A gallery that read hand-written FRD would be showing what
this project believes CalculiX writes, which is the thing the rest of the
repository goes to some length not to do.

Usage::

    python tools/generate_docs_data.py --ccx ccx
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent.parent
LENGTH, WIDTH, HEIGHT = 150.0, 20.0, 20.0


def _grid(nx: int, ny: int, nz: int):
    """Return nodes and hex8 elements of a structured box, 1-based."""
    nodes = {}
    nid = 0
    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                nid += 1
                nodes[i, j, k] = (nid, i * LENGTH / nx, j * WIDTH / ny, k * HEIGHT / nz)
    elements = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                c = [
                    nodes[i, j, k][0],
                    nodes[i + 1, j, k][0],
                    nodes[i + 1, j + 1, k][0],
                    nodes[i, j + 1, k][0],
                    nodes[i, j, k + 1][0],
                    nodes[i + 1, j, k + 1][0],
                    nodes[i + 1, j + 1, k + 1][0],
                    nodes[i, j + 1, k + 1][0],
                ]
                elements.append((len(elements) + 1, c))
    return nodes, elements


def _deck(nx: int, ny: int, nz: int, analysis: str) -> str:
    """Return an Abaqus-syntax deck for a fixed-free beam of ``nx * ny * nz`` hexahedra."""
    nodes, elements = _grid(nx, ny, nz)
    out = ['*NODE, NSET=NALL']
    for (i, _j, _k), (nid, x, y, z) in sorted(nodes.items(), key=lambda kv: kv[1][0]):
        _ = i
        out.append(f'{nid}, {x:.6f}, {y:.6f}, {z:.6f}')
    out.append('*ELEMENT, TYPE=C3D8, ELSET=EALL')
    for eid, conn in elements:
        out.append(f'{eid}, ' + ', '.join(str(c) for c in conn))

    fixed = sorted(nid for (i, _j, _k), (nid, *_) in nodes.items() if i == 0)
    tip = sorted(nid for (i, _j, _k), (nid, *_) in nodes.items() if i == nx)
    out.append('*NSET, NSET=FIXED')
    out.extend(', '.join(str(n) for n in fixed[c : c + 8]) for c in range(0, len(fixed), 8))
    out.append('*NSET, NSET=TIP')
    out.extend(', '.join(str(n) for n in tip[c : c + 8]) for c in range(0, len(tip), 8))

    out += [
        '*MATERIAL, NAME=STEEL',
        '*ELASTIC',
        '210000.0, 0.3',
        '*DENSITY',
        '7.85E-9',
        '*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL',
        '*BOUNDARY',
        'FIXED, 1, 3',
    ]
    if analysis == 'static':
        out += [
            '*STEP',
            '*STATIC',
            '*CLOAD',
            f'TIP, 3, {-60.0 / len(tip):.6f}',
            '*NODE FILE',
            'U',
            '*EL FILE',
            'S, E',
            '*END STEP',
        ]
    else:
        out += [
            '*STEP',
            '*FREQUENCY, STORAGE=NO',
            '6',
            # Displacement only. The example that reads this file plots mode
            # shapes; a stress block per mode would triple the file for
            # something no page shows.
            '*NODE FILE',
            'U',
            '*END STEP',
        ]
    return '\n'.join(out) + '\n'


# Both beams are 150 x 20 x 20. The element counts are what keeps each FRD
# under the repository's 500 KB file limit with its result blocks in it.
DECKS = {
    'cantilever': {'nx': 24, 'ny': 5, 'nz': 5, 'analysis': 'static'},
    'modes': {'nx': 24, 'ny': 5, 'nz': 5, 'analysis': 'frequency'},
}


def main() -> int:
    """Write every deck, solve it, and copy the FRD next to the source."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ccx', default='ccx', help='CalculiX executable')
    parser.add_argument('--out', type=Path, default=HERE / 'doc' / '_data')
    args = parser.parse_args()

    if shutil.which(args.ccx) is None:
        print(f'{args.ccx} not found; nothing to do')
        return 1

    src = args.out / 'src'
    src.mkdir(parents=True, exist_ok=True)
    for name, spec in DECKS.items():
        text = _deck(**spec)
        (src / f'{name}.inp').write_text(text)
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / name
            job.with_suffix('.inp').write_text(text)
            subprocess.run([args.ccx, '-i', str(job)], check=False, capture_output=True, cwd=tmp)
            frd = job.with_suffix('.frd')
            if not frd.exists() or frd.stat().st_size == 0:
                print(f'{name}: no FRD produced')
                return 1
            shutil.copy(frd, args.out / f'{name}.frd')
            kb = (args.out / f'{name}.frd').stat().st_size / 1024
            print(f'{name}.frd  {kb:8.0f} KB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
