# Writing FRD

`pyvista_frd.write` writes a PyVista mesh as long ASCII, binary `float32`, or
binary `float64` FRD. `pyvista_frd.convert` changes an existing document's
encoding without building a mesh. With no target encoding, conversion
preserves all four FRD encodings, including short ASCII.

```python
import pyvista_frd

mesh = pyvista_frd.read("result.frd")
pyvista_frd.write("copy.frd", mesh)
pyvista_frd.write("result_binary.frd", mesh, binary=True)

pyvista_frd.convert("result_binary.frd", "result_ascii.frd", binary=False)
```

Files created by this package identify `pyvista-frd-reader` as the writer.
They are not labeled as CalculiX output.

## Byte round trips

A writer and reader from the same implementation can share a defect and still
pass a write-then-read test. This project therefore checks original bytes from
external files in addition to semantic round trips.

`tools/sweep_rewrite.py` reads each document, writes it in its original
encoding, and compares every byte:

| Corpus | Files with FRD blocks | Byte-identical | Different |
| --- | ---: | ---: | ---: |
| CalculiX regression suite | 834 | 834 | 0 |
| GitHub code search, `extension:frd` | 277 | 277 | 0 |
| **Total** | **1,111** | **1,111** | **0** |

Another 655 files contain no FRD node, element, or result blocks. The converter
copies these files unchanged and reports them separately. The sweep fails if it
finds no file with FRD blocks, so an empty or irrelevant corpus cannot pass.

`tests/test_writer.py` applies the same byte check to the 24 CalculiX-generated
fixtures. Handwritten fixtures use non-CalculiX number formatting, so their
tests compare the resulting mesh and values by bit pattern instead.

## Cases found by the external corpus

### CalculiX GraphiX record layout

Two `cgx_2.x/examples/result.frd` files use a different ASCII layout:

```text
 -1    1 0.86430E-07-0.16898E+02 0.55880E+02      cgx example
 -1         1 8.64300E-08-1.68980E-01 5.58800E+01  common ccx layout
```

The GraphiX files use five-column ID fields, 15 element IDs per line, and
Fortran `E12.5` formatting. Their headers do not include a format code. The
writer infers record width and number formatting from the first record of each
block and preserves that layout.

### Binary-to-ASCII rounding

CalculiX casts each value to `float32` before formatting ASCII. This writer
formats the stored `float64` value. The outputs differ only at rounding ties.

Across 12 paired binary and ASCII fixtures, 800 of 825 record lines match.
The other 25 lines differ by one final digit. Those 25 lines contain 0.8% of
the 3,044 values.

This choice preserves the value held by a `float64` binary block or NumPy
array. It means a binary-to-ASCII conversion is not always byte-identical to
ASCII written by CalculiX. Same-encoding round trips are unaffected. See
[Differences from PyVista](divergences.md) for the exact case.

### Adjacent element IDs

Five-column fields can contain adjacent five-digit IDs:

```text
 -21000110002100031000410005100061000710008
```

Whitespace splitting treats this as one integer and loses the connectivity.
The writer parses these records by fixed width. The case is pinned by
`test_glued_face_ids_survive_the_writer`.

## Cross-encoding check with CalculiX

Same-encoding byte comparison cannot detect errors that occur only during
conversion. Binary blocks, for example, have no ` -3` terminator; ASCII blocks
require one.

The CalculiX regression suite includes a submodel that reads
`beampdouble.frd.ref`. The following inputs were tested:

| Input | CalculiX result |
| --- | --- |
| Original binary file | Accepted; baseline output |
| Binary file rewritten by this package | Accepted; output matches baseline byte for byte |
| Binary converted to ASCII without a terminator | Rejected |
| Binary converted to ASCII after the terminator fix | Accepted; output matches CalculiX's ASCII reference |

The final comparison excludes four header lines containing dates and CalculiX
versions. Ten coordinate values also differ in their final digit unless this
writer's values are first narrowed to `float32`, as described above.

## Coverage limits

- A newly constructed mesh has no original FRD document for byte comparison.
  Its records use the same emitter, while its headers are covered by C++ writer
  tests and write-then-read tests.
- Format 0 (short ASCII) and format 2 (binary `float32`) appear in none of the
  1,766 external files. They are covered by project write-and-read tests.
- External binary coverage contains one published format-3 file. Another 12
  format-3 files are generated from project decks with CalculiX.
- Two external files contain `NaN`. The writer uses a fixed spelling instead
  of platform `printf` output.
- Byte identity proves preservation of the document, not the meaning of fields
  ignored by both CalculiX and this implementation.

The observed format-code counts are:

| Format code | Blocks | Files |
| --- | ---: | ---: |
| 0, short ASCII | 0 | 0 |
| 1, long ASCII | 2,138 | 1,070 |
| 2, binary `float32` | 0 | 0 |
| 3, binary `float64` | 1 | 1 |
| No code | 4 | 2 |

## Mutation checks

`tools/mutate.py` applies 10 writer defects and verifies that the named test
fails for each one:

| Mutant | Expected check |
| --- | --- |
| `writer-value-precision` | Byte round trip |
| `writer-narrows-through-float32` | Binary-to-ASCII comparison with CalculiX |
| `writer-faces-wrap-at-nine` | Byte round trip |
| `writer-values-wrap-at-five` | Byte round trip |
| `writer-face-width-assumed` | Byte round trip |
| `writer-faces-split-on-whitespace` | Adjacent-ID test |
| `writer-converts-without-a-terminator` | Terminator test |
| `writer-truncates-array-names` | Write-then-read test |
| `writer-reuses-the-readers-permutation` | C++ `WriteTest` |
| `writer-hoists-unparsed-lines` | Stray-line position test |

All 10 are rejected by their expected checks. The stray-line test was added
after that mutant initially survived, and it covers both node and result
blocks.
