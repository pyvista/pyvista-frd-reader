pyvista-frd-reader
==================

Read CalculiX FRD result files. The parser is C++ behind a plain C ABI, so the
same implementation serves Python, C++, and anything else with a
foreign-function interface — and the Python side turns what it produced into a
``pyvista.UnstructuredGrid``.

.. code:: python

   import pyvista_frd

   mesh = pyvista_frd.read("mesh.frd")
   mesh.plot(scalars="STRESS_Mises")

Time steps work the way PyVista's reader does:

.. code:: python

   reader = pyvista_frd.FRDReader("mesh.frd")
   reader.time_values          # [0.5, 1.0]
   reader.set_active_time_value(1.0)
   mesh = reader.read()

Installation
------------

.. code:: bash

   pip install pyvista-frd-reader

Wheels are published for Linux (x86_64 and aarch64), macOS (Intel and Apple
silicon) and Windows. They contain a compiled library and no CPython extension
module, so one wheel per platform serves every supported interpreter.

The Linux wheels are ``manylinux_2_28``, meaning glibc 2.28 or newer -- RHEL 8,
Debian 10, Ubuntu 20.04 and later. That floor comes from NumPy and VTK, not
from this package: the core needs only C++17, but a wheel tagged for an older
glibc than its own dependencies can be installed on would promise something
that does not work.

Installing from source needs CMake and a C++17 compiler: there is no
pure-Python fallback, because a reader that silently falls back is
indistinguishable from one that works until someone measures it.

What it reads
-------------

Element types HE8, PE6, PE15, TE4, HE20, TE10, TR3, TR6, QU4, QU8, BE2, BE3,
PY5 and PY13 — the last two being CalculiX's experimental pyramids, C3D5 and
C3D13. Both the short and long element-record formats are handled, including
the case CalculiX produces past 9999 nodes, where the node ids in a record run
together with no separator at all.

For any 6-component tensor whose name contains ``STRESS`` or ``STRAIN``, the
reader appends the derived arrays PyVista's reader appends:

- ``<NAME>_Mises`` — equivalent von Mises magnitude
- ``<NAME>_sgMises`` — signed by the trace
- ``<NAME>_PS1``, ``_PS2``, ``_PS3`` — principal values, largest first

Elements with the wrong number of nodes, or a type nothing recognises, raise
``pyvista.InvalidMeshWarning`` naming the line they were found on.

Speed
-----

Not why this exists -- multi-language reuse is -- but the question follows the
language, so it is measured rather than asserted. Against PyVista's reader,
reading the same file to the same grid:

=========================  ==========  ==========  =====
file                       pyvista_frd     pyvista  ratio
=========================  ==========  ==========  =====
``mesh.frd`` (0.14 MB)        3.15 ms     8.14 ms   2.6x
synthetic (12.8 MB)          85.7 ms      531 ms    6.2x
=========================  ==========  ==========  =====

Medians of interleaved runs on one workstation. Treat the ratio as indicative
and the absolute figures as a property of that machine -- ``benchmarks/read_speed.py``
reproduces both, and interleaves the two arms rather than running one after
the other, because a machine that drifts mid-run otherwise charges the drift
to whichever arm was unlucky.

The ratio grows with file size because both readers pay the same fixed cost to
build the VTK grid at the end; only the parse differs. On a small file that
fixed cost is most of the work.

Relationship to PyVista's reader
--------------------------------

PyVista ships its own ``.frd`` reader, written in Python. This package is a
reimplementation of it, and *agreement with it is the claim being made*: the
conformance suite compares every array of every file in the corpus against
PyVista's own parser, bit for bit, and the exceptions are listed in
`doc/divergences.md <doc/divergences.md>`_ with the test that pins each one.

This package deliberately does **not** register itself as PyVista's ``.frd``
handler. Doing so today would make ``pv.read`` use this reader while
``pv.get_reader`` kept the built-in — two readers for one extension, differing
by which call the user made. Overriding it properly is a follow-up.

Using it from C++
-----------------

The core builds standalone and installs a header and a library:

.. code:: bash

   cmake -S cpp -B build -DCMAKE_BUILD_TYPE=Release
   cmake --build build

``cpp/include/pvfrd/pvfrd.h`` is the whole public surface. It is plain C with
no C++ types crossing the boundary:

.. code:: c

   #include <pvfrd/pvfrd.h>

   pvfrd_file *file = NULL;
   if (pvfrd_open("mesh.frd", &file) != PVFRD_OK) { /* handle it */ }

   const double *points = pvfrd_points(file);
   uint64_t n_points = pvfrd_n_points(file);

   int64_t index = pvfrd_find_array(file, /* step */ 0, "STRESS_Mises");
   const double *mises = NULL;
   pvfrd_array_data(file, 0, index, &mises);

   pvfrd_close(file);

Opening a file parses the mesh and indexes the result blocks; a step's values
are parsed when that step is first asked for, so reading one time step of a
many-step file does not pay for the rest. ``pvfrd_open_memory`` takes bytes you
already have, for callers holding the file in an archive or an HTTP response.

Development
-----------

.. code:: bash

   cmake -S cpp -B cpp/build -DPVFRD_BUILD_TESTS=ON
   cmake --build cpp/build
   ./cpp/build/pvfrd_tests                      # the C++ tier

   pip install -e .[tests]
   pytest                                       # conformance against PyVista

Both tiers read the same fixture corpus under ``tests/fixtures/``.

``tools/mutate.py`` breaks the C++ on purpose — twenty-one plausible mistakes,
one at a time — and checks that the suite reddens for each. A green suite has
two explanations, and that script is what tells them apart. It is also how the
corpus grew: two mutants survived the first sweep, and the files that now
catch them were written in response.

License
-------

MIT. The vendored ``fast_float`` header under ``cpp/third_party/`` is
Apache-2.0 / MIT / BSL at your option.
