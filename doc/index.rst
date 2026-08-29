pyvista-frd-reader
==================

Read and write CalculiX ``.frd`` result files as :class:`pyvista.UnstructuredGrid`
objects, backed by a C++ core behind a C ABI.

.. grid:: 1 2 2 3
   :gutter: 3

   .. grid-item-card:: Get started
      :link: getting-started
      :link-type: doc

      Install it, read a file, plot the result.

   .. grid-item-card:: Examples
      :link: gallery/index
      :link-type: doc

      A gallery, every entry run against real solver output.

   .. grid-item-card:: API reference
      :link: api/index
      :link-type: doc

      The Python API and the C ABI underneath it.

.. code-block:: python

   import pyvista_frd

   mesh = pyvista_frd.read("result.frd")
   mesh.plot(scalars="STRESS_Mises")

.. figure:: /gallery/images/sphx_glr_plot_c_time_steps_001.png
   :target: gallery/plot_c_time_steps.html
   :align: center
   :width: 100%

   The first four modes of a cantilever, read from the four steps CalculiX
   wrote for them. :ref:`sphx_glr_gallery_plot_c_time_steps.py`

What it is
----------

CalculiX writes its results to FRD. PyVista has read the ASCII half of that
format since :pr:`8255`; this package reimplements the whole of it in C++ behind
a plain C ABI, so the same answers are available to a caller who is not writing
Python, and adds a writer.

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: All four encodings

      Both ASCII widths and both binary ones. Binary FRD is what CalculiX
      writes from ``*REFINE MESH`` and from a ``DOUBLE`` output card, and an
      ASCII-only reader returns an empty mesh for those files without raising
      anything.

   .. grid-item-card:: A writer graded on CalculiX's bytes

      A document read and emitted again is the input byte for byte, over 1,111
      external files. CalculiX itself reads what this package writes.

   .. grid-item-card:: Agreement, measured

      1,766 FRD files nobody here wrote, compared array by array against
      PyVista's reader. Zero divergences.

   .. grid-item-card:: ctypes, not an extension module

      One wheel per platform serves every supported interpreter. The core is
      also usable from C++, or from WebAssembly, with no Python involved.

.. toctree::
   :hidden:
   :caption: Using it

   getting-started
   gallery/index

.. toctree::
   :hidden:
   :caption: Reference

   api/index
   writing
   binary

.. toctree::
   :hidden:
   :caption: How it is checked

   parity
   divergences
   history
