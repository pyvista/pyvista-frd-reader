"""Convert CalculiX FRD data from the native parser into PyVista meshes.

The public reader follows PyVista's ``FRDReader`` and ``TimeReader`` interfaces.
Parsing, element conversion, and derived tensor quantities are implemented in
the C++ library.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING
import warnings

import numpy as np
import pyvista as pv
from pyvista.core.errors import InvalidMeshWarning
from pyvista.core.utilities.arrays import convert_array

from . import _capi
from ._capi import WEDGE_ASIS
from ._capi import WEDGE_SWAP
from ._capi import Diagnostic
from ._capi import DiagnosticKind
from ._capi import NativeFile
from .sets import INPSets
from .sets import read_sets

if TYPE_CHECKING:
    from pyvista import UnstructuredGrid

__all__ = ['ELEMENT_TYPE_NAMES', 'FRDReader', 'convert', 'read', 'write']

# The array the reference reader uses to carry the file's own node numbering.
ORIGINAL_NODE_IDS = 'original_node_ids'

_INT32_MAX = 2**31 - 1

# A result record is one node and its components, so an array is at most
# two-dimensional: nodes by components.
_MAX_ARRAY_RANK = 2

ELEMENT_TYPE_NAMES = {
    1: 'HE8',
    2: 'PE6',
    3: 'TE4',
    4: 'HE20',
    5: 'PE15',
    6: 'TE10',
    7: 'TR3',
    8: 'TR6',
    9: 'QU4',
    10: 'QU8',
    11: 'BE2',
    12: 'BE3',
    15: 'PY5',
    16: 'PY13',
}
"""CalculiX element codes and their names, keyed by the code an FRD file uses.

The code is the second field of an element's ``-1`` record. The names are what
the reference reader prints in its warnings, so they are message text rather
than an internal table -- ``PY5`` and ``PY13`` are CalculiX's experimental
pyramids, C3D5 and C3D13.
"""

# The reference prints at most this many offending elements per warning.
_MAX_REPORTED = 3

_WARNING_TEXT = {
    DiagnosticKind.TOO_MANY_POINTS: 'too many points detected',
    DiagnosticKind.TOO_FEW_POINTS: 'too few points detected. These elements are skipped',
    DiagnosticKind.UNSUPPORTED_ELEMENT: (
        'unknown element type encountered. These elements are skipped.'
    ),
}


def _default_wedge_order() -> int:
    """Return the PE6 node order the installed VTK expects.

    VTK changed its linear-wedge node order at 9.7. The C core cannot see
    which VTK its cells are destined for, so the choice is made here, where
    the answer is knowable, and passed in explicitly.
    """
    return WEDGE_SWAP if pv.vtk_version_info < (9, 7) else WEDGE_ASIS


def _describe(diagnostic: Diagnostic) -> str:
    """Render one diagnostic exactly as the reference reader renders it."""
    parts = [f'line {diagnostic.line}']
    name = ELEMENT_TYPE_NAMES.get(diagnostic.element_type)
    if name is not None:
        parts.append(f'element type {diagnostic.element_type} ({name})')
    else:
        parts.append(f'element type {diagnostic.element_type}')
    if diagnostic.n_actual is not None and diagnostic.n_expected is not None:
        parts.append(f'num nodes {diagnostic.n_actual} (expected {diagnostic.n_expected})')
    return ', '.join(parts)


class FRDReader:
    """Reader for CalculiX FRD result files (``.frd``).

    Reads both ASCII encodings and both binary encodings. Supported element
    types are HE8, PE6, PE15, TE4, HE20, TE10,
    TR3, TR6, QU4, QU8, BE2, BE3, PY5 and PY13.

    For each six-component STRESS or STRAIN tensor, the reader adds:

    - ``<NAME>_Mises``: equivalent von Mises magnitude.
    - ``<NAME>_sgMises``: signed von Mises magnitude.
    - ``<NAME>_PS1``, ``_PS2``, ``_PS3``: principal components, largest first.

    Parameters
    ----------
    path : str | os.PathLike
        File to read.
    inp_path : str | os.PathLike, optional
        Companion input deck. When supplied, add boolean ``NSET:<NAME>``
        point arrays and ``ELSET:<NAME>`` cell arrays. No deck is loaded
        automatically. IDs absent from the FRD mesh are omitted from masks.

    Attributes
    ----------
    sets : INPSets
        Original node and element memberships from the supplied input deck.
        Empty when no input deck was supplied.

    Warns
    -----
    pyvista.InvalidMeshWarning
        Emitted during construction for an invalid node count or unsupported
        element type.

    Examples
    --------
    >>> import pyvista_frd
    >>> reader = pyvista_frd.FRDReader('mesh.frd')  # doctest: +SKIP
    >>> reader.time_values  # doctest: +SKIP
    [0.5, 1.0]
    >>> mesh = reader.read()  # doctest: +SKIP

    """

    def __init__(
        self, path: str | os.PathLike[str], *, inp_path: str | os.PathLike[str] | None = None
    ) -> None:
        self.sets = INPSets() if inp_path is None else read_sets(inp_path)
        self.path = os.fspath(path)
        self._file = NativeFile(self.path, wedge_order=_default_wedge_order())
        self._time_steps = self._file.step_times
        self._active_time_point = 0
        self._warn_about_diagnostics()

    def _warn_about_diagnostics(self) -> None:
        by_kind: dict[int, list[Diagnostic]] = {}
        for diagnostic in self._file.diagnostics:
            by_kind.setdefault(diagnostic.kind, []).append(diagnostic)

        # Emitted in the reference's order -- too many, too few, unsupported --
        # because a caller filtering warnings by their first line depends on
        # which arrives first.
        for kind in (
            DiagnosticKind.TOO_MANY_POINTS,
            DiagnosticKind.TOO_FEW_POINTS,
            DiagnosticKind.UNSUPPORTED_ELEMENT,
        ):
            found = by_kind.get(kind)
            if not found:
                continue
            plural = 's' if len(found) > 1 else ''
            message = f'{len(found)} cell{plural} with {_WARNING_TEXT[kind]}:'
            for diagnostic in found[:_MAX_REPORTED]:
                message += '\n  ' + _describe(diagnostic)
            warnings.warn(message, InvalidMeshWarning, stacklevel=3)

    # -- TimeReader surface -------------------------------------------

    @property
    def number_time_points(self) -> int:
        """Return the total number of time points."""
        return len(self._time_steps)

    def time_point_value(self, time_point: int) -> float:
        """Return the time value associated with the given time point."""
        return self._time_steps[time_point]

    @property
    def time_values(self) -> list[float]:
        """Return the list of available time values."""
        return list(self._time_steps)

    def set_active_time_point(self, time_point: int) -> None:
        """Set the active time point."""
        n = self.number_time_points
        if not 0 <= time_point < n:
            msg = f'time_point {time_point} is out of range (file has {n} time point(s)).'
            raise IndexError(msg)
        self._active_time_point = time_point

    def set_active_time_value(self, time_value: float) -> None:
        """Set the active time value. An exact match is required."""
        steps = self._time_steps
        if not steps:
            msg = 'No time steps found in the FRD file.'
            raise RuntimeError(msg)
        if time_value not in steps:
            msg = f'Not a valid time {time_value} from available time values: {steps}'
            raise ValueError(msg)
        self._active_time_point = steps.index(time_value)

    @property
    def active_time_value(self) -> float:
        """Return the currently active time value, or 0.0 if there are none."""
        if not self._time_steps:
            return 0.0
        return self._time_steps[self._active_time_point]

    @active_time_value.setter
    def active_time_value(self, time_value: float) -> None:
        self.set_active_time_value(time_value)

    # -- reading ------------------------------------------------------

    def read(self) -> UnstructuredGrid:
        """Build the mesh for the active time step.

        Returns
        -------
        pyvista.UnstructuredGrid
            Mesh with ``original_node_ids`` and every array of the active
            step attached as point data.

        """
        n_points = self._file.n_points
        if n_points == 0:
            msg = 'No nodes found in FRD file -- cannot build grid.'
            raise ValueError(msg)

        points = self._file.points
        offsets = self._file.cell_offsets
        connectivity = self._file.cell_connectivity
        celltypes = self._file.cell_types

        grid = pv.UnstructuredGrid()
        grid.points = np.array(points, dtype=np.float64)
        grid.SetCells(convert_array(celltypes, deep=True), _cell_array(offsets, connectivity))

        # Strings, not integers: the reference stores them this way and code
        # in the wild compares against `str(node_id)`.
        grid.point_data['original_node_ids'] = np.array([str(nid) for nid in self._file.node_ids])

        if self._time_steps:
            step = self._active_time_point
            for index, (name, _n_components, _kind) in enumerate(self._file.array_infos(step)):
                grid.point_data[name] = self._file.array(step, index)

        if self.sets.node_sets or self.sets.element_sets:
            grid.cell_data['original_element_ids'] = self._file.cell_ids.copy()
            for name, ids in self.sets.node_sets.items():
                key = f'NSET:{name}'
                if key in grid.point_data:
                    msg = f'Set array {key!r} conflicts with an FRD result array'
                    raise ValueError(msg)
                grid.point_data[key] = np.isin(self._file.node_ids, ids)
            for name, ids in self.sets.element_sets.items():
                grid.cell_data[f'ELSET:{name}'] = np.isin(self._file.cell_ids, ids)

        return grid


class _Cells(pv.CellArray):
    """Cells in the width they were handed in, holding on to the buffers.

    ``vtkCellArray`` keeps whichever index width it is given and does not take
    ownership of it, so both arrays are kept here for as long as this lives.
    ``CellArray.from_arrays`` would do the keeping but promotes to
    ``pv.ID_TYPE`` on the way, which is the thing being avoided.
    """

    def __init__(self, offsets: np.ndarray, connectivity: np.ndarray) -> None:
        super().__init__()
        self._arrays = (offsets, connectivity)
        self.SetData(convert_array(offsets), convert_array(connectivity))


def _cell_array(offsets: np.ndarray, connectivity: np.ndarray) -> pv.CellArray:
    """Build the grid's cells, in 32-bit storage when the mesh fits.

    Narrowing here halves what a grid costs to hold for the whole of its life,
    and anything short of two billion connectivity entries fits -- which is
    every FRD file that has ever been written.

    Both arrays are copied: the ones handed in are views into memory the native
    reader owns and frees.
    """
    dtype = np.int32 if len(offsets) and offsets[-1] <= _INT32_MAX else np.int64
    return _Cells(offsets.astype(dtype), connectivity.astype(dtype))


def read(
    path: str | os.PathLike[str],
    *,
    time_point: int | None = None,
    inp_path: str | os.PathLike[str] | None = None,
) -> UnstructuredGrid:
    """Read an FRD file into a :class:`pyvista.UnstructuredGrid`.

    Parameters
    ----------
    path : str | os.PathLike
        File to read.
    time_point : int, optional
        Time step to read. Defaults to the first step.
    inp_path : str | os.PathLike, optional
        Companion input deck; see :class:`FRDReader` for set array naming.

    Returns
    -------
    pyvista.UnstructuredGrid
        The mesh, with the chosen step's arrays as point data.

    Examples
    --------
    >>> import pyvista_frd
    >>> mesh = pyvista_frd.read('mesh.frd')  # doctest: +SKIP

    """
    reader = FRDReader(path, inp_path=inp_path)
    if time_point is not None:
        reader.set_active_time_point(time_point)
    return reader.read()


def _grid_cells(grid: UnstructuredGrid) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the cell arrays in the offset/connectivity form the core wants."""
    offsets = np.asarray(grid.offset, dtype=np.int64)
    connectivity = np.asarray(grid.cell_connectivity, dtype=np.int64)
    return np.asarray(grid.celltypes, dtype=np.uint8), offsets, connectivity


def write(  # noqa: PLR0913 - each argument is one documented knob of the format
    path: str | os.PathLike[str],
    mesh: UnstructuredGrid,
    *,
    binary: bool = False,
    double: bool = True,
    time: float = 1.0,
    step: int = 1,
) -> None:
    """Write a mesh and its point data to a CalculiX FRD file.

    Parameters
    ----------
    path : str | os.PathLike
        File to write.
    mesh : pyvista.UnstructuredGrid
        Mesh to write. Every cell type must have a CalculiX element code.
    binary : bool, default: False
        Write binary records. ASCII records are used by default.
    double : bool, default: True
        Use 64-bit binary values. Set to ``False`` for 32-bit binary values.
    time, step : float and int
        The time value and step number recorded in the result block header.

    Notes
    -----
    Point data is written; cell data is not. An array that is neither a scalar,
    three-component vector, nor six-component tensor is written
    with a scalar kind code and its own component names.

    The output identifies this package as its writer rather than CalculiX.

    Examples
    --------
    >>> import pyvista_frd
    >>> pyvista_frd.write('out.frd', mesh)  # doctest: +SKIP

    """
    fmt = _capi.FORMAT_LONG_ASCII
    if binary:
        fmt = _capi.FORMAT_BINARY_DOUBLE if double else _capi.FORMAT_BINARY_FLOAT

    celltypes, offsets, connectivity = _grid_cells(mesh)
    points = np.asarray(mesh.points, dtype=np.float64)

    # A mesh this library read carries the file's own node numbering in
    # `original_node_ids` -- as strings, because that is what the reference
    # reader produces and this one matches it. Those are node *numbers*, so
    # they go back into the node records they came from rather than being
    # written out again as a result array of stringified integers.
    node_ids = None
    arrays = list(mesh.point_data)
    if ORIGINAL_NODE_IDS in mesh.point_data:
        try:
            node_ids = np.asarray(mesh.point_data[ORIGINAL_NODE_IDS]).astype(np.int64)
        except (TypeError, ValueError):
            node_ids = None  # not a numbering after all; write it as an array
        else:
            arrays.remove(ORIGINAL_NODE_IDS)

    with _capi.Writer(fmt) as writer:
        writer.set_nodes(points, node_ids)
        if len(celltypes):
            writer.set_cells(celltypes, offsets, connectivity, wedge_order=_default_wedge_order())
        if arrays:
            writer.begin_step(step, time)
            for name in arrays:
                raw = np.asarray(mesh.point_data[name])
                try:
                    values = raw.astype(np.float64)
                except (TypeError, ValueError) as exc:
                    # Refused rather than skipped. FRD result blocks hold
                    # numbers, and an array quietly left out of the file is a
                    # worse answer than being told it cannot go in.
                    msg = (
                        f'{name!r} has dtype {raw.dtype}, which FRD cannot hold: a result '
                        f'block is numeric. Remove it or convert it before writing.'
                    )
                    raise ValueError(msg) from exc
                if values.ndim > _MAX_ARRAY_RANK:
                    msg = f'{name!r} has shape {values.shape}; FRD holds one value per component'
                    raise ValueError(msg)
                writer.add_array(name, values)
        data = writer.finish()

    Path(os.fspath(path)).write_bytes(data)


def convert(
    source: str | os.PathLike[str],
    target: str | os.PathLike[str],
    *,
    binary: bool | None = None,
    double: bool = True,
) -> None:
    """Rewrite an FRD file, optionally changing its encoding.

    If ``binary`` is omitted, each block keeps its input encoding. Set it to
    ``False`` to make binary records available to ASCII-only readers. ASCII
    output stores six significant digits.

    Raises
    ------
    FRDFormatError
        If a block has no format code and cannot be converted safely.

    Examples
    --------
    >>> import pyvista_frd
    >>> pyvista_frd.convert('binary.frd', 'ascii.frd', binary=False)  # doctest: +SKIP

    """
    if binary is None:
        fmt = _capi.FORMAT_KEEP
    elif binary:
        fmt = _capi.FORMAT_BINARY_DOUBLE if double else _capi.FORMAT_BINARY_FLOAT
    else:
        fmt = _capi.FORMAT_LONG_ASCII

    data = Path(os.fspath(source)).read_bytes()
    Path(os.fspath(target)).write_bytes(_capi.rewrite_bytes(data, fmt))
