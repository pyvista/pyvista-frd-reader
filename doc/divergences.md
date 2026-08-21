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

That is not a speed sacrifice, which is the natural assumption. Measured over
two million tensors, best of five interleaved repeats: Jacobi 238 ns each,
LAPACK `dsyev` 635 ns — and LAPACK was given every advantage, called directly
with preallocated workspace and `jobz='N'` so it neither allocates nor
computes eigenvectors. A 3×3 is all call overhead and no work; LAPACK's
advantage is asymptotic and there is no asymptote here. The closed-form
trigonometric solution is faster still at 62 ns, and lands 268 ulp from LAPACK
where Jacobi lands 9.9, so it does not fit the band below.

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

### Integer fields must be within int64, and their digits ASCII

PyVista parses node ids and element types with Python's `int()`. Three things
that accepts and a naive byte parser does not: digit-group underscores
(`1_000`), non-ASCII digit characters, and integers of unbounded size.

**Underscores are no longer a difference.** They are ASCII, the rule is small
— an underscore must have a digit immediately either side, for `int()` and
`float()` alike — and this library now applies it. It had been grouped with
the other two under one heading, which made the cheap third of the entry look
as settled as the expensive two thirds.

What remains:

- **Non-ASCII digits.** `int('١٢٣')` is 123 to Python. Matching that means a
  Unicode `Nd` table, and it is also in the locale-dependent family below:
  whether those bytes even become digit characters depends on the decoding.
- **Unbounded integers.** Python has no upper bound; an `int64` does. This one
  would not be worth closing even if it were free — a node id past `int64` has
  nowhere to go in the arrays it indexes, so accepting it would change which
  record is dropped, not whether one is.

*Pinned by* `TextTest.ParseIntAcceptsWhatPythonIntAccepts`,
`TextTest.ParseIntBoundaries` and
`TextTest.UnderscoresBetweenDigitsParseAsPythonParsesThem`.

### Non-ASCII whitespace has no answer to agree with

PyVista reads the file as text, so `str.strip()` and `str.split()` treat
Unicode space characters as whitespace. This library works on bytes.

**Within ASCII the two now agree exactly**, which they did not before. Python
treats `0x1C`–`0x1F`, the C0 information separators, as whitespace for
`strip()` and `split()`; this library did not, so a `STRESS` row separated by
`0x1C` was read by PyVista and dropped here — losing the whole array. That
needed no non-ASCII byte at all, in a format that has none. It was filed under
this heading and invisible because every fixture in the corpus is ASCII.

Python is also asymmetric in a way worth copying exactly: `'a\x1cb'.split()`
gives two fields but `int('\x1c42')` raises. So there are two whitespace sets
here, `is_python_space` and `is_c_space`, and the numeric parsers use the
narrower one.

**Outside ASCII there is no fixed behaviour to match.** `ref_frd` opens the
file with `Path.open(errors='replace')` and no encoding, so the bytes are
decoded with whatever `locale.getpreferredencoding(False)` returns. U+2003
encoded as UTF-8 is one whitespace character on a UTF-8 machine and three
non-space characters on a cp1252 one, and cp1252 is still a Windows default.
The same file yields a different field count on different machines.

So "compatible with PyVista" is not a well-formed goal for these bytes — there
is no single PyVista behaviour, and matching one locale means diverging from
another. This library reads bytes, which makes its answer a function of the
file alone. That is the property being chosen, and it is the only one of the
available options that is the same everywhere.

*Pinned by* `TextTest.TheInformationSeparatorsAreWhitespaceToStripAndSplit`,
`TextTest.TheInformationSeparatorsAreNotWhitespaceToIntAndFloat`,
`TextTest.TheTwoWhitespaceSetsDifferByExactlyTheSeparators` and
`tests/conformance/test_bytes_and_str.py`, which drives both readers over the
cases the corpus cannot hold.

### Field widths are counted in bytes, not characters

The element-record format test (`> 50` characters) and the fixed-width field
split both count bytes here and characters in PyVista. The two agree for any
ASCII content, which is every element record CalculiX writes — element records
contain nothing but digits and spaces. A multi-byte character inside one would
make the readers choose different widths.

This is the same locale-dependent family as the entry above: a multi-byte
character's *character* count is a property of the decoding, so there is no
single reference width to agree with either.

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
