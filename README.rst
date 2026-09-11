pyvista-frd-reader
==================

Read and write CalculiX FRD files with PyVista. The Python API returns a
``pyvista.UnstructuredGrid``; the C API exposes the same parser without a
Python dependency.

.. code:: python

   import pyvista_frd

   mesh = pyvista_frd.read("result.frd")
   mesh.plot(scalars="STRESS_Mises")

Install
-------

.. code:: bash

   pip install pyvista-frd-reader

Wheels are available for Linux, macOS, and Windows. Linux wheels require
glibc 2.28 or newer. A source build requires CMake and a C++17 compiler.
There is no pure-Python fallback.

Read time steps
---------------

Use ``FRDReader`` when a file contains more than one result step:

.. code:: python

   reader = pyvista_frd.FRDReader("transient.frd")
   print(reader.time_values)

   reader.set_active_time_point(3)
   mesh = reader.read()

The reader implements PyVista's time-reader interface. Result blocks are
indexed when the file is opened and parsed when their step is first read.

Read node and element sets
--------------------------

Supply a companion input deck to attach boolean set masks to the result:

.. code:: python

   mesh = pyvista_frd.read("model.frd", inp_path="model.inp")
   body = mesh.extract_cells(mesh.cell_data["ELSET:BODY"])
   fixed = mesh.extract_points(mesh.point_data["NSET:FIXED"])

``pyvista_frd.read_sets("model.inp")`` returns the original set IDs without
an FRD file. Includes, generated ranges, and references to earlier sets are
supported. See `Node and element sets <https://frd-reader.pyvista.org/sets.html>`_
for naming, missing-ID behavior, and limitations.

Named surfaces
--------------

Extract faces using the companion deck's ``*SURFACE`` definitions, with all
nodal results from the active step:

.. code:: python

   reader = pyvista_frd.FRDReader("model.frd", inp_path="model.inp")
   wall = reader.read_surface("WALL")
   wall.plot(scalars="STRESS_Mises")
   surfaces = reader.read_surfaces()  # named MultiBlock

Solid faces retain quadratic midside nodes. Shell sides, planar edges,
expanded beam/shell faces, internal faces, and nodal surfaces are supported.
See `Named surfaces <https://frd-reader.pyvista.org/surfaces.html>`_ for face
numbering, missing-ID handling, dataset validation, and two runnable galleries
with all required result files and companion decks included in the source.

Write and convert files
-----------------------

.. code:: python

   pyvista_frd.write("result_ascii.frd", mesh)
   pyvista_frd.write("result_binary.frd", mesh, binary=True)

   # Convert the records without building a PyVista mesh.
   pyvista_frd.convert("result_binary.frd", "result_ascii.frd", binary=False)

ASCII output stores six significant digits. Binary output is smaller and
retains the stored floating-point values. See
`Writing FRD <https://frd-reader.pyvista.org/writing.html>`_ for format and
round-trip details.

Supported FRD data
------------------

The reader supports the two ASCII encodings and the ``float32`` and
``float64`` binary encodings. It reads short and long element records,
including fixed-width records whose node IDs have no separating spaces.

Supported element types are HE8, PE6, PE15, TE4, HE20, TE10, TR3, TR6, QU4,
QU8, BE2, BE3, PY5, and PY13. PY5 and PY13 are the experimental CalculiX
pyramid types C3D5 and C3D13.

For each six-component array whose name contains ``STRESS`` or ``STRAIN``, the
reader adds:

- ``<NAME>_Mises``: von Mises magnitude
- ``<NAME>_sgMises``: von Mises magnitude signed by the tensor trace
- ``<NAME>_PS1``, ``_PS2``, and ``_PS3``: principal values, largest first

Invalid and unsupported elements produce ``pyvista.InvalidMeshWarning`` with
the source line number. Points use ``float64`` storage. VTK cell connectivity
uses 32-bit storage when it fits, otherwise 64-bit storage.

Relationship to PyVista
-----------------------

PyVista includes a Python FRD reader. This package provides a separate C++
implementation and does not replace ``pyvista.FRDReader`` or register itself
as the handler for ``pyvista.read``.

The conformance suite compares the two readers file by file and array by
array. The current external sweep covers 1,766 files with no undocumented
divergences. The principal-value comparison uses a numerical tolerance because
the implementations use different eigensolvers. Binary FRD is checked against
paired ASCII and binary output from CalculiX because PyVista's reader supports
ASCII only.

See `Parity <https://frd-reader.pyvista.org/parity.html>`_ for the corpus,
method, results, and limitations. See
`Divergences <https://frd-reader.pyvista.org/divergences.html>`_ for the exact
behavioral and numerical differences.

C API
-----

The public header is ``cpp/include/pvfrd/pvfrd.h``. It uses a C ABI and can be
called from C, C++, or another language with a foreign-function interface.

.. code:: bash

   cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
   cmake --build build

.. code:: c

   #include <pvfrd/pvfrd.h>

   pvfrd_file *file = NULL;
   if (pvfrd_open("mesh.frd", &file) != PVFRD_OK) { /* handle error */ }

   const double *points = pvfrd_points(file);
   uint64_t n_points = pvfrd_n_points(file);

   pvfrd_close(file);

The shared library has no additional link dependencies. Static linking with
GCC or Clang also requires ``-lstdc++ -lm``.

Development
-----------

.. code:: bash

   cmake -S cpp -B cpp/build -DPVFRD_BUILD_TESTS=ON
   cmake --build cpp/build
   ./cpp/build/pvfrd_tests

   pip install -e .[tests]
   pytest

The C++ and Python suites share the fixtures in ``tests/fixtures``.
``tools/mutate.py`` applies known parser and writer defects and verifies that
the intended tests fail.

Documentation
-------------

The `documentation <https://frd-reader.pyvista.org>`_ includes installation,
examples, the Python and C APIs, format notes, and verification results.

Credit
------

Rafal (`@3rav <https://github.com/3rav>`_) wrote PyVista's original FRD reader
in `pyvista#8255 <https://github.com/pyvista/pyvista/pull/8255>`_. This package
reimplements that behavior and vendors the PyVista reader as its conformance
reference. Guido Dhondt and Klaus Wittig created CalculiX and its FRD format.
See `History and credit <https://frd-reader.pyvista.org/history.html>`_.

License
-------

This project is MIT licensed. The vendored ``fast_float`` header is available
under Apache-2.0, MIT, or BSL terms.
