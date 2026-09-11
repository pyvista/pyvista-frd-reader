"""Extract CalculiX named surfaces while retaining FRD result arrays.

Face labels follow *SURFACE in the CalculiX 2.23 manual. VTK supplies the
higher-order face/edge connectivity; its face *indices* are never treated as
CalculiX face numbers. See doc/surfaces.md for the mapping and provenance.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING
import warnings

import numpy as np
import pyvista as pv

from .sets import _element_size

if TYPE_CHECKING:
    from .sets import INPSurface

# Corner memberships in CalculiX local numbering (zero based). Winding is
# supplied by the corresponding VTK face, including all midside nodes.
_HEX = ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0))
_TET = ((0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0))
_WEDGE = ((0, 1, 2), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5))
_SOLIDS = {12: _HEX, 25: _HEX, 10: _TET, 24: _TET, 13: _WEDGE, 26: _WEDGE}
_PLANAR = {5: 3, 22: 3, 9: 4, 23: 4}
_REVERSE = {5: (0, 2, 1), 22: (0, 2, 1, 5, 4, 3), 9: (0, 3, 2, 1), 23: (0, 3, 2, 1, 7, 6, 5, 4)}


@lru_cache(maxsize=32)
def _topology(cell_type: int, n_points: int) -> tuple[tuple, tuple]:
    """Get local VTK face/edge connectivity from a cell with unique IDs."""
    template = pv.UnstructuredGrid(
        np.r_[n_points, np.arange(n_points)],
        [cell_type],
        np.zeros((n_points, 3)),
    ).get_cell(0)
    faces = []
    for face in template.faces:
        indices = tuple(face.point_ids)
        if cell_type == pv.CellType.QUADRATIC_WEDGE:
            # Older VTK releases return inward-wound quadratic wedge faces.
            # Normalize on the reference cell, never on distorted user geometry.
            reference = np.asarray(template.GetParametricCoords()).reshape(-1, 3)
            a, b, c = reference[list(indices[:3])]
            normal = np.cross(b - a, c - a)
            if np.dot(normal, a - reference.mean(axis=0)) < 0:
                indices = tuple(indices[i] for i in _REVERSE[int(face.type)])
        faces.append((int(face.type), indices))
    edges = tuple((int(edge.type), tuple(edge.point_ids)) for edge in template.edges)
    return tuple(faces), edges


def _family(source_type: str) -> str:
    if source_type.startswith(('CPS', 'CPE', 'CAX')):
        return 'plane'
    if (source_type.startswith('S') and source_type[1:2].isdigit()) or source_type.startswith(
        'M3D'
    ):
        return 'shell'
    if source_type.startswith('B'):
        return 'beam'
    if source_type.startswith(('C3D', 'DC3D', 'F3D')) or not source_type:
        return 'solid'
    msg = f'unsupported input element type {source_type!r} for surface extraction'
    raise ValueError(msg)


def _face_number(label: str, source_type: str, family: str) -> int:
    if label in {'SNEG', 'SPOS'} and family == 'shell':
        return 1 if label == 'SNEG' else 2
    if label in {'SN', 'SP'} and source_type.startswith('CPS'):
        return 1 if label == 'SN' else 2
    if len(label) == 2 and label[0] == 'S' and label[1].isdigit():  # noqa: PLR2004
        return int(label[1])
    msg = f'face {label!r} is not valid for input element type {source_type or "unknown"}'
    raise ValueError(msg)


def _validate_source_face(number: int, label: str, source_type: str, family: str) -> None:
    count = _element_size(source_type)
    if family in {'plane', 'shell'} and count is not None:
        corners = 3 if count in {3, 6} else 4
        maximum = corners if family == 'plane' else corners + 2
        if label not in {'SN', 'SP', 'SNEG', 'SPOS'} and not 1 <= number <= maximum:
            msg = f'face {label} is invalid for {source_type}'
            raise ValueError(msg)


def _solid_face(
    cell_type: int, n_points: int, label: str, source_type: str
) -> tuple[int, tuple[int, ...]]:
    family = _family(source_type)
    number = _face_number(label, source_type, family)
    _validate_source_face(number, label, source_type, family)
    faces, _ = _topology(cell_type, n_points)
    if family == 'plane' and label not in {'SN', 'SP'}:
        number += 2
    if family == 'beam' and number not in {1, 2, 3, 5}:
        msg = f'face {label} is not a documented beam face'
        raise ValueError(msg)
    expected = {4: _TET, 10: _TET, 6: _WEDGE, 15: _WEDGE, 8: _HEX, 20: _HEX}
    if (
        family == 'solid'
        and source_type
        and expected.get(_element_size(source_type)) != _SOLIDS[cell_type]
    ):
        msg = f'input element type {source_type} does not match VTK cell type {cell_type}'
        raise ValueError(msg)
    mapping = _SOLIDS[cell_type]
    if not 1 <= number <= len(mapping):
        msg = f'face {label} is outside the supported faces for {source_type or cell_type}'
        raise ValueError(msg)
    corners = mapping[number - 1]
    if cell_type == pv.CellType.WEDGE and pv.vtk_version_info < (9, 7):
        order = (0, 2, 1, 3, 5, 4)
        corners = tuple(order[i] for i in corners)
    for face_type, indices in faces:
        if set(indices[: len(corners)]) == set(corners):
            return face_type, indices
    msg = f'VTK cell {cell_type} has no face matching {label}'
    raise ValueError(msg)


def _face_connectivity(
    cell_type: int,
    n_points: int,
    label: str,
    source_type: str,
) -> tuple[int, tuple[int, ...]]:
    if source_type.startswith('U') and cell_type in _PLANAR and label in {'SNEG', 'SPOS'}:
        return cell_type, _REVERSE[cell_type] if label == 'SNEG' else tuple(range(n_points))
    family = _family(source_type)
    number = _face_number(label, source_type, family)
    _validate_source_face(number, label, source_type, family)
    _, edges = _topology(cell_type, n_points)
    if cell_type in _SOLIDS:
        return _solid_face(cell_type, n_points, label, source_type)
    if cell_type in _PLANAR and family in {'plane', 'shell'}:
        if (family == 'shell' and number in {1, 2}) or label in {'SN', 'SP'}:
            return cell_type, _REVERSE[cell_type] if number == 1 else tuple(range(n_points))
        edge_number = number - 2 if family == 'shell' else number
        n_corners = _PLANAR[cell_type]
        if 1 <= edge_number <= n_corners:
            wanted = {edge_number - 1, edge_number % n_corners}
            for edge_type, indices in edges:
                if set(indices[:2]) == wanted:
                    return edge_type, indices
    msg = (
        f'cannot extract face {label} from input type {source_type or "unknown"} '
        f'and VTK cell type {cell_type}; unexpanded beams and pyramid faces are unsupported'
    )
    raise ValueError(msg)


def _missing(ids: list[int], association: str, policy: str) -> None:
    if not ids:
        return
    message = (
        f'Surface references {len(ids)} {association} ID(s) absent from the FRD mesh: {ids[:8]}'
    )
    if policy == 'raise':
        raise ValueError(message)
    warnings.warn(message, UserWarning, stacklevel=4)


def _assemble(
    mesh: pv.UnstructuredGrid,
    cells: list[tuple[int, ...]],
    types: list[int],
    parents: list[int] | None,
) -> pv.UnstructuredGrid:
    if not cells:
        result = mesh.extract_cells(np.empty(0, dtype=np.int64))
        if parents is None:
            result.cell_data.clear()
        return result
    used = np.unique(np.array([point for cell in cells for point in cell], dtype=np.int64))
    lookup = {int(point): index for index, point in enumerate(used)}
    connectivity = [value for cell in cells for value in (len(cell), *(lookup[i] for i in cell))]
    result = pv.UnstructuredGrid(
        np.array(connectivity, dtype=np.int64),
        np.array(types, dtype=np.uint8),
        mesh.points[used].copy(),
    )
    for name, values in mesh.point_data.items():
        result.point_data[name] = values[used].copy()
    if parents is not None:
        for name, values in mesh.cell_data.items():
            result.cell_data[name] = values[parents].copy()
    for name, values in mesh.field_data.items():
        result.field_data[name] = values.copy()
    active = mesh.active_scalars_name
    if active in result.point_data:
        result.set_active_scalars(active, preference='point')
    return result


def extract_surface(
    mesh: pv.UnstructuredGrid,
    surface: INPSurface,
    element_types: dict[int, str],
    *,
    missing: str = 'raise',
) -> pv.UnstructuredGrid:
    """Build one surface from original IDs and the active step's mesh data."""
    if missing not in {'raise', 'warn'}:
        msg = "missing must be 'raise' or 'warn'"
        raise ValueError(msg)
    if surface.kind == 'NODE':
        indices = {int(nid): i for i, nid in enumerate(mesh.point_data['original_node_ids'])}
        absent = sorted(set(surface.node_ids) - indices.keys())
        _missing(absent, 'node', missing)
        cells = [(indices[nid],) for nid in surface.node_ids if nid in indices]
        result = _assemble(mesh, cells, [int(pv.CellType.VERTEX)] * len(cells), None)
        result.field_data['missing_node_ids'] = np.array(absent, dtype=np.int64)
        return result
    ids = mesh.cell_data['original_element_ids']
    indices = {int(eid): i for i, eid in enumerate(ids)}
    if len(indices) != len(ids):
        msg = 'FRD element IDs are duplicated; surface parent lookup is ambiguous'
        raise ValueError(msg)
    absent = sorted({eid for eid, _ in surface.element_faces} - indices.keys())
    _missing(absent, 'element', missing)
    cells, types, parents, labels = [], [], [], []
    offsets = np.asarray(mesh.cell_offsets if hasattr(mesh, 'cell_offsets') else mesh.offset)
    connectivity = np.asarray(mesh.cell_connectivity)
    for eid, label in surface.element_faces:
        if eid not in indices:
            continue
        index = indices[eid]
        points = connectivity[offsets[index] : offsets[index + 1]]
        try:
            kind, local = _face_connectivity(
                int(mesh.celltypes[index]), len(points), label, element_types.get(eid, '')
            )
        except ValueError as exc:
            msg = f'element {eid}, {label}: {exc}'
            raise ValueError(msg) from exc
        cells.append(tuple(int(points[i]) for i in local))
        types.append(kind)
        parents.append(index)
        labels.append(label)
    result = _assemble(mesh, cells, types, parents)
    result.cell_data['surface_face_labels'] = np.array(labels, dtype=str)
    result.field_data['missing_element_ids'] = np.array(absent, dtype=np.int64)
    return result
