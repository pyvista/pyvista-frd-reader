Getting started
===============

Install
-------

.. code-block:: bash

   pip install pyvista-frd-reader

Wheels are available for Linux (x86_64 and aarch64), macOS (Intel and Apple
silicon), and Windows.

Linux wheels use ``manylinux_2_28`` and require glibc 2.28 or newer. This
includes RHEL 8, Debian 10, Ubuntu 20.04, and later releases.

A source build requires CMake and a C++17 compiler. The package has no
pure-Python fallback.

Read a file
-----------

.. code-block:: python

   import pyvista_frd

   mesh = pyvista_frd.read("result.frd")
   mesh.plot(scalars="STRESS_Mises")

:func:`pyvista_frd.read` returns a :class:`pyvista.UnstructuredGrid`. Nodal
results are stored as point data under their CalculiX names. Six-component
``STRESS`` and ``STRAIN`` arrays also produce ``_Mises``, ``_sgMises``, and
``_PS1`` through ``_PS3`` arrays.

``mesh.point_data["original_node_ids"]`` stores the original FRD node numbers
as integers: ``int32`` when every ID fits in the signed 32-bit range,
otherwise ``int64``. The width depends on the ID values, not the number of
points. Compare IDs numerically, for example
``mesh.point_data["original_node_ids"] == 42``. Earlier versions returned
strings and required comparisons against ``"42"``.

``mesh.point_data_to_cell_data()`` can average the numeric nodal results
directly. Any averaged node-ID array is metadata with no physical meaning;
it does not identify the element. This filter averages existing nodal values
and does not recover element integration-point results.

For a file with more than one step, use the reader object:

.. code-block:: python

   reader = pyvista_frd.FRDReader("transient.frd")
   reader.set_active_time_point(3)
   mesh = reader.read()

Write a file
------------

.. code-block:: python

   pyvista_frd.write("out_ascii.frd", mesh)
   pyvista_frd.write("out_binary.frd", mesh, binary=True)

   # Or convert without building a mesh at all.
   pyvista_frd.convert("binary.frd", "ascii.frd", binary=False)

What it reads
-------------

Supported element types are HE8, PE6, PE15, TE4, HE20, TE10, TR3, TR6, QU4,
QU8, BE2, BE3, PY5, and PY13. PY5 and PY13 are the experimental CalculiX
pyramid types C3D5 and C3D13. The parser handles short and long fixed-width
element records, including records with adjacent node IDs.

The package reads both ASCII encodings and the ``float32`` and ``float64``
binary encodings. CalculiX writes binary FRD for ``*REFINE MESH`` and ``DOUBLE``
output cards. PyVista's built-in reader reads ASCII FRD only. See :doc:`binary`
for the record layout and test coverage.

Elements with an invalid node count or an unsupported type produce
:class:`pyvista.InvalidMeshWarning` with the source line number.

Relation to PyVista's own reader
--------------------------------

PyVista already reads ASCII FRD through ``pyvista.FRDReader``. This package is
a separate implementation and does not replace PyVista's reader. :doc:`parity`
reports the external comparison; :doc:`divergences` lists known differences.
:doc:`history` records the implementation history and credit.
