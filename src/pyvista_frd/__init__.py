"""Read and write CalculiX FRD files with PyVista.

The Python API converts arrays from the C++ parser into
:class:`pyvista.UnstructuredGrid` objects. The same parser is available through
the C API in ``cpp/include/pvfrd/pvfrd.h``.

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
from ._capi import FRDFormatError as FRDFormatError
from ._capi import FRDInternalError as FRDInternalError
from ._capi import FRDInvalidArgumentError as FRDInvalidArgumentError
from ._capi import FRDMemoryError as FRDMemoryError
from ._capi import FRDRaggedArrayError as FRDRaggedArrayError
from ._capi import FRDRangeError as FRDRangeError
from ._capi import NativeFile as NativeFile
from ._capi import NativeUnavailableError as NativeUnavailableError
from ._capi import library_path as library_path
from .reader import ELEMENT_TYPE_NAMES as ELEMENT_TYPE_NAMES
from .reader import FRDReader as FRDReader
from .reader import convert as convert
from .reader import read as read
from .reader import write as write
from .sets import INPSets as INPSets
from .sets import read_sets as read_sets

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
    'FRDFormatError',
    'FRDInternalError',
    'FRDInvalidArgumentError',
    'FRDMemoryError',
    'FRDRaggedArrayError',
    'FRDRangeError',
    'FRDReader',
    'INPSets',
    'NativeFile',
    'NativeUnavailableError',
    '__version__',
    'convert',
    'library_path',
    'read',
    'read_sets',
    'write',
]
