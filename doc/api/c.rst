C ABI
=====

The Python package loads the native library with ``ctypes``. The library can
also be used directly from C, C++, WebAssembly, or another language with an
FFI.

The header is `cpp/include/pvfrd/pvfrd.h
<https://github.com/pyvista/pyvista-frd-reader/blob/main/cpp/include/pvfrd/pvfrd.h>`_
and contains the complete public API. The header does not expose C++ types.

Two ownership rules apply:

* Opening a file parses the mesh and indexes the result blocks. Result values
  are parsed when a step is first requested.
* The reader owns every pointer returned by an accessor. Each pointer remains
  valid until ``pvfrd_close``. Several threads may read from one reader.

Locating the library
--------------------

The wheel places the shared library beside the Python package. Use
:func:`pyvista_frd.library_path` to locate it::

   >>> import pyvista_frd
   >>> pyvista_frd.library_path()  # doctest: +SKIP
   '.../site-packages/pyvista_frd/lib/libpvfrd.so'

Building from source
--------------------

The core is a CMake project with no Python dependency::

   cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
   cmake --build build

``-DPVFRD_BUILD_TESTS=ON`` adds the gtest suite. ``cpp/tools`` holds two small
programs that use the library the way another C++ project would: ``frd_dump``
prints a summary of a file, and ``frd_rewrite`` re-emits one in a chosen
format.

Versioning
----------

``pvfrd_abi_version()`` returns the ABI version. Any declaration change,
including an added function, increments this value. Bindings require an exact
match because they declare all expected symbols when loading the library.

======  =================================
ABI     Contents
======  =================================
1       Reading
2       Reading and writing
3       Original element IDs
======  =================================
