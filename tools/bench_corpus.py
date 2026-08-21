#!/usr/bin/env python3
"""Time both readers over a corpus, with both made to do the same work.

The naive measurement flatters this library and should not be quoted. Opening
a file here indexes the blocks and stops; a step's values are parsed when that
step is first asked for. PyVista's reader parses every value of every step
during ``parse()``. Timing "open" against "parse" therefore compares a full
read against an index build, and the ratio it reports is partly just the work
this library has not done yet.

So both sides are driven to the same end state: every array of every step
materialised as a NumPy array. That is the number a caller who actually wants
the results would see.

Two figures are reported per file, because they answer different questions.
The **total** is what a user waits for. The **ratio** is what changed by
rewriting the reader, and the median ratio across a corpus is a more honest
summary than any single file, which is why the corpus matters here at all:
a benchmark on one hand-picked file measures that file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
import warnings

import numpy as np

MB = 1024 * 1024
SMALL_FILE_BYTES = 64 * 1024
SKIPS_LISTED = 10

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pyvista_frd import _capi  # noqa: E402
from pyvista_frd.reader import _default_wedge_order  # noqa: E402
from tests.conformance.ref_frd import _FRDParser  # noqa: E402


def time_oracle(path: Path) -> float:
    """Parse and materialise every array, the way PyVista's reader does."""
    start = time.perf_counter()
    data = _FRDParser(str(path)).parse()
    for step_time in sorted(data.results_by_step):
        grid = _FRDParser._build_grid(data, data.results_by_step[step_time])
        for name in grid.point_data:
            np.asarray(grid.point_data[name])
    return time.perf_counter() - start


def time_native(path: Path) -> float:
    """Open and materialise every array, so both sides end up in the same place."""
    start = time.perf_counter()
    native = _capi.NativeFile(str(path), wedge_order=_default_wedge_order())
    try:
        np.asarray(native.points)
        np.asarray(native.cell_connectivity)
        for step_index in range(native.n_steps):
            for index, _info in enumerate(native.array_infos(step_index)):
                np.asarray(native.array(step_index, index))
    finally:
        native.close()
    return time.perf_counter() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--repeats', type=int, default=3, help='best of N, to shed scheduler noise')
    parser.add_argument('--min-bytes', type=int, default=0)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()

    paths = sorted(
        p
        for p in args.directory.rglob('*')
        if p.suffix.lower() == '.frd' and p.stat().st_size >= args.min_bytes
    )
    rows = []
    skipped: list[tuple[Path, str]] = []
    warnings.simplefilter('ignore')
    for i, path in enumerate(paths, 1):
        try:
            oracle = min(time_oracle(path) for _ in range(args.repeats))
            native = min(time_native(path) for _ in range(args.repeats))
        except Exception as exc:  # noqa: BLE001
            # Named, not swallowed. A benchmark that quietly drops the files it
            # could not time reports a mean over a corpus it did not measure,
            # and the drop is invisible in exactly the case where it matters --
            # when the unreadable files are the interesting ones.
            skipped.append((path, f'{type(exc).__name__}: {exc}'))
            continue
        rows.append(
            {
                'path': str(path),
                'bytes': path.stat().st_size,
                'oracle_s': oracle,
                'native_s': native,
                'ratio': oracle / native if native > 0 else None,
            }
        )
        if i % 100 == 0:
            print(f'  {i}/{len(paths)}', file=sys.stderr)

    ratios = np.array([r['ratio'] for r in rows if r['ratio']])
    sizes = np.array([r['bytes'] for r in rows if r['ratio']])
    oracle_total = sum(r['oracle_s'] for r in rows)
    native_total = sum(r['native_s'] for r in rows)

    print(f'\nfiles timed          {len(rows)}')
    print(f'bytes read           {sizes.sum() / MB:.1f} MB')
    print(f'PyVista total        {oracle_total:.2f} s')
    print(f'this library total   {native_total:.2f} s')
    print(f'aggregate speedup    {oracle_total / native_total:.2f}x')
    print()
    print('per-file speedup distribution')
    for q in (0, 10, 25, 50, 75, 90, 100):
        print(f'  p{q:<3d} {np.percentile(ratios, q):6.2f}x')
    print(f'  slower than PyVista on {int((ratios < 1).sum())} of {len(ratios)} files')

    big = sizes >= MB
    if big.any():
        print(f'\nfiles over 1 MB ({int(big.sum())}): median {np.median(ratios[big]):.2f}x')
    small = sizes < SMALL_FILE_BYTES
    if small.any():
        print(f'files under 64 KB ({int(small.sum())}): median {np.median(ratios[small]):.2f}x')

    if skipped:
        print(f'\nnot timed: {len(skipped)} of {len(paths)} files')
        for path, why in skipped[:SKIPS_LISTED]:
            print(f'  {path.name}: {why[:110]}')
        if len(skipped) > SKIPS_LISTED:
            print(f'  ... and {len(skipped) - SKIPS_LISTED} more')

    if args.json:
        args.json.write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
