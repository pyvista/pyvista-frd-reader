# Differences from PyVista

The conformance suite expects this reader to match PyVista unless a difference
is listed here. Report any unlisted difference as a bug.

Behavioral differences change the returned data or error. Numerical
differences affect floating-point results and use an explicit tolerance. The
final section covers differences between this writer and CalculiX.

## Numerical difference

### Principal values use a different eigensolver

`<NAME>_PS1`, `_PS2`, and `_PS3` are the eigenvalues of a symmetric 3 by 3
tensor. PyVista uses `numpy.linalg.eigvalsh`, backed by LAPACK. This package
uses cyclic Jacobi so the C++ library does not depend on LAPACK.

The conformance tolerance is 32 ulp of the source tensor's magnitude. It is not
scaled by the eigenvalue because a value near zero has poor relative
conditioning. The maximum difference in the current corpus is 1.09 ulp of the
tensor magnitude.

A benchmark over two million tensors, using the best of five interleaved runs,
measured 238 ns per tensor for Jacobi and 635 ns for LAPACK `dsyev`. The LAPACK
call used preallocated workspace and `jobz='N'`.

Von Mises and signed von Mises values are bit-identical. The C++ expressions
use PyVista's association order, and floating-point contraction is disabled
with `-ffp-contract=off` or `/fp:precise`.

Pinned by
`tests/conformance/test_corpus_parity.py::test_arrays_match_reference` and the
`mises-reassociated` mutant in `tools/mutate.py`.

## Behavioral differences

### Original node IDs are integers

`original_node_ids` uses `int32` when all IDs lie between -2,147,483,648 and
2,147,483,647 inclusive, and `int64` otherwise. The original reference reader
and earlier versions of this package returned strings. Compare IDs against
integers instead of strings. Node numbering and point order are preserved.

Integer storage also avoids the VTK 9.7.0 string-array crash when calling
`point_data_to_cell_data()` on a mesh returned by this reader. The underlying
VTK issue can still affect user-added string arrays.

Pinned by `test_original_node_ids_are_integers`, `test_original_node_id_width`,
and `test_integer_node_ids_round_trip_and_point_to_cell` in `tests/test_reader.py`.

### Integers are limited to ASCII and int64

PyVista uses Python's `int()`, which accepts Unicode digits and arbitrary-size
integers. This parser accepts ASCII digits and values representable by
`int64`. It also accepts underscores between digits, matching Python.

Node IDs outside `int64` cannot be represented in the arrays they index.
Supporting Unicode digits would require the file's byte encoding to be known,
which FRD does not declare.

Pinned by `TextTest.ParseIntAcceptsWhatPythonIntAccepts`,
`TextTest.ParseIntBoundaries`, and
`TextTest.UnderscoresBetweenDigitsParseAsPythonParsesThem`.

### Non-ASCII whitespace is not locale-dependent

Within ASCII, this parser matches Python's `strip()`, `split()`, `int()`, and
`float()` behavior, including C0 information separators where applicable.

Outside ASCII, PyVista's behavior depends on the locale used to decode the
file. The same UTF-8 bytes can be whitespace under a UTF-8 locale and ordinary
characters under a Windows code page. This package parses bytes directly and
does not treat non-ASCII bytes as whitespace.

Pinned by `TextTest.TheInformationSeparatorsAreWhitespaceToStripAndSplit`,
`TextTest.TheInformationSeparatorsAreNotWhitespaceToIntAndFloat`,
`TextTest.TheTwoWhitespaceSetsDifferByExactlyTheSeparators`, and
`tests/conformance/test_bytes_and_str.py`.

### Field widths count bytes

Element-record format detection and fixed-width splitting count bytes here and
decoded characters in PyVista. CalculiX element records contain only ASCII
digits and spaces, so the readers agree on generated files. A multibyte
character inside an element record could select a different width.

Pinned by the format-detection tests in `cpp/tests/test_parse.cpp`.

### Ragged result blocks raise an FRD error

If nodes in one result block have different component counts, PyVista raises a
NumPy `ValueError`. This package raises `FRDRaggedArrayError`, which is also an
`FRDFormatError` and `ValueError`. Its message includes the node and component
counts.

Pinned by
`tests/conformance/test_corpus_parity.py::test_ragged_block_is_an_error_in_both`.

### Wedge ordering is explicit in the C API

VTK changed the PE6 linear-wedge node order in VTK 9.7. The Python layer reads
the installed VTK version and selects the matching order. The C++ core cannot
infer whether its arrays will be passed to VTK.

C and C++ callers must use `PVFRD_WEDGE_SWAP` for VTK earlier than 9.7 and
`PVFRD_WEDGE_ASIS` for VTK 9.7 or later.

Pinned by `ParseTest.WedgeOrderOptionSwapsOnlyTheWedge` and
`test_wedge_order_option_actually_changes_the_wedge`.

### PY5 and PY13 are not in a released PyVista version

This package supports the experimental C3D5 and C3D13 pyramid elements.
PyVista support is proposed in
[pyvista#8936](https://github.com/pyvista/pyvista/pull/8936), which remains
open. Until it is merged and released, installed PyVista versions warn that
these element types are unknown.

The conformance reference includes the implementation from that pull request.
The diagnostic comparison against installed PyVista skips the pyramid fixtures.

Pinned by `tests/test_reader.py::test_pyramid_nodes_land_unpermuted` and the
skip list in `tests/conformance/test_diagnostics_parity.py`.

## Writer difference from CalculiX

### Binary-to-ASCII conversion formats the stored double

CalculiX casts each value to `float32` before writing ASCII. This writer formats
the `float64` value it holds. Both use six significant digits, but they can
differ at a rounding tie. For example:

```text
float64 value: 6.464285098e-04
this writer:   6.46429E-04
CalculiX:      6.46428E-04
```

Across the 12 paired binary and ASCII fixtures, 25 of 825 record lines differ.
Each difference is one final digit at a rounding tie. This affects conversion
from binary to ASCII. Reading and writing a file in its original encoding is
byte-identical across 1,111 external FRD files.

Pinned by `test_converted_ascii_is_the_double_rounded_not_the_float`,
`test_the_float_cast_explains_a_few_percent_and_no_more`, and the
`writer-narrows-through-float32` mutant.

## Equivalent behavior with different timing

- Result arrays are parsed on demand. PyVista parses all results when the file
  is opened. This package indexes blocks at open and parses a step when it is
  first requested.
- Invalid-element warnings are emitted when `FRDReader` is constructed, not
  when `read()` is called. Both readers parse the mesh during construction.
