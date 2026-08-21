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
from ctypes import c_char
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
    'FRDFormatError',
    'FRDInternalError',
    'FRDInvalidArgumentError',
    'FRDMemoryError',
    'FRDRaggedArrayError',
    'FRDRangeError',
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
_STATUS_IO = 1
_STATUS_FORMAT = 2
_STATUS_RANGE = 3
_STATUS_NOMEM = 4
_STATUS_INVALID = 5
_STATUS_RAGGED = 6
_STATUS_INTERNAL = 7

_STATUS_NAMES = {
    _STATUS_IO: 'the file could not be opened or read',
    _STATUS_FORMAT: 'the file did not parse as an FRD document',
    _STATUS_RANGE: 'index out of range',
    _STATUS_NOMEM: 'out of memory',
    _STATUS_INVALID: 'invalid argument',
    _STATUS_RAGGED: 'a result block gave two nodes different component counts',
    _STATUS_INTERNAL: 'an unexpected error inside the library; please report it',
}

RAW = 0
DERIVED = 1


class FRDError(RuntimeError):
    """The native library reported a failure.

    The base of every error this package raises from the native core, so
    ``except FRDError`` catches all of them. The subclasses below also inherit
    the built-in exception a Python caller would reach for -- an index out of
    range is an ``IndexError``, running out of memory is a ``MemoryError`` --
    because a C status code is the wrong shape for Python's ``except`` and
    making callers match on ``err.status`` is asking them to write a switch
    where the language already has one.
    """

    def __init__(self, status: int, detail: str = '') -> None:
        described = _STATUS_NAMES.get(status, f'unknown status {status}')
        super().__init__(f'{described} ({detail})' if detail else described)
        self.status = status


class FRDFormatError(FRDError, ValueError):
    """The bytes were not a readable FRD document."""


class FRDRaggedArrayError(FRDFormatError):
    """One result block gave two nodes different component counts.

    A subclass of the format error rather than a sibling: it is a statement
    about the file, and a caller who only wants to know "is this file
    readable" should not have to name it separately.
    """


class FRDRangeError(FRDError, IndexError):
    """A step, array or element index was out of range."""


class FRDInvalidArgumentError(FRDError, ValueError):
    """An argument the native core rejected."""


class FRDMemoryError(FRDError, MemoryError):
    """The native core could not allocate."""


class FRDInternalError(FRDError):
    """A fault inside the native library, not a property of the file.

    Distinct from :class:`FRDFormatError` on purpose. Reporting a library bug
    as a bad file sends the reporter to inspect a file that is fine. If you
    see this, it is worth an issue.
    """


_STATUS_EXCEPTIONS: dict[int, type[FRDError]] = {
    _STATUS_FORMAT: FRDFormatError,
    _STATUS_RANGE: FRDRangeError,
    _STATUS_NOMEM: FRDMemoryError,
    _STATUS_INVALID: FRDInvalidArgumentError,
    _STATUS_RAGGED: FRDRaggedArrayError,
    _STATUS_INTERNAL: FRDInternalError,
}


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

    lib.pvfrd_struct_size.restype = c_uint32
    lib.pvfrd_struct_size.argtypes = [c_int]

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

    lib.pvfrd_steps_parsed.restype = c_uint64
    lib.pvfrd_steps_parsed.argtypes = [c_void_p]

    _bind_writing(lib)


def _bind_writing(lib: ctypes.CDLL) -> None:
    """Declare the writing half, split out only because the two are long together."""
    lib.pvfrd_rewrite_memory.restype = c_int
    lib.pvfrd_rewrite_memory.argtypes = [
        c_void_p,
        c_size_t,
        c_int32,
        POINTER(POINTER(c_char)),
        POINTER(c_size_t),
    ]

    lib.pvfrd_free.restype = None
    lib.pvfrd_free.argtypes = [POINTER(c_char)]

    lib.pvfrd_writer_new.restype = c_void_p
    lib.pvfrd_writer_new.argtypes = [c_int32]

    lib.pvfrd_writer_free.restype = None
    lib.pvfrd_writer_free.argtypes = [c_void_p]

    lib.pvfrd_writer_set_nodes.restype = c_int
    lib.pvfrd_writer_set_nodes.argtypes = [c_void_p, c_uint64, c_void_p, c_void_p]

    lib.pvfrd_writer_set_cells.restype = c_int
    lib.pvfrd_writer_set_cells.argtypes = [
        c_void_p,
        c_uint64,
        c_void_p,
        c_void_p,
        c_void_p,
        c_void_p,
        c_int32,
    ]

    lib.pvfrd_writer_begin_step.restype = c_int
    lib.pvfrd_writer_begin_step.argtypes = [c_void_p, c_int32, c_double]

    lib.pvfrd_writer_add_array.restype = c_int
    lib.pvfrd_writer_add_array.argtypes = [
        c_void_p,
        c_char_p,
        c_uint32,
        c_void_p,
        c_int32,
        c_void_p,
    ]

    lib.pvfrd_writer_finish.restype = c_int
    lib.pvfrd_writer_finish.argtypes = [c_void_p, POINTER(POINTER(c_char)), POINTER(c_size_t)]


# ctypes struct id -> the C enumerator it must agree with.
_STRUCT_IDS = {
    'pvfrd_open_options': 0,
    'pvfrd_array_info': 1,
    'pvfrd_diagnostic': 2,
}


def _check_struct_layouts(lib: ctypes.CDLL, candidate: str) -> None:
    """Confirm the structs declared here match the ones the library compiled.

    The declarations in this module are handwritten, and nothing checks them:
    a field in the wrong order or an ``int`` where an ``int64`` belongs
    produces plausible garbage rather than an error. It also does so only on
    the platform whose alignment rules differ from the one the binding was
    written on, which is the worst possible place to find out.

    Comparing sizes will not catch two fields of equal width swapped -- the
    tests cover that by reading real values -- but it does catch every width
    and padding mistake, at import, with a message naming the struct.
    """
    for name, struct in (
        ('pvfrd_open_options', _OpenOptions),
        ('pvfrd_array_info', _ArrayInfo),
        ('pvfrd_diagnostic', _Diagnostic),
    ):
        native = int(lib.pvfrd_struct_size(_STRUCT_IDS[name]))
        declared = ctypes.sizeof(struct)
        if native != declared:
            msg = (
                f'{candidate}: {name} is {native} bytes in the library and '
                f'{declared} in this binding. The two are not from the same '
                f'build, or this platform lays the struct out differently.'
            )
            raise NativeUnavailableError(msg)


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
        _check_struct_layouts(lib, candidate)
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


def _native_detail(handle: c_void_p | None) -> str:
    """Return the native core's account of the last failure, or ''.

    ``handle`` may be None, and that is the interesting case: a failed open
    leaves no reader to ask, so the core keeps a thread-local slot for exactly
    that. Passing None here reads it. Before it existed, the reason for the
    one failure a caller cannot guess at was dropped, and this module filled
    the gap by reporting back the path it had just been given.
    """
    raw = _lib.pvfrd_last_error(handle)
    return raw.decode('utf-8', 'replace') if raw else ''


def _raise_for_status(status: int, detail: str = '') -> None:
    """Raise the exception type that matches a native status code."""
    exception = _STATUS_EXCEPTIONS.get(status, FRDError)
    raise exception(status, detail)


def _check(status: int, handle: c_void_p | None = None) -> None:
    if status == _STATUS_OK:
        return
    _raise_for_status(status, _native_detail(handle))


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


def _raise_for_open_failure(status: int, path: str | os.PathLike[str]) -> None:
    """Raise the best exception available for a failed open.

    For an I/O failure this deliberately lets Python do the diagnosis. The C
    ABI can only say PVFRD_E_IO -- one code for "no such file", "permission
    denied" and "that is a directory" -- and reproducing errno across the
    boundary would mean inventing a second, worse errno. Python already has
    the path and already raises the right ``OSError`` subclass for it, so the
    cheapest correct answer is to ask it. One extra syscall, on the error path
    only, buys ``except FileNotFoundError`` working the way a caller expects.

    So an unreadable path raises ``FileNotFoundError``, ``PermissionError`` or
    ``IsADirectoryError`` -- the genuine article, with the native core's
    account attached as a note where the interpreter supports one -- rather
    than an FRDError that a caller would have to inspect ``.status`` to
    understand. I/O is the operating system's news to break, not this
    library's.

    If the open unexpectedly succeeds on the retry -- a race, or a file the
    core rejected for a reason the OS does not share -- the native status
    stands rather than being papered over.
    """
    if status == _STATUS_IO:
        try:
            with Path(path).open('rb'):
                pass
        except OSError as exc:
            detail = _native_detail(None)
            if detail and hasattr(exc, 'add_note'):  # Python 3.11+
                exc.add_note(f'pyvista_frd: {detail}')
            raise
    # Either the status was not an I/O failure, or the file opened fine on the
    # retry and the native core's objection stands on its own.
    _raise_for_status(status, _native_detail(None) or str(path))


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
            _raise_for_open_failure(status, path)
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
            _raise_for_status(status, _native_detail(None) or '<memory>')
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

    @property
    def steps_parsed(self) -> int:
        """Number of times a step's values have been parsed.

        Zero until a step is asked for, and thereafter equal to the number of
        distinct steps requested. Exposed so that both halves of the lazy step
        path -- parsed on demand, and parsed at most once -- are things a test
        can assert rather than things the documentation asserts.
        """
        return int(_lib.pvfrd_steps_parsed(self._require_open()))

    def find_array(self, step: int, name: str) -> int:
        """Index of ``name`` within ``step``, or -1."""
        return int(_lib.pvfrd_find_array(self._require_open(), step, name.encode('utf-8')))


# The four FRD format codes, plus the rewrite-only "leave it alone".
FORMAT_KEEP = -1
FORMAT_SHORT_ASCII = 0
FORMAT_LONG_ASCII = 1
FORMAT_BINARY_FLOAT = 2
FORMAT_BINARY_DOUBLE = 3


def _take_buffer(pointer: object, size: int) -> bytes:
    """Copy a library-allocated buffer out and release it.

    Released through the library's own pvfrd_free rather than anything here:
    on Windows the extension and its caller can be linked against different C
    runtimes with different heaps, and freeing across them is not a crash that
    tells you what happened.
    """
    try:
        return ctypes.string_at(pointer, size)
    finally:
        _lib.pvfrd_free(pointer)


def rewrite_bytes(data: bytes, fmt: int = FORMAT_KEEP) -> bytes:
    """Re-emit an FRD document, optionally converting its format.

    With ``FORMAT_KEEP`` this is the identity on well-formed FRD, which is the
    property the byte-match gate checks against files this project did not
    write.
    """
    pointer = POINTER(c_char)()
    size = c_size_t()
    _check(_lib.pvfrd_rewrite_memory(data, len(data), fmt, byref(pointer), byref(size)))
    return _take_buffer(pointer, size.value)


class Writer:
    """Build an FRD document and emit it.

    A context manager, because the native handle has to be released whether or
    not the build succeeds::

        with Writer(FORMAT_LONG_ASCII) as writer:
            writer.set_nodes(points)
            writer.set_cells(cell_types, offsets, connectivity)
            writer.begin_step(1, 1.0)
            writer.add_array('DISP', displacement)
            data = writer.finish()
    """

    def __init__(self, fmt: int = FORMAT_LONG_ASCII) -> None:
        handle = _lib.pvfrd_writer_new(fmt)
        if not handle:
            msg = f'{fmt} is not one of the four FRD format codes'
            raise ValueError(msg)
        self._handle = c_void_p(handle)
        # Held so the buffers stay alive for as long as the writer might read
        # them. ctypes does not keep a reference to what a c_void_p points at,
        # and a temporary numpy array passed inline would be collected between
        # the call that stores it and the call that uses it.
        self._kept: list[NDArray] = []

    def __enter__(self) -> Writer:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._handle:
            _lib.pvfrd_writer_free(self._handle)
            self._handle = c_void_p()

    def _require(self) -> c_void_p:
        if not self._handle:
            msg = 'this writer has been closed'
            raise ValueError(msg)
        return self._handle

    def _keep(self, values, dtype) -> object:  # noqa: ANN001
        array = np.ascontiguousarray(values, dtype=dtype)
        self._kept.append(array)
        return array.ctypes.data_as(c_void_p)

    def set_nodes(self, points, node_ids=None) -> None:  # noqa: ANN001
        """Set the mesh points, ``(n, 3)``, and optionally their FRD ids."""
        xyz = np.ascontiguousarray(points, dtype=np.float64).reshape(-1, 3)
        ids = None if node_ids is None else self._keep(node_ids, np.int64)
        _check(
            _lib.pvfrd_writer_set_nodes(self._require(), len(xyz), ids, self._keep(xyz, np.float64))
        )

    def set_cells(self, cell_types, offsets, connectivity, cell_ids=None, wedge_order=0) -> None:  # noqa: ANN001
        """Set the cells, in the same VTK terms the reader hands back."""
        types = np.ascontiguousarray(cell_types, dtype=np.uint8)
        ids = None if cell_ids is None else self._keep(cell_ids, np.int64)
        _check(
            _lib.pvfrd_writer_set_cells(
                self._require(),
                len(types),
                self._keep(types, np.uint8),
                self._keep(offsets, np.int64),
                self._keep(connectivity, np.int64),
                ids,
                wedge_order,
            )
        )

    def begin_step(self, number: int, time: float) -> None:
        """Open a step. Arrays added after this belong to it."""
        _check(_lib.pvfrd_writer_begin_step(self._require(), number, time))

    def add_array(self, name: str, values, component_names=None, ictype: int = 0) -> None:  # noqa: ANN001
        """Add one nodal array to the open step."""
        data = np.ascontiguousarray(values, dtype=np.float64)
        n_components = 1 if data.ndim == 1 else data.shape[1]
        names = None
        if component_names is not None:
            encoded = [c.encode('utf-8') for c in component_names]
            array = (c_char_p * len(encoded))(*encoded)
            self._kept.append(array)  # type: ignore[arg-type]
            names = ctypes.cast(array, c_void_p)
        _check(
            _lib.pvfrd_writer_add_array(
                self._require(),
                name.encode('utf-8'),
                n_components,
                names,
                ictype,
                self._keep(data, np.float64),
            )
        )

    def finish(self) -> bytes:
        """Emit the document. The writer cannot be added to afterwards."""
        pointer = POINTER(c_char)()
        size = c_size_t()
        _check(_lib.pvfrd_writer_finish(self._require(), byref(pointer), byref(size)))
        return _take_buffer(pointer, size.value)
