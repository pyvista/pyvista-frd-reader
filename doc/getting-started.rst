Getting started
===============

Install
-------

.. code-block:: bash

   pip install pyvista-frd-reader

Wheels are published for Linux (x86_64 and aarch64), macOS (Intel and Apple
silicon) and Windows. They carry a compiled library and no CPython extension
module, so one wheel per platform serves every supported interpreter.

The Linux wheels are ``manylinux_2_28`` -- glibc 2.28 or newer, so RHEL 8,
Debian 10, Ubuntu 20.04 and later. That floor comes from NumPy and VTK rather
than from this package: the core needs only C++17, but a wheel tagged for an
older glibc than its dependencies can be installed alongside would be promising
something that does not work.

Installing from source needs CMake and a C++17 compiler. There is no
pure-Python fallback, deliberately: a reader that silently falls back is
indistinguishable from one that works until someone measures it.

Read a file
-----------

.. code-block:: python

   import pyvista_frd

   mesh = pyvista_frd.read("result.frd")
   mesh.plot(scalars="STRESS_Mises")

:func:`pyvista_frd.read` returns a :class:`pyvista.UnstructuredGrid`. Every
nodal result in the file is attached as point data under the name CalculiX gave
it, and for any six-component ``STRESS`` or ``STRAIN`` array five derived
arrays are appended -- ``_Mises``, ``_sgMises``, and ``_PS1`` through ``_PS3``.

For a file with more than one step, use the reader object:

.. code-block:: python

   reader = pyvista_frd.FRDReader("transient.frd")
   reader.set_active_time_point(3)
   mesh = reader.read()

Write a file
------------

.. code-block:: python

   pyvista_frd.write("out.frd", mesh)               # ASCII
   pyvista_frd.write("out.frd", mesh, binary=True)  # about a third of the size

   # Or convert without building a mesh at all.
   pyvista_frd.convert("binary.frd", "ascii.frd", binary=False)

What it reads
-------------

Element types HE8, PE6, PE15, TE4, HE20, TE10, TR3, TR6, QU4, QU8, BE2, BE3,
PY5 and PY13 -- the last two being CalculiX's experimental pyramids, C3D5 and
C3D13. Both the short and long element-record formats are handled, including
the case CalculiX produces past 9,999 nodes where the node ids in a record run
together with no separator at all.

**All four encodings**, which is a block header's last field: the two ASCII
widths and the two binary ones. Binary FRD is what CalculiX writes from
``*REFINE MESH`` and from a ``DOUBLE`` output card, and PyVista's own reader
cannot open it -- it parses FRD as text, so a binary file yields an empty mesh
or an error. :doc:`binary` covers how that decode is checked.

Elements with the wrong number of nodes, or a type nothing recognises, raise
:class:`pyvista.InvalidMeshWarning` naming the line they were found on.

Relation to PyVista's own reader
--------------------------------

PyVista reads ``.frd`` already, through ``pyvista.FRDReader``. This package
reimplements that reader rather than replacing it, and is graded against it:
:doc:`parity` records a comparison over 1,766 files nobody here wrote, and
:doc:`divergences` lists every place the two deliberately differ, with the test
that pins each one.

Both are Rafal's design. :doc:`history` says whose work this is.
