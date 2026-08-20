"""Compare this reader with PyVista's on the same files.

Speed is not why this library exists -- multi-language reuse is -- but "why
C++" invites the question, so it is measured rather than asserted.

Two rules the numbers depend on:

- **Arms are interleaved, not run in sequence.** A shared machine drifts:
  another process starts, a core parks, the file leaves page cache. Running
  all of A then all of B attributes that drift to whichever arm ran during it.
- **The first read of a file is discarded.** It measures the disk, not the
  parser, and it measures it for exactly one arm.

Usage::

    python benchmarks/read_speed.py [--repeats 7] [FILE ...]

With no files, it uses the committed corpus's real CalculiX file and a
synthetic file large enough to be worth timing.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).parent.parent / 'tests'))

from conformance.ref_frd import _FRDParser

import pyvista_frd

FIXTURES = Path(__file__).parent.parent / 'tests' / 'fixtures'


def synthetic(path: Path, n_nodes: int = 40000, n_steps: int = 3) -> Path:
    """Write a file big enough that the parse dominates the timing."""
    lines = ['1C synthetic', '2C']
    for i in range(1, n_nodes + 1):
        lines.append(f' -1{i:10d} {i * 1e-3:.5E} {i * 2e-3:.5E} {i * 3e-3:.5E}')
    lines.append(' -3')
    lines.append('3C')
    for e in range(1, n_nodes // 8 + 1):
        base = (e - 1) * 8 + 1
        ids = ''.join(f'{base + k:10d}' for k in range(8))
        lines.append(f' -1{e:10d}{1:5d}')
        lines.append(f' -2{ids}')
    lines.append(' -3')
    for s in range(1, n_steps + 1):
        lines.append(f'  100CL  10{s} {s}.00000E+00')
        lines.append(' -4  STRESS      6    1')
        for i in range(1, n_nodes + 1):
            v = i * 1e-2
            lines.append(
                f' -1{i:10d} {v:.5E} {v * 2:.5E} {v * 3:.5E} '
                f'{v * 0.1:.5E} {v * 0.2:.5E} {v * 0.3:.5E}'
            )
        lines.append(' -3')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def time_native(path: Path) -> float:
    start = time.perf_counter()
    reader = pyvista_frd.FRDReader(path)
    reader.read()
    return time.perf_counter() - start


def time_reference(path: Path) -> float:
    start = time.perf_counter()
    data = _FRDParser(str(path)).parse()
    steps = sorted(data.results_by_step)
    _FRDParser._build_grid(data, data.results_by_step[steps[0]] if steps else {})
    return time.perf_counter() - start


def compare(path: Path, repeats: int) -> None:
    # Discarded: the first read of a file measures the disk, and it would
    # measure it for whichever arm happened to go first.
    time_native(path)
    time_reference(path)

    native: list[float] = []
    reference: list[float] = []
    for _ in range(repeats):
        # Interleaved, and the order alternates, so a machine that drifts
        # during the run drifts through both arms rather than one.
        native.append(time_native(path))
        reference.append(time_reference(path))
        reference.append(time_reference(path))
        native.append(time_native(path))

    n = statistics.median(native)
    r = statistics.median(reference)
    print(f'{path.name} ({path.stat().st_size / 1e6:.2f} MB)')
    print(
        f'  pyvista_frd  median {n * 1e3:8.2f} ms   spread {min(native) * 1e3:.2f}-{max(native) * 1e3:.2f}'
    )
    print(
        f'  pyvista      median {r * 1e3:8.2f} ms   spread {min(reference) * 1e3:.2f}-{max(reference) * 1e3:.2f}'
    )
    print(f'  ratio        {r / n:.1f}x')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', type=Path)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()

    files = args.files
    scratch = None
    if not files:
        scratch = Path(tempfile.mkdtemp(prefix='frd-bench-'))
        files = [FIXTURES / 'mesh.frd', synthetic(scratch / 'synthetic.frd')]

    for path in files:
        compare(path, args.repeats)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
