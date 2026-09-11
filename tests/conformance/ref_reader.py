"""Pinned PyVista FRD reader wrappers for versions that removed FRD support.

The two classes below are verbatim extracts from
https://github.com/pyvista/pyvista/blob/23bc8abf0cfa35c5a37f74537b615c57ac8709bf/pyvista/core/utilities/reader.py
Copyright (c) 2017-2026, The PyVista Developers. MIT license (see LICENSE).
Only the imports are adapted to use the existing pinned parser in ref_frd.py.
Do not edit the class bodies to make conformance tests pass.
"""

from __future__ import annotations

from pyvista._warn_external import warn_external
from pyvista.core.errors import InvalidMeshWarning
from pyvista.core.utilities.reader import BaseReader
from pyvista.core.utilities.reader import BaseVTKReader
from pyvista.core.utilities.reader import TimeReader

from .ref_frd import _FRDData
from .ref_frd import _FRDParser


class _FRDReader(BaseVTKReader):
    """VTK-style reader for CalculiX FRD files using FRDParser."""

    def __init__(self) -> None:
        super().__init__()
        self._frd_data: _FRDData | None = None
        self._time_steps: list[float] = []
        self._active_time_point: int = 0

    def UpdateInformation(self) -> None:
        parser = _FRDParser(self._filename)
        self._frd_data = parser.parse()

        MAX_N_LINES = 3

        def _warn_invalid(invalid_elements, desc):
            n = len(invalid_elements)
            s = 's' if n > 1 else ''
            msg = f'{n} cell{s} with {desc}:'
            for elem in invalid_elements[:MAX_N_LINES]:
                msg += '\n  ' + str(elem)

            warn_external(msg, InvalidMeshWarning)

        if invalid_elements := self._frd_data._has_too_many_points:
            _warn_invalid(invalid_elements, 'too many points detected')

        if invalid_elements := self._frd_data._has_too_few_points:
            _warn_invalid(invalid_elements, 'too few points detected. These elements are skipped')

        if invalid_elements := self._frd_data._has_unsupported_element:
            _warn_invalid(
                invalid_elements, 'unknown element type encountered. These elements are skipped.'
            )

        self._time_steps = sorted(self._frd_data.results_by_step.keys())

    def Update(self) -> None:
        """Construct the mesh for the currently active time step."""
        if self._frd_data is None:
            return
        step_time = self._time_steps[self._active_time_point] if self._time_steps else None
        step_data = (
            self._frd_data.results_by_step.get(step_time, {}) if step_time is not None else {}
        )
        self._data_object = _FRDParser._build_grid(self._frd_data, step_data)


class FRDReader(BaseReader['UnstructuredGrid'], TimeReader):
    """Reader for CalculiX FRD ASCII result files (``.frd``).

    Supported element types include: HE8, PE6, PE15, TE4, HE20, TE10, TR3, TR6, QU4, QU8, BE2, BE3,
    PY5, PY13.

    For datasets containing 6-component tensors (e.g. STRESS or STRAIN), this reader automatically
    pre-computes and appends the following derived scalar arrays to the output mesh:

    - ``<NAME>_Mises``: equivalent von Mises magnitude.
    - ``<NAME>_sgMises``: signed von Mises magnitude.
    - ``<NAME>_PS1``, ``_PS2``, ``_PS3``: principal components.

    .. versionadded:: 0.48

    Examples
    --------
    >>> import pyvista as pv
    >>> from pyvista import examples
    >>> from pathlib import Path
    >>> filename = examples.download_frd(load=False)
    >>> Path(filename).name
    'mesh.frd'
    >>> reader = pv.get_reader(filename)
    >>> mesh = reader.read()
    >>> mesh.plot()

    """

    _class_reader = _FRDReader

    @property
    def number_time_points(self) -> int:
        """Return the total number of time points."""
        return len(self.reader._time_steps)

    def time_point_value(self, time_point: int) -> float:
        """Return the time value associated with the given time point."""
        return self.reader._time_steps[time_point]

    @property
    def time_values(self) -> list[float]:
        """Return the list of available time values."""
        return list(self.reader._time_steps)

    def set_active_time_point(self, time_point: int) -> None:
        """Set the active time point."""
        n = self.number_time_points
        if not 0 <= time_point < n:
            msg = f'time_point {time_point} is out of range (file has {n} time point(s)).'
            raise IndexError(msg)
        self.reader._active_time_point = time_point

    def set_active_time_value(self, time_value: float) -> None:
        """Set the active time value."""
        steps = self.reader._time_steps
        if not steps:
            msg = 'No time steps found in the FRD file.'
            raise RuntimeError(msg)

        # Changed logic - exact match is required
        if time_value not in steps:
            msg = f'Not a valid time {time_value} from available time values: {steps}'
            raise ValueError(msg)

        self.reader._active_time_point = steps.index(time_value)

    @property
    def active_time_value(self) -> float:
        """Return the active time value."""
        steps = self.reader._time_steps
        if not steps:
            return 0.0
        return steps[self.reader._active_time_point]

    @active_time_value.setter
    def active_time_value(self, value: float) -> None:
        """Set the active time value."""
        self.set_active_time_value(value)
