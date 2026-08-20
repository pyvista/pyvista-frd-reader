# Where this reader differs from PyVista's

This library exists to read the files PyVista reads and produce the arrays
PyVista produces. Everywhere the two differ, it is on purpose, and it is
listed here with the test that pins it. A difference not on this list is a
bug — please report it.

Two kinds of entry appear below. **Behavioural** differences change what a
caller gets back. **Numerical** differences change the last bits of a value.
They are not interchangeable, and the conformance suite treats them
differently: behavioural agreement is asserted exactly, and only the one
numerical entry is given a tolerance.

## Numerical

### Principal stresses and strains agree to within 32 ulp of the tensor

`<NAME>_PS1`, `_PS2` and `_PS3` are eigenvalues of a symmetric 3×3. PyVista
gets them from `numpy.linalg.eigvalsh`, which is LAPACK; this library uses
cyclic Jacobi, so that the C++ core has no LAPACK dependency and the same
numbers are available to a caller in any language.

Reproducing LAPACK's last bit is not an achievable goal, so the suite states a
band instead. The band is on the **absolute** difference divided by the
magnitude of the tensor the eigenvalues came from — not by the eigenvalue.
That choice is the substance of this entry:

> An eigenvalue close to zero has no relative accuracy to speak of. Measured
> the usual way, a strain tensor of order 1e-20 produces relative differences
> of order 1e+262 between two implementations that are both correct. Scaling
> by the tensor's magnitude is the measurement that means something, and it is
> what backward stability actually promises.

Measured across the whole corpus, including a real CalculiX file: **maximum
1.09 ulp** of the tensor magnitude. The band is set at 32 ulp, and every
failure prints the measured figure alongside the bound, so a red distinguishes
a regression from a runner with a different LAPACK.

Everything else is bit-identical, including `<NAME>_Mises` and `_sgMises`.
That is not luck: the expressions in `cpp/src/derived.cpp` are written in the
same association order as PyVista's NumPy expression, and the build sets
`-ffp-contract=off` (`/fp:precise` on MSVC) so the compiler cannot fuse a
multiply and an add into an FMA. Without that flag the values would differ,
and only on hardware that has the instruction — a difference no one would
think to look for.

*Pinned by* `tests/conformance/test_corpus_parity.py::test_arrays_match_reference`
and the `mises-reassociated` mutant in `tools/mutate.py`.

## Behavioural

### Integer fields must be ASCII digits within int64

PyVista parses node ids and element types with Python's `int()`, which accepts
digit-group underscores (`1_000`), non-ASCII digit characters, and integers of
unbounded size. This library accepts an optional sign and ASCII digits, and
refuses anything outside the range of a signed 64-bit integer.

Every case in that gap is one where PyVista accepts a record this library
drops. No file written by CalculiX contains one.

*Pinned by* `TextTest.ParseIntAcceptsWhatPythonIntAccepts` and
`TextTest.ParseIntBoundaries`.

### Whitespace is the ASCII set

PyVista reads the file as text, so `str.strip()` treats Unicode space
characters — U+00A0 and friends — as whitespace. This library works on bytes
and strips the ASCII set only. FRD is an ASCII format; a file with a
non-breaking space where a space belongs would be tokenised differently by the
two readers.

*Pinned by* `TextTest.NonAsciiWhitespace`.

### Field widths are counted in bytes, not characters

The element-record format test (`> 50` characters) and the fixed-width field
split both count bytes here and characters in PyVista. The two agree for any
ASCII content, which is every element record CalculiX writes — element records
contain nothing but digits and spaces. A multi-byte character inside one would
make the readers choose different widths.

*Pinned by* the format-detection tests in `cpp/tests/test_parse.cpp`.

### A ragged result block is an error rather than an exception

A block whose first node carries six components and a later node three cannot
become an array. PyVista raises `ValueError` from NumPy's assignment; this
library returns `PVFRD_E_RAGGED` with a message naming the node and the two
counts.

The outcome is the same — neither reader stores a short row — but the error
type and message differ. That difference is deliberate: a status code is what
crosses a C ABI, and the detail a caller needs is in `pvfrd_last_error`.

*Pinned by* `tests/conformance/test_corpus_parity.py::test_ragged_block_is_an_error_in_both`.

### PE6 wedge ordering is an argument, not a lookup

PyVista's parser checks `pyvista.vtk_version_info < (9, 7)` inside the parse
and swaps the linear wedge's node order accordingly. The C++ core cannot see
which VTK its cells are destined for — it may not be handing them to VTK at
all — so the choice is an open option, and the Python layer supplies it from
the installed VTK.

A C++ caller who wants PyVista's answer must set `PVFRD_WEDGE_SWAP` for
VTK < 9.7 and `PVFRD_WEDGE_ASIS` otherwise. There is deliberately no automatic
value: there is nothing to detect it from.

*Pinned by* `ParseTest.WedgeOrderOptionSwapsOnlyTheWedge` and
`test_wedge_order_option_actually_changes_the_wedge`.

### PY5 and PY13 are read here and not yet in released PyVista

CalculiX's experimental pyramids (C3D5 and C3D13) are supported by this
library. PyVista gains them in
[pyvista#8936](https://github.com/pyvista/pyvista/pull/8936), which is not in a
release yet. Until it is, a file using them reads here and produces an
"unknown element type" warning there.

The conformance suite's vendored oracle is taken from that pull request, so
the parity sweep grades these elements. The warning-parity sweep, which grades
against the *installed* PyVista, skips the pyramid fixtures by name and says
why.

*Pinned by* `tests/test_reader.py::test_pyramid_nodes_land_unpermuted`, and by
the skip list in `tests/conformance/test_diagnostics_parity.py`.

## Not differences

Two things look like differences and are not:

- **Time steps are materialised on demand.** PyVista parses every value of
  every step at open. This library indexes the blocks at open and parses a
  step's values when that step is first asked for. The arrays are identical;
  only when the work happens differs.
- **Warnings are raised at construction.** Both readers warn when the reader
  is constructed, not when `read()` is called, because construction is where
  the file is parsed.
