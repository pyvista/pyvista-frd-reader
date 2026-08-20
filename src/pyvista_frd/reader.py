"""PyVista-facing reader for CalculiX FRD files.

This layer does one job: turn the arrays the native core produced into a
:class:`pyvista.UnstructuredGrid`. All parsing, all element handling, and all
derived quantities happen in C++ -- which is what lets a caller in another
language get the same numbers without reimplementing any of it.

The public surface deliberately matches PyVista's own ``FRDReader``, including
the ``TimeReader`` methods and the wording of its warnings, so that PyVista can
one day hand ``.frd`` to this package without any caller noticing.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
import warnings

import numpy as np
import pyvista as pv
from pyvista.core.errors import InvalidMeshWarning

from ._capi import WEDGE_ASIS
from ._capi import WEDGE_SWAP
from ._capi import Diagnostic
from ._capi import DiagnosticKind
from ._capi import NativeFile

if TYPE_CHECKING:
    from pyvista import UnstructuredGrid

__all__ = ['ELEMENT_TYPE_NAMES', 'FRDReader', 'read']

# CalculiX element codes and the names the reference reader prints in its
# warnings. The C core reports codes; the names live here because they are
# message text, and message text is the part users and tests read.
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
    """Reader for CalculiX FRD ASCII result files (``.frd``).

    Supported element types: HE8, PE6, PE15, TE4, HE20, TE10, TR3, TR6, QU4,
    QU8, BE2, BE3, PY5, PY13.

    For datasets containing 6-component tensors (e.g. STRESS or STRAIN), the
    reader pre-computes and appends the following derived point arrays:

    - ``<NAME>_Mises``: equivalent von Mises magnitude.
    - ``<NAME>_sgMises``: signed von Mises magnitude.
    - ``<NAME>_PS1``, ``_PS2``, ``_PS3``: principal components, largest first.

    Parameters
    ----------
    path : str | os.PathLike
        File to read.

    Warns
    -----
    pyvista.InvalidMeshWarning
        Raised at construction, not at read, for elements carrying the wrong
        number of nodes or an unknown type. Construction is where the file is
        parsed, so it is also where anything wrong with it is known.

    Examples
    --------
    >>> import pyvista_frd
    >>> reader = pyvista_frd.FRDReader('mesh.frd')  # doctest: +SKIP
    >>> reader.time_values  # doctest: +SKIP
    [0.5, 1.0]
    >>> mesh = reader.read()  # doctest: +SKIP

    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
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

        grid = pv.UnstructuredGrid(_legacy_cells(offsets, connectivity), celltypes, points)

        # Strings, not integers: the reference stores them this way and code
        # in the wild compares against `str(node_id)`.
        grid.point_data['original_node_ids'] = np.array([str(nid) for nid in self._file.node_ids])

        if self._time_steps:
            step = self._active_time_point
            for index, (name, _n_components, _kind) in enumerate(self._file.array_infos(step)):
                grid.point_data[name] = self._file.array(step, index)

        return grid


def _legacy_cells(offsets: np.ndarray, connectivity: np.ndarray) -> np.ndarray:
    """Interleave point counts into the connectivity, VTK's legacy cell form.

    ``pyvista.UnstructuredGrid`` takes this shape, and building it here keeps
    the C ABI on the offsets/connectivity pair that VTK 9 and every other
    consumer actually use. Done with array arithmetic rather than a loop
    because the loop is what the C++ core exists to avoid.
    """
    n_cells = len(offsets) - 1
    if n_cells <= 0:
        return np.empty(0, dtype=pv.ID_TYPE)
    cells = np.empty(len(connectivity) + n_cells, dtype=pv.ID_TYPE)
    positions = offsets[:-1] + np.arange(n_cells)
    cells[positions] = np.diff(offsets)
    mask = np.ones(len(cells), dtype=bool)
    mask[positions] = False
    cells[mask] = connectivity
    return cells


def read(path: str | os.PathLike[str], *, time_point: int | None = None) -> UnstructuredGrid:
    """Read an FRD file into a :class:`pyvista.UnstructuredGrid`.

    Parameters
    ----------
    path : str | os.PathLike
        File to read.
    time_point : int, optional
        Which time step to build. Defaults to the first, matching PyVista.

    Returns
    -------
    pyvista.UnstructuredGrid
        The mesh, with the chosen step's arrays as point data.

    Examples
    --------
    >>> import pyvista_frd
    >>> mesh = pyvista_frd.read('mesh.frd')  # doctest: +SKIP

    """
    reader = FRDReader(path)
    if time_point is not None:
        reader.set_active_time_point(time_point)
    return reader.read()
