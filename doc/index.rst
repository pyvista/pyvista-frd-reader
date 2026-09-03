pyvista-frd-reader
==================

Read and write CalculiX ``.frd`` result files as
:class:`pyvista.UnstructuredGrid` objects. The parser is also available through
a C API.

.. grid:: 1 2 2 3
   :gutter: 3

   .. grid-item-card:: Get started
      :link: getting-started
      :link-type: doc

      Install the package, read a file, and select result steps.

   .. grid-item-card:: Examples
      :link: gallery/index
      :link-type: doc

      Read, plot, convert, and inspect solver output.

   .. grid-item-card:: API reference
      :link: api/index
      :link-type: doc

      Python classes, functions, errors, and the C API.

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

Capabilities
------------

CalculiX writes analysis results to FRD files. This package reads all four FRD
encodings, writes long ASCII and binary FRD, and converts record encodings.

.. grid:: 1 2 2 2
   :gutter: 2

   .. grid-item-card:: Four encodings

      Read short ASCII, long ASCII, binary ``float32``, and binary ``float64``
      records. Preserve or convert their encodings.

   .. grid-item-card:: FRD writer

      Write PyVista meshes to FRD or convert an existing file without building
      a mesh.

   .. grid-item-card:: PyVista compatibility

      The conformance suite compares mesh and result arrays with PyVista's
      built-in reader.

   .. grid-item-card:: C API

      Use the parser from C, C++, WebAssembly, or another language with a
      foreign-function interface.

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
