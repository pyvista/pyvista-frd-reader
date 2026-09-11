#!/usr/bin/env python3
"""Audit named surfaces in public input decks and all available FRD time steps.

Unit tests independently pin face numbering and midside connectivity. This
external sweep checks compatibility, parent membership, data transfer, and
missing-ID reporting. Every rejection and unpaired deck is retained in JSON.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np

from pyvista_frd import FRDReader
from pyvista_frd import read_sets
from pyvista_frd.surfaces import extract_surface


def verify(mesh, result, definition):
    original = {str(nid): i for i, nid in enumerate(mesh['original_node_ids'])}
    selected = [original[str(nid)] for nid in result['original_node_ids']]
    for name in mesh.point_data:
        np.testing.assert_array_equal(result.point_data[name], mesh.point_data[name][selected])
    np.testing.assert_array_equal(result.points, mesh.points[selected])
    if definition.kind == 'NODE':
        actual = result['original_node_ids'].astype(int).tolist()
        expected = set(definition.node_ids) & {int(nid) for nid in original}
        assert len(actual) == len(expected) == result.n_cells
        assert set(actual) == expected
        assert set(result.field_data['missing_node_ids']) == set(definition.node_ids) - expected
        return
    parents = {int(eid): i for i, eid in enumerate(mesh['original_element_ids'])}
    refs = {(eid, label) for eid, label in definition.element_faces if eid in parents}
    actual = list(
        zip(result['original_element_ids'].astype(int), result['surface_face_labels'], strict=True)
    )
    assert len(actual) == len(refs) == result.n_cells
    assert set(actual) == refs
    assert set(result.field_data['missing_element_ids']) == {
        eid for eid, _ in definition.element_faces if eid not in parents
    }
    for i, (eid, label) in enumerate(
        zip(result['original_element_ids'], result['surface_face_labels'], strict=True)
    ):
        assert (int(eid), str(label)) in refs
        parent = mesh.get_cell(parents[int(eid)])
        cell = result.get_cell(i)
        parent_ids = set(mesh['original_node_ids'][parent.point_ids])
        assert set(result['original_node_ids'][cell.point_ids]) <= parent_ids
    parent_rows = [parents[int(eid)] for eid in result['original_element_ids']]
    for name in mesh.cell_data:
        np.testing.assert_array_equal(result.cell_data[name], mesh.cell_data[name][parent_rows])


def audit_pair(path, inp):
    reader = FRDReader(path, inp_path=inp)
    rows = {
        name: {
            'name': name,
            'kind': definition.kind,
            'status': 'checked',
            'faces': 0,
            'steps': 0,
            'warnings': [],
            'cell_types': [],
        }
        for name, definition in reader.sets.surfaces.items()
    }
    for step in range(max(1, reader.number_time_points)):
        if reader.number_time_points:
            reader.set_active_time_point(step)
        mesh = reader.read()
        for name, definition in reader.sets.surfaces.items():
            row = rows[name]
            if row['status'] == 'failed':
                continue
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always', UserWarning)
                    result = extract_surface(
                        mesh, definition, reader.sets.element_types, missing='warn'
                    )
                verify(mesh, result, definition)
                row['steps'] += 1
                row['faces'] = result.n_cells
                row['cell_types'] = sorted(set(result.celltypes.tolist()))
                row['warnings'] = sorted(
                    set(row['warnings'])
                    | {str(w.message) for w in caught if issubclass(w.category, UserWarning)}
                )
            except Exception as exc:  # noqa: BLE001 - retain failures, not just successes
                row.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    return {'path': str(path), 'surfaces': list(rows.values())}


def audit(path):
    row = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        data = read_sets(path)
    except (ValueError, OSError) as exc:
        return {**row, 'status': 'rejected', 'error': f'{type(exc).__name__}: {exc}'}
    row.update(
        status='parsed',
        surfaces=len(data.surfaces),
        node_surfaces=sum(s.kind == 'NODE' for s in data.surfaces.values()),
        pairs=[],
    )
    if not data.surfaces:
        return row
    for frd in (path.with_suffix('.frd'), path.with_suffix('.frd.ref')):
        if frd.exists():
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', DeprecationWarning)
                    row['pairs'].append(audit_pair(frd, path))
            except Exception as exc:  # noqa: BLE001
                row['pairs'].append({'path': str(frd), 'error': f'{type(exc).__name__}: {exc}'})
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--json', type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(p for p in args.directory.rglob('*') if p.suffix.lower() in {'.inp', '.sur'})
    if not paths:
        parser.error('no input files found')
    rows = []
    for i, path in enumerate(paths, 1):
        rows.append(audit(path))
        if i % 100 == 0:
            print(i, '/', len(paths), flush=True)
    args.json.write_text(json.dumps(rows, indent=2) + '\n')
    counts = Counter(row['status'] for row in rows)
    surfaces = Counter(
        s['status']
        for row in rows
        for pair in row.get('pairs', [])
        for s in pair.get('surfaces', [])
    )
    print('decks', dict(counts), 'surfaces', dict(surfaces))
    return int(
        counts['rejected'] > 0
        or surfaces['failed'] > 0
        or any('error' in pair for row in rows for pair in row.get('pairs', []))
    )


if __name__ == '__main__':
    raise SystemExit(main())
