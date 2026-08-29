C ABI
=====

The Python package is a ctypes binding over a shared library. That library is
the whole implementation, and it is usable without Python: from C, from C++, or
from WebAssembly.

The header is `cpp/include/pvfrd/pvfrd.h
<https://github.com/pyvista/pyvista-frd-reader/blob/main/cpp/include/pvfrd/pvfrd.h>`_
and is the complete public surface. Nothing in it is C++, so it binds from any
language with an FFI.

Two things to know before reading it:

* Opening a file parses the mesh and *indexes* the result blocks. A step's
  values are materialised when that step is first asked for, so opening a
  500-step file and reading one step does not pay for the other 499.
* Every pointer an accessor returns is owned by the reader and stays valid
  until ``pvfrd_close``. A reader is immutable apart from that per-step
  materialisation, which is guarded, so several threads may read from one
  reader at once.

Locating the library
--------------------

The wheel ships the shared library beside the Python package.
:func:`pyvista_frd.library_path` returns it, which is what a C++ project
vendoring this package would link against::

   >>> import pyvista_frd
   >>> pyvista_frd.library_path()  # doctest: +SKIP
   PosixPath('.../site-packages/pyvista_frd/lib/libpvfrd.so')

Building from source
--------------------

The core is a CMake project with no dependency on Python at all::

   cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
   cmake --build build

``-DPVFRD_BUILD_TESTS=ON`` adds the gtest suite. ``cpp/tools`` holds two small
programs that use the library the way another C++ project would: ``frd_dump``
prints a summary of a file, and ``frd_rewrite`` re-emits one in a chosen
format.

Versioning
----------

``pvfrd_abi_version()`` returns an integer that is bumped on **any** change to
the declarations in the header, additions included. The check is an equality
rather than a floor, because a binding declares every symbol it knows about up
front: meeting an older library that is missing one would otherwise fail at
bind time with an error naming the symbol rather than the version.

======  =========================
ABI     Contents
======  =========================
1       Reading
2       Reading and writing
======  =========================
