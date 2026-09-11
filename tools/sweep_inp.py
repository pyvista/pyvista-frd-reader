#!/usr/bin/env python3
"""Audit external INP parsing and companion FRD set mapping.

This is a compatibility sweep, not an independent oracle for INP semantics.
Authored unit tests pin those semantics. Here every deck is attempted, failures
are recorded, and available companion FRDs are checked at every time step for
exact membership mapping and unchanged geometry/results. Returns nonzero for
any rejected input or failed check; the JSON distinguishes these outcomes.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np

import pyvista_frd


def check_pair(path, inp, sets):
    reader = pyvista_frd.FRDReader(path, inp_path=inp)
    plain = pyvista_frd.FRDReader(path)
    point_ids = plain._file.node_ids.tolist()
    cell_ids = plain._file.cell_ids.tolist()
    point_masks = {
        f'NSET:{name}': [i in set_ids for i in point_ids]
        for name, ids in sets.node_sets.items()
        for set_ids in [set(ids.tolist())]
    }
    cell_masks = {
        f'ELSET:{name}': [i in set_ids for i in cell_ids]
        for name, ids in sets.element_sets.items()
        for set_ids in [set(ids.tolist())]
    }
    for step in range(max(1, reader.number_time_points)):
        if reader.number_time_points:
            reader.set_active_time_point(step)
            plain.set_active_time_point(step)
        actual, expected = reader.read(), plain.read()
        for left, right in [
            (actual.points, expected.points),
            (actual.cells, expected.cells),
            (actual.celltypes, expected.celltypes),
        ]:
            np.testing.assert_array_equal(left, right)
        for name in expected.point_data:
            np.testing.assert_array_equal(actual.point_data[name], expected.point_data[name])
        for name, mask in point_masks.items():
            np.testing.assert_array_equal(actual.point_data[name], mask)
        for name, mask in cell_masks.items():
            np.testing.assert_array_equal(actual.cell_data[name], mask)
    return {
        'frd': str(path),
        'status': 'checked',
        'steps': max(1, reader.number_time_points),
        'point_masks': len(point_masks),
        'cell_masks': len(cell_masks),
    }


def audit(path):
    row = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        sets = pyvista_frd.read_sets(path)
    except (OSError, ValueError) as exc:
        row.update(status='rejected', error=f'{type(exc).__name__}: {exc}')
        return row
    row.update(status='parsed', node_sets=len(sets.node_sets), element_sets=len(sets.element_sets))
    row['pairs'] = []
    for companion in (path.with_suffix('.frd'), path.with_suffix('.frd.ref')):
        if not companion.exists():
            continue
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                result = check_pair(companion, path, sets)
            result['warnings'] = sorted({str(w.message) for w in caught})
        except Exception as exc:  # noqa: BLE001 - preserve every failure in the audit
            result = {
                'frd': str(companion),
                'status': 'failed',
                'error': f'{type(exc).__name__}: {exc}',
            }
        row['pairs'].append(result)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--json', type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(p for p in args.directory.rglob('*') if p.suffix.lower() == '.inp')
    if not paths:
        parser.error('no INP files found')
    rows = []
    for index, path in enumerate(paths, 1):
        rows.append(audit(path))
        if index % 100 == 0:
            print(f'{index}/{len(paths)} decks', flush=True)
    args.json.write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
    counts = Counter(row['status'] for row in rows)
    pairs = Counter(pair['status'] for row in rows for pair in row.get('pairs', []))
    print(f'Decks: {dict(counts)}; companions: {dict(pairs)}; report: {args.json}')
    return int(counts['rejected'] > 0 or pairs['failed'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
