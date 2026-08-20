"""Read CalculiX FRD result files into PyVista, backed by a C++ core.

The parser is C++ behind a plain C ABI (``cpp/include/pvfrd/pvfrd.h``), so the
same implementation serves Python here, a C++ program linking the library, and
anything else with a foreign-function interface. This package is the PyVista
half of it: it converts what the core produced into an
:class:`pyvista.UnstructuredGrid`.

Examples
--------
>>> import pyvista_frd
>>> mesh = pyvista_frd.read('mesh.frd')  # doctest: +SKIP

"""

from __future__ import annotations

from ._capi import ABI_VERSION as ABI_VERSION
from ._capi import Diagnostic as Diagnostic
from ._capi import DiagnosticKind as DiagnosticKind
from ._capi import FRDError as FRDError
from ._capi import NativeFile as NativeFile
from ._capi import NativeUnavailableError as NativeUnavailableError
from ._capi import library_path as library_path
from .reader import ELEMENT_TYPE_NAMES as ELEMENT_TYPE_NAMES
from .reader import FRDReader as FRDReader
from .reader import read as read

try:
    from ._version import __version__
except ImportError:  # pragma: no cover - a source tree with no build behind it
    __version__ = '0.0.0.dev0'

__all__ = [
    'ABI_VERSION',
    'ELEMENT_TYPE_NAMES',
    'Diagnostic',
    'DiagnosticKind',
    'FRDError',
    'FRDReader',
    'NativeFile',
    'NativeUnavailableError',
    '__version__',
    'library_path',
    'read',
]
