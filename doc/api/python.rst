Python API
==========

.. currentmodule:: pyvista_frd

Everything below is importable from the top-level ``pyvista_frd`` package.

Reading
-------

.. autofunction:: read

.. autoclass:: FRDReader
   :members:
   :inherited-members:

Input-deck sets
---------------

.. autofunction:: read_sets

.. autoclass:: INPSets
   :members:

Writing
-------

.. autofunction:: write

.. autofunction:: convert

Diagnostics
-----------

.. autoclass:: Diagnostic
   :members:

.. autoclass:: DiagnosticKind
   :members:

Errors
------

Native-library exceptions inherit from :class:`FRDError` and the corresponding
built-in exception. For example, :class:`FRDFormatError` is also a
:class:`ValueError`.

.. autoexception:: FRDError
.. autoexception:: FRDFormatError
.. autoexception:: FRDRaggedArrayError
.. autoexception:: FRDRangeError
.. autoexception:: FRDInvalidArgumentError
.. autoexception:: FRDMemoryError
.. autoexception:: FRDInternalError
.. autoexception:: NativeUnavailableError

Constants
---------

These constants are importable from the top-level package.

.. autodata:: pyvista_frd.reader.ELEMENT_TYPE_NAMES
   :no-value:

.. autodata:: pyvista_frd._capi.ABI_VERSION

.. autofunction:: library_path

Below the Python layer
----------------------

:class:`NativeFile` provides NumPy arrays directly from the C API without
building a :class:`pyvista.UnstructuredGrid`.

.. autoclass:: NativeFile
   :members:
