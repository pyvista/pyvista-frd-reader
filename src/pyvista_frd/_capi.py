"""``ctypes`` binding to the ``pvfrd`` C ABI.

There is no compiled extension module here and no binding framework. The core
is a plain shared library exposing a C ABI, and this module loads it with
:mod:`ctypes`. That is what lets the same library be consumed as a C++
submodule, cross-compiled to WebAssembly, and shipped in a wheel without three
binding layers going out of step -- and it is why a wheel of this package
carries no CPython ABI tag.

Unlike some sibling projects, there is no pure-Python fallback: the C++ core
*is* the implementation. A missing or unloadable library raises here rather
than degrading to something slower, because a degraded reader that still
returns a mesh is indistinguishable from a working one until someone measures.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER
from ctypes import Structure
from ctypes import byref
from ctypes import c_char_p
from ctypes import c_double
from ctypes import c_int
from ctypes import c_int32
from ctypes import c_int64
from ctypes import c_size_t
from ctypes import c_uint8
from ctypes import c_uint32
from ctypes import c_uint64
from ctypes import c_void_p
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Iterator

    from numpy.typing import NDArray

__all__ = [
    'ABI_VERSION',
    'WEDGE_ASIS',
    'WEDGE_SWAP',
    'Diagnostic',
    'DiagnosticKind',
    'FRDError',
    'NativeFile',
    'NativeUnavailableError',
    'library_path',
]

ABI_VERSION = 1
"""ABI this binding speaks. A library reporting anything else is refused."""

WEDGE_ASIS = 0
WEDGE_SWAP = 1

# Names *which* library to load, for development and unusual deployments. It
# does not change what the library does; every behavioural knob is an argument.
_LIBRARY_ENV_VAR = 'PVFRD_LIBRARY'

_STATUS_OK = 0
_STATUS_NAMES = {
    1: 'the file could not be opened or read',
    2: 'the file did not parse as an FRD document',
    3: 'index out of range',
    4: 'out of memory',
    5: 'invalid argument',
    6: 'a result block gave two nodes different component counts',
}

RAW = 0
DERIVED = 1


class FRDError(RuntimeError):
    """The native library reported a failure."""

    def __init__(self, status: int, detail: str = '') -> None:
        described = _STATUS_NAMES.get(status, f'unknown status {status}')
        super().__init__(f'{described} ({detail})' if detail else described)
        self.status = status


class NativeUnavailableError(ImportError):
    """The native library could not be loaded on this machine."""


class DiagnosticKind:
    """Why an element was reported as questionable."""

    TOO_MANY_POINTS = 0
    TOO_FEW_POINTS = 1
    UNSUPPORTED_ELEMENT = 2


@dataclass(frozen=True)
class Diagnostic:
    """One questionable element, as the parser saw it."""

    kind: int
    element_type: int
    line: int
    n_expected: int | None
    n_actual: int | None


class _ArrayInfo(Structure):
    _fields_ = (
        ('name', c_char_p),
        ('n_tuples', c_uint64),
        ('n_components', c_uint32),
        ('kind', c_int32),
    )


class _Diagnostic(Structure):
    _fields_ = (
        ('kind', c_int32),
        ('element_type', c_int32),
        ('line', c_int64),
        ('n_expected', c_int64),
        ('n_actual', c_int64),
    )


class _OpenOptions(Structure):
    _fields_ = (
        ('wedge_order', c_int32),
        ('reserved', c_int32),
    )


def _candidate_names() -> list[str]:
    """Shared-library file names to try, per platform."""
    if sys.platform == 'win32':
        return ['pvfrd.dll', 'libpvfrd.dll']
    if sys.platform == 'darwin':
        return ['libpvfrd.dylib']
    return ['libpvfrd.so']


def _candidate_paths() -> Iterator[str]:
    """Yield places the library may live, in priority order.

    The bundled copy inside the package wins over anything on the system
    search path, so an installed wheel is self-contained and cannot be
    silently served by an unrelated build sitting in the loader path.
    """
    override = os.environ.get(_LIBRARY_ENV_VAR)
    if override:
        yield override

    here = Path(__file__).parent
    for directory in (here / 'lib', here):
        for name in _candidate_names():
            candidate = directory / name
            if candidate.exists():
                yield str(candidate)

    # Last: let the platform loader search. Yields a bare name, not a path.
    yield from _candidate_names()


def _bind(lib: ctypes.CDLL) -> None:
    """Declare every signature.

    Not optional book-keeping: ctypes defaults a return value to C ``int``,
    which silently truncates every ``uint64`` count here and turns a pointer
    into a sign-extended 32-bit integer on a 64-bit build.
    """
    lib.pvfrd_abi_version.restype = c_uint32
    lib.pvfrd_abi_version.argtypes = []

    lib.pvfrd_status_message.restype = c_char_p
    lib.pvfrd_status_message.argtypes = [c_int]

    lib.pvfrd_last_error.restype = c_char_p
    lib.pvfrd_last_error.argtypes = [c_void_p]

    lib.pvfrd_open_ex.restype = c_int
    lib.pvfrd_open_ex.argtypes = [c_char_p, POINTER(_OpenOptions), POINTER(c_void_p)]

    lib.pvfrd_open_memory.restype = c_int
    lib.pvfrd_open_memory.argtypes = [
        c_void_p,
        c_size_t,
        POINTER(_OpenOptions),
        POINTER(c_void_p),
    ]

    lib.pvfrd_close.restype = None
    lib.pvfrd_close.argtypes = [c_void_p]

    lib.pvfrd_n_points.restype = c_uint64
    lib.pvfrd_n_points.argtypes = [c_void_p]

    lib.pvfrd_points.restype = POINTER(c_double)
    lib.pvfrd_points.argtypes = [c_void_p]

    lib.pvfrd_node_ids.restype = POINTER(c_int64)
    lib.pvfrd_node_ids.argtypes = [c_void_p]

    lib.pvfrd_n_cells.restype = c_uint64
    lib.pvfrd_n_cells.argtypes = [c_void_p]

    lib.pvfrd_cell_types.restype = POINTER(c_uint8)
    lib.pvfrd_cell_types.argtypes = [c_void_p]

    lib.pvfrd_cell_offsets.restype = POINTER(c_int64)
    lib.pvfrd_cell_offsets.argtypes = [c_void_p]

    lib.pvfrd_cell_connectivity.restype = POINTER(c_int64)
    lib.pvfrd_cell_connectivity.argtypes = [c_void_p]

    lib.pvfrd_n_diagnostics.restype = c_uint64
    lib.pvfrd_n_diagnostics.argtypes = [c_void_p]

    lib.pvfrd_diagnostic_at.restype = c_int
    lib.pvfrd_diagnostic_at.argtypes = [c_void_p, c_uint64, POINTER(_Diagnostic)]

    lib.pvfrd_n_steps.restype = c_uint64
    lib.pvfrd_n_steps.argtypes = [c_void_p]

    lib.pvfrd_step_time.restype = c_int
    lib.pvfrd_step_time.argtypes = [c_void_p, c_uint64, POINTER(c_double)]

    lib.pvfrd_n_arrays.restype = c_int
    lib.pvfrd_n_arrays.argtypes = [c_void_p, c_uint64, POINTER(c_uint64)]

    lib.pvfrd_array_info_range.restype = c_int
    lib.pvfrd_array_info_range.argtypes = [
        c_void_p,
        c_uint64,
        c_uint64,
        c_uint64,
        POINTER(_ArrayInfo),
    ]

    lib.pvfrd_array_data.restype = c_int
    lib.pvfrd_array_data.argtypes = [c_void_p, c_uint64, c_uint64, POINTER(POINTER(c_double))]

    lib.pvfrd_find_array.restype = c_int64
    lib.pvfrd_find_array.argtypes = [c_void_p, c_uint64, c_char_p]


def _load() -> tuple[ctypes.CDLL, str]:
    attempts: list[str] = []
    for candidate in _candidate_paths():
        try:
            lib = ctypes.CDLL(candidate)
        except OSError as exc:
            attempts.append(f'{candidate}: {exc}')
            continue

        _bind(lib)
        found = lib.pvfrd_abi_version()
        if found != ABI_VERSION:
            msg = (
                f'{candidate}: ABI version {found}, expected {ABI_VERSION}. '
                f'The library and the Python package are from different builds.'
            )
            raise NativeUnavailableError(msg)
        return lib, candidate

    detail = '\n  '.join(attempts) if attempts else '(no candidate paths existed)'
    msg = (
        'pyvista-frd-reader could not load its native library. It has no '
        'pure-Python fallback; the C++ core is the implementation.\n'
        f'Tried:\n  {detail}\n'
        f'Set {_LIBRARY_ENV_VAR} to point at a built library, or reinstall '
        'the package from a wheel.'
    )
    raise NativeUnavailableError(msg)


_lib, _lib_path = _load()


def library_path() -> str:
    """Return the file the native core was loaded from."""
    return _lib_path


def _check(status: int, handle: c_void_p | None = None) -> None:
    if status == _STATUS_OK:
        return
    detail = ''
    if handle is not None:
        raw = _lib.pvfrd_last_error(handle)
        if raw:
            detail = raw.decode('utf-8', 'replace')
    raise FRDError(status, detail)


def _as_array(pointer, shape: tuple[int, ...], dtype) -> NDArray:  # noqa: ANN001
    """Copy a native buffer into a NumPy array.

    Copied, not viewed. A view would alias memory the reader owns, and the
    arrays handed to PyVista outlive the reader in every realistic use --
    ``grid.point_data[name] = arr`` keeps a reference to the NumPy object, not
    to whatever it borrowed from. The copy costs a memcpy against a parse that
    already walked the file character by character.
    """
    count = int(np.prod(shape)) if shape else 0
    if count == 0:
        return np.empty(shape, dtype=dtype)
    buffer = ctypes.cast(pointer, POINTER(ctypes.c_byte * (count * np.dtype(dtype).itemsize)))
    return np.frombuffer(buffer.contents, dtype=dtype).reshape(shape).copy()


class NativeFile:
    """An open FRD document.

    Thin: it owns the handle and converts native buffers to NumPy. Everything
    about PyVista lives a layer up, so this class is usable without PyVista
    installed and is what the conformance suite drives directly.
    """

    def __init__(self, path: str | os.PathLike[str], *, wedge_order: int = WEDGE_ASIS) -> None:
        options = _OpenOptions(wedge_order=wedge_order, reserved=0)
        handle = c_void_p()
        status = _lib.pvfrd_open_ex(os.fsencode(os.fspath(path)), byref(options), byref(handle))
        if status != _STATUS_OK:
            raise FRDError(status, str(path))
        self._handle = handle
        self._path = str(path)

    @classmethod
    def from_bytes(cls, data: bytes, *, wedge_order: int = WEDGE_ASIS) -> NativeFile:
        """Open a document already in memory, without a temporary file."""
        self = cls.__new__(cls)
        options = _OpenOptions(wedge_order=wedge_order, reserved=0)
        handle = c_void_p()
        status = _lib.pvfrd_open_memory(data, len(data), byref(options), byref(handle))
        if status != _STATUS_OK:
            raise FRDError(status, '<memory>')
        self._handle = handle
        self._path = '<memory>'
        return self

    def close(self) -> None:
        """Release the document. Idempotent."""
        if getattr(self, '_handle', None) is not None:
            _lib.pvfrd_close(self._handle)
            self._handle = None

    def __del__(self) -> None:
        self.close()

    def __enter__(self) -> NativeFile:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _require_open(self) -> c_void_p:
        if getattr(self, '_handle', None) is None:
            msg = 'this FRD document has already been closed'
            raise ValueError(msg)
        return self._handle

    # -- mesh ---------------------------------------------------------

    @property
    def n_points(self) -> int:
        return int(_lib.pvfrd_n_points(self._require_open()))

    @property
    def points(self) -> NDArray[np.float64]:
        n = self.n_points
        return _as_array(_lib.pvfrd_points(self._require_open()), (n, 3), np.float64)

    @property
    def node_ids(self) -> NDArray[np.int64]:
        n = self.n_points
        return _as_array(_lib.pvfrd_node_ids(self._require_open()), (n,), np.int64)

    @property
    def n_cells(self) -> int:
        return int(_lib.pvfrd_n_cells(self._require_open()))

    @property
    def cell_types(self) -> NDArray[np.uint8]:
        n = self.n_cells
        return _as_array(_lib.pvfrd_cell_types(self._require_open()), (n,), np.uint8)

    @property
    def cell_offsets(self) -> NDArray[np.int64]:
        handle = self._require_open()
        n = self.n_cells
        # n_cells + 1 entries, always, even for an empty mesh.
        return _as_array(_lib.pvfrd_cell_offsets(handle), (n + 1,), np.int64)

    @property
    def cell_connectivity(self) -> NDArray[np.int64]:
        handle = self._require_open()
        total = int(self.cell_offsets[-1]) if self.n_cells else 0
        return _as_array(_lib.pvfrd_cell_connectivity(handle), (total,), np.int64)

    # -- diagnostics --------------------------------------------------

    @property
    def diagnostics(self) -> list[Diagnostic]:
        handle = self._require_open()
        out: list[Diagnostic] = []
        for i in range(int(_lib.pvfrd_n_diagnostics(handle))):
            raw = _Diagnostic()
            _check(_lib.pvfrd_diagnostic_at(handle, i, byref(raw)), handle)
            out.append(
                Diagnostic(
                    kind=raw.kind,
                    element_type=raw.element_type,
                    line=raw.line,
                    n_expected=None if raw.n_expected < 0 else raw.n_expected,
                    n_actual=None if raw.n_actual < 0 else raw.n_actual,
                )
            )
        return out

    # -- steps and arrays ---------------------------------------------

    @property
    def n_steps(self) -> int:
        return int(_lib.pvfrd_n_steps(self._require_open()))

    @property
    def step_times(self) -> list[float]:
        handle = self._require_open()
        out: list[float] = []
        for i in range(self.n_steps):
            value = c_double()
            _check(_lib.pvfrd_step_time(handle, i, byref(value)), handle)
            out.append(value.value)
        return out

    def n_arrays(self, step: int) -> int:
        handle = self._require_open()
        count = c_uint64()
        _check(_lib.pvfrd_n_arrays(handle, step, byref(count)), handle)
        return int(count.value)

    def array_infos(self, step: int) -> list[tuple[str, int, int]]:
        """Return ``(name, n_components, kind)`` for every array in a step.

        One call across the boundary rather than one per array. A step holds
        an array per result block plus five more for every tensor, so the
        per-call cost of a foreign-function layer was being paid a dozen times
        to move a few hundred bytes.
        """
        handle = self._require_open()
        count = self.n_arrays(step)
        if count == 0:
            return []
        buffer = (_ArrayInfo * count)()
        _check(_lib.pvfrd_array_info_range(handle, step, 0, count, buffer), handle)
        return [
            (info.name.decode('utf-8', 'replace'), int(info.n_components), int(info.kind))
            for info in buffer
        ]

    def array(self, step: int, index: int) -> NDArray[np.float64]:
        """Return array ``index`` of ``step``, shaped ``(n_points,)`` or 2-D."""
        handle = self._require_open()
        _name, n_components, _kind = self.array_infos(step)[index]
        pointer = POINTER(c_double)()
        _check(_lib.pvfrd_array_data(handle, step, index, byref(pointer)), handle)
        shape = (self.n_points,) if n_components == 1 else (self.n_points, n_components)
        return _as_array(pointer, shape, np.float64)

    def find_array(self, step: int, name: str) -> int:
        """Index of ``name`` within ``step``, or -1."""
        return int(_lib.pvfrd_find_array(self._require_open(), step, name.encode('utf-8')))
