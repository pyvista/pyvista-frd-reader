# Binary FRD

FRD block headers end with a format code:

| Code | Encoding |
| ---: | --- |
| 0 | ASCII with five-column ID fields |
| 1 | ASCII with ten-column ID fields |
| 2 | Binary with `float32` values |
| 3 | Binary with `float64` values |

CalculiX writes binary FRD for `*REFINE MESH` and `DOUBLE` output cards.
PyVista's built-in reader parses FRD as text and does not support formats 2 or
3. Depending on the file, it returns an empty mesh or raises an error.

## Record layout

Headers remain ASCII. Only the records are binary.

```text
nodes      int32 ID, then three coordinates       16 bytes (format 2) or 28 (format 3)
elements   int32 number, type, group, material, then n_points x int32
results    int32 node ID, then one value per stored component
```

Binary blocks have no ` -3` terminator. The parser uses the record count from
the block header to locate the next header.

Result width comes from the stored component definitions. A `-5` component
line may join the `iexist` flag and component name, for example `1ALL`.
Computed components such as displacement magnitude are not stored in the
binary records and therefore do not contribute to their width.

After reading a binary payload, the parser checks that it reached another
ASCII header or the end of the file. It reports truncated records and invalid
landing offsets as format errors.

## Verification

PyVista cannot serve as the reference for binary FRD. Binary parsing is checked
against paired files and one published CalculiX file.

### Paired CalculiX output

`tools/generate_fixtures.py` solves 12 element decks twice. One deck requests
normal ASCII output and the other adds CalculiX's `DOUBLE` keyword. The paired
files contain the same calculation in formats 1 and 3.

ASCII output has six significant digits and CalculiX casts values to
`float32` before printing them. Comparisons therefore use rounding bounds
instead of bit equality.

For a six-component tensor with per-component relative rounding `u`, a
perturbation satisfies `||ds||_F <= u||s||_F`. The derived-value bounds are:

| Quantity | Bound | Measured maximum |
| --- | ---: | ---: |
| Principal values | `1.000 u` | `4.231e-06` |
| von Mises | `1.225 u` | `4.036e-06` |

The Frobenius norm treats each off-diagonal tensor component twice. Using the
norm of the stored six-vector would understate the reference magnitude.

### Published binary file

CalculiX 2.22 includes one binary result file,
`beampdouble.frd.ref`. The reader returns 261 points and 32 cells. Converting
it to ASCII reproduces `beamp.frd.ref` except for 14 of 644 lines:

- four header lines contain different dates and CalculiX versions;
- ten coordinates differ in the final digit because CalculiX formats ASCII
  values after casting them to `float32`.

All 1,566 values match after the same `float32` cast. CalculiX also accepts the
converted file as submodel input and produces the same solver result. See
[Writing FRD](writing.md) for that check.

## Header counts

Binary blocks must use their declared record count because they have no
terminator. Counts are reliable for known binary files, but some ASCII files
show why this remains a limitation:

| ASCII block | Header matches records | Header differs |
| --- | ---: | ---: |
| `2C`, nodes | 784 | 0 |
| `3C`, elements | 779 | 5 |

Another 98 ASCII headers contain no count. The five element-count mismatches
occur in three files where CalculiX expands beam or shell elements for output:

- `concretebeam.frd`: declares 10 elements and stores 110;
- `shell3.frd`: declares 4 and stores 8;
- `shell4.frd`: declares 242 and stores 968.

The ASCII parser reads records through the terminator and ignores the declared
count. A binary file with the same incorrect count could not be recovered
reliably. No such binary file is present in the available corpora.

## Coverage limits

- Format 2, binary `float32`, appears in none of the 1,766 external files.
  It is covered only by write-and-read tests within this project.
- Binary element blocks appear only in generated project fixtures.
- External binary coverage consists of 12 small linear-elastic models and one
  published CalculiX file.
