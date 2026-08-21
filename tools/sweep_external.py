#!/usr/bin/env python3
"""Grade this reader against PyVista's over a directory of FRD files from elsewhere.

The conformance suite in ``tests/`` runs over ``tests/fixtures/``, which is a
corpus this project authored. That is the right instrument for pinning known
behaviour and the wrong one for finding behaviour nobody has thought of: an
authored corpus can only contain the cases its author already knew about, so a
green sweep over it says the reader agrees with the oracle on the files we
wrote, and nothing at all about the files CalculiX writes in the wild.

This script exists to point the same comparison at a corpus we did not write.
It takes a directory, finds every ``.frd`` under it, and for each one runs both
readers and compares what they produce, to the same two standards the
conformance suite uses -- bit-exact everywhere except the principal values,
which are graded against the magnitude of the tensor they came from.

It is deliberately a script rather than a test. The corpora it is aimed at are
gigabytes of someone else's GPL-licensed regression data; they cannot be
vendored into an MIT repository and should not be a precondition for running
the test suite. What belongs in the repo is this harness, the record of what
it found, and any fixture the sweep proves was missing -- reduced to something
small and written here rather than copied.

Usage:

    python tools/sweep_external.py CORPUS_DIR [--json OUT] [--limit N]
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
import json
from pathlib import Path
import sys
import time
import traceback
import warnings

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pyvista_frd import _capi  # noqa: E402
from pyvista_frd.reader import _default_wedge_order  # noqa: E402
from tests.conformance.ref_frd import _FRDParser  # noqa: E402

EIGEN_TOLERANCE_ULPS = 32.0
_EPS = float(np.finfo(np.float64).eps)


@dataclass
class Result:
    """What the sweep learned about one file."""

    path: str
    size_bytes: int
    verdict: str  # agree | differ | oracle-only | native-only | neither | error
    detail: str = ''
    oracle_seconds: float | None = None
    native_seconds: float | None = None
    n_points: int | None = None
    n_cells: int | None = None
    n_steps: int | None = None
    n_arrays: int | None = None
    worst_eigen_ulps: float | None = None
    differences: list[str] = field(default_factory=list)


def _is_principal(name: str) -> bool:
    return name.endswith(('_PS1', '_PS2', '_PS3'))


def bitwise_equal(a: np.ndarray, b: np.ndarray) -> bool:
    """Compare two float arrays by their bit patterns rather than by value.

    ``==`` is the wrong operator for grading a parser, in two directions that
    both showed up in this corpus.

    It is too strict for NaN. CalculiX writes a literal ``NaN`` into the
    coordinate records of network nodes -- nodes in a fluid deck that have no
    geometric position -- and ``NaN != NaN``, so a plain comparison reported
    three files as divergent when the two readers had produced identical bits.
    That is a false red, and a false red in a sweep this size is worse than it
    sounds: it is the one that trains you to skim the output.

    It is also too weak for zero. ``-0.0 == 0.0`` is true in IEEE 754, so a
    reader that dropped the sign of a negative zero would pass a value
    comparison unnoticed. ``numpy.testing.assert_array_equal`` has the same
    blind spot, which means the conformance suite in ``tests/`` shares it.

    Comparing the raw bits answers both at once: NaNs match when they really
    are the same NaN, and a signed zero is only equal to a signed zero.
    """
    if a.shape != b.shape:
        return False
    if a.dtype != np.float64 or b.dtype != np.float64:
        return np.array_equal(a, b)
    return np.array_equal(
        np.ascontiguousarray(a).view(np.uint64), np.ascontiguousarray(b).view(np.uint64)
    )


def compare(path: Path) -> Result:
    """Read one file both ways and say whether the answers agree."""
    result = Result(path=str(path), size_bytes=path.stat().st_size, verdict='error')

    # Both readers warn about the same things; the diagnostics parity suite
    # grades those separately, and here they would drown the output.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')

        oracle_error = native_error = None
        data = None
        native = None

        start = time.perf_counter()
        try:
            data = _FRDParser(str(path)).parse()
        except Exception as exc:  # noqa: BLE001
            oracle_error = f'{type(exc).__name__}: {exc}'
        result.oracle_seconds = time.perf_counter() - start

        start = time.perf_counter()
        try:
            native = _capi.NativeFile(str(path), wedge_order=_default_wedge_order())
        except Exception as exc:  # noqa: BLE001
            native_error = f'{type(exc).__name__}: {exc}'
        result.native_seconds = time.perf_counter() - start

        if oracle_error and native_error:
            result.verdict = 'neither'
            result.detail = f'oracle: {oracle_error} | native: {native_error}'
            return result
        if oracle_error:
            result.verdict = 'native-only'
            result.detail = f'oracle: {oracle_error}'
            return result
        if native_error:
            result.verdict = 'oracle-only'
            result.detail = f'native: {native_error}'
            return result

        try:
            grid_error = None
            try:
                _FRDParser._build_grid(data, {})
            except Exception as exc:  # noqa: BLE001
                grid_error = f'{type(exc).__name__}: {exc}'

            if grid_error is not None:
                # The oracle parsed the file and then refused to turn it into a
                # grid -- CalculiX writes node-free FRDs for spring-only and
                # substructure decks, and PyVista rejects those rather than
                # returning an empty mesh. That is not an error in the sweep;
                # it is a behaviour to check we reproduce. The question is
                # whether this library refuses in the same way, so ask it at
                # the level where both are comparable: the Python entry point.
                import pyvista_frd

                try:
                    pyvista_frd.read(str(path))
                except Exception as exc:  # noqa: BLE001
                    ours = f'{type(exc).__name__}: {exc}'
                    if ours == grid_error:
                        result.verdict = 'both-decline'
                        result.detail = grid_error
                    else:
                        result.verdict = 'differ'
                        result.detail = f'oracle: {grid_error} | native: {ours}'
                        result.differences = [
                            f'both refuse the file but not alike: {grid_error!r} vs {ours!r}'
                        ]
                else:
                    result.verdict = 'differ'
                    result.detail = grid_error
                    result.differences = [
                        'the oracle refuses to build a grid from this file; this library does not'
                    ]
                return result

            return _compare_contents(result, data, native)
        except Exception:  # noqa: BLE001
            result.verdict = 'error'
            result.detail = traceback.format_exc(limit=6)
            return result
        finally:
            if native is not None:
                native.close()


def _compare_contents(result: Result, data, native) -> Result:
    """Both readers succeeded; now decide whether they said the same thing."""
    differences: list[str] = []
    grid = _FRDParser._build_grid(data, {})

    result.n_points = int(native.n_points)
    result.n_cells = int(native.n_cells)
    result.n_steps = int(native.n_steps)

    if native.n_points != grid.n_points:
        differences.append(f'n_points: native {native.n_points}, oracle {grid.n_points}')
    if native.n_cells != grid.n_cells:
        differences.append(f'n_cells: native {native.n_cells}, oracle {grid.n_cells}')

    if native.n_points == grid.n_points:
        expected_points = np.asarray(grid.points, dtype=np.float64)
        if not bitwise_equal(np.asarray(native.points), expected_points):
            bad = int(np.count_nonzero(native.points != expected_points))
            differences.append(f'points: {bad} of {expected_points.size} values differ')
        expected_ids = np.asarray(grid.point_data['original_node_ids'])
        actual_ids = np.array([str(i) for i in native.node_ids])
        if not np.array_equal(actual_ids, expected_ids):
            differences.append('node ids differ')

    if native.n_cells == grid.n_cells:
        if not np.array_equal(native.cell_types, grid.celltypes):
            bad = int(np.count_nonzero(native.cell_types != grid.celltypes))
            differences.append(f'cell types: {bad} of {grid.n_cells} differ')
        if not np.array_equal(native.cell_offsets, grid.offset):
            differences.append('cell offsets differ')
        if not np.array_equal(native.cell_connectivity, grid.cell_connectivity):
            differences.append('cell connectivity differs')

    expected_times = sorted(data.results_by_step)
    if native.step_times != expected_times:
        differences.append(
            f'step times: native {len(native.step_times)} steps, oracle {len(expected_times)}'
        )
    else:
        worst = 0.0
        arrays = 0
        for step_index, step_time in enumerate(expected_times):
            step_grid = _FRDParser._build_grid(data, data.results_by_step[step_time])
            expected_names = [n for n in step_grid.point_data if n != 'original_node_ids']
            got = native.array_infos(step_index)
            arrays += len(got)
            if [name for name, _, _ in got] != expected_names:
                differences.append(
                    f'step {step_time}: array names differ '
                    f'(native {[n for n, _, _ in got]}, oracle {expected_names})'
                )
                continue
            for index, (name, _n_components, _kind) in enumerate(got):
                reference = np.asarray(step_grid.point_data[name], dtype=np.float64)
                actual = native.array(step_index, index)
                if actual.shape != reference.shape:
                    differences.append(
                        f'step {step_time} {name}: shape {actual.shape} vs {reference.shape}'
                    )
                    continue
                if not _is_principal(name):
                    if not bitwise_equal(np.asarray(actual, dtype=np.float64), reference):
                        bad = int(np.count_nonzero(actual != reference))
                        worst_abs = float(np.max(np.abs(actual - reference)))
                        differences.append(
                            f'step {step_time} {name}: {bad} of {reference.size} values differ, '
                            f'largest by {worst_abs:.3e}'
                        )
                    continue
                base = name.rsplit('_', 1)[0]
                tensor = np.asarray(step_grid.point_data[base], dtype=np.float64)
                scale = np.linalg.norm(tensor, axis=1)
                error = np.abs(actual - reference)
                scaled = np.where(
                    scale > 0.0, error / np.maximum(scale, np.finfo(float).tiny), error
                )
                # A NaN anywhere makes max() return NaN, and `NaN > bound` is
                # False -- the band would silently pass. Grade the NaNs
                # structurally and the numbers numerically.
                if not np.array_equal(np.isnan(actual), np.isnan(reference)):
                    differences.append(f'step {step_time} {name}: NaNs in different places')
                    continue
                finite = ~np.isnan(scaled)
                measured = float(np.max(scaled[finite])) / _EPS if finite.any() else 0.0
                worst = max(worst, measured)
                if measured > EIGEN_TOLERANCE_ULPS:
                    differences.append(
                        f'step {step_time} {name}: eigenvalue error {measured:.1f} ulp '
                        f'exceeds the {EIGEN_TOLERANCE_ULPS} ulp band'
                    )
        result.n_arrays = arrays
        result.worst_eigen_ulps = worst

    result.differences = differences
    result.verdict = 'agree' if not differences else 'differ'
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--json', type=Path, help='write the full result set here')
    parser.add_argument('--limit', type=int, help='stop after this many files')
    parser.add_argument('--quiet', action='store_true', help='only print non-agreeing files')
    args = parser.parse_args()

    paths = sorted(p for p in args.directory.rglob('*') if p.suffix.lower() == '.frd')
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print(f'no .frd files under {args.directory}', file=sys.stderr)
        return 1

    results = []
    counts: dict[str, int] = {}
    for i, path in enumerate(paths, 1):
        result = compare(path)
        results.append(result)
        counts[result.verdict] = counts.get(result.verdict, 0) + 1
        if not args.quiet or result.verdict != 'agree':
            rel = path.relative_to(args.directory)
            mb = result.size_bytes / 1048576
            print(f'[{i}/{len(paths)}] {result.verdict:12s} {mb:7.2f} MB  {rel}')
            for line in result.differences[:8]:
                print(f'        {line}')
            if result.detail:
                print(f'        {result.detail.splitlines()[-1][:200]}')

    print()
    print('=' * 70)
    for verdict, count in sorted(counts.items()):
        print(f'{verdict:14s} {count}')
    print(f'{"total":14s} {len(results)}')

    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2))
        print(f'\nwritten to {args.json}')

    return 0 if set(counts) <= {'agree'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
