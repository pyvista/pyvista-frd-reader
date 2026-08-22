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

Every exception this package raises is both an :class:`FRDError` and the
built-in a caller would have expected, so ``except ValueError`` and
``except FRDError`` both work.

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

An attribute docstring is only visible to autodoc in the module that makes the
assignment, so these are documented from there. Both are importable from the
top-level package.

.. autodata:: pyvista_frd.reader.ELEMENT_TYPE_NAMES
   :no-value:

.. autodata:: pyvista_frd._capi.ABI_VERSION

.. autofunction:: library_path

Below the Python layer
----------------------

:class:`NativeFile` is the thin ctypes binding over the C ABI. It is public so
that a caller who wants the arrays without a :class:`pyvista.UnstructuredGrid`
around them -- or who is measuring what the Python layer costs -- does not have
to reach into a private module.

.. autoclass:: NativeFile
   :members:
