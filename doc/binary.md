# Binary FRD

Half of the format, and this library did not implement it.

## What was missing

Every FRD block header ends with a format code, and there are four:

| code | encoding |
| ---: | --- |
| 0 | ASCII, five-column id fields |
| 1 | ASCII, ten-column id fields |
| 2 | binary, `float32` values |
| 3 | binary, `float64` values |

Codes 0 and 1 were implemented. Codes 2 and 3 were not, and the failure was
the quiet kind: the header's records were not text, so no line matched the
record marker, so the block contributed nothing and the parse finished
normally. A file whose header declared 2195 nodes returned a mesh with none of
them, no error and no diagnostic. `*REFINE MESH` output is binary
unconditionally, so "a lot of `.frd` files come back empty" was not a
collection of edge cases.

## The encoding

Block headers stay ASCII. Only the records are binary.

```
nodes      int32 id, then three coordinates    28 bytes (fmt 3) or 16 (fmt 2)
elements   int32 number, type, group, material, then n_points × int32
results    int32 node id, then one value per stored component
```

Two details decide whether any of it works.

**There is no ` -3` terminator.** CalculiX writes it only in ASCII mode —
`frd.c` guards it with `if(strcmp1(output,"asc")==0)` — so a binary payload
runs straight into the next header line. A block has to be measured from its
header's record count, because there is nothing to scan for; scanning would
find whatever byte sequence the floats happened to spell.

**The record width comes from counting stored components,** and the `-5` lines
make that harder than it looks:

```
 -5  ALL         1    2    0    0    1ALL
```

The `iexist` flag and the component name are printed with nothing between
them, so the field splits as `1ALL` and will not parse as an integer. A
component with that flag is computed by the postprocessor rather than stored —
`ALL` is the magnitude of a displacement — so counting it makes a displacement
block four components wide instead of three, and every record after the first
is decoded from the wrong offset. Nothing about that is loud.

Because the width is computed rather than read, the parser checks where the
payload landed. A binary block is followed by an ASCII header line or by the
end of the file, and every FRD header begins with spaces and then a digit or a
minus. Landing anywhere else means the width was wrong, and the alternative to
noticing is handing back numbers decoded from the middle of other numbers.

Truncation is an error rather than a short read. A file that promises three
nodes and holds one must not come back as a one-node mesh.

## How it is graded

The oracle cannot help here. PyVista's reader parses FRD as text, so a binary
file yields it a silent zero-node parse — comparing against that would be
comparing our answer with nothing at all. The sweep reports these as
`beyond-oracle`, which is not an agreement and is never counted as one.

What they are graded against is better than the oracle.

### Twins

`tools/generate_fixtures.py` writes each of twelve element decks twice, into
`tests/fixtures/generated/` and `tests/fixtures/generated/binary/`. The only
difference between the two decks is CalculiX's documented `DOUBLE` keyword on
the `*NODE FILE` and `*EL FILE` cards. Both are solved in the same run of the
generator, so each binary fixture has an ASCII twin holding the same
computation, written by a program neither half of this project wrote. A reader
decoding binary records at the wrong offset could not accidentally reproduce
the ASCII file's numbers.

ASCII is the lossy side — `%12.5E`, six significant digits — so the comparison
is within that rounding rather than bit-exact.

### The bands are derived, not fitted

Mises and the principal values are not in the file. This library computes them
from the six tensor components, so both twins run identical code and the only
thing that differs is the rounding of the inputs. That makes their tolerance a
propagation bound, which can be derived — and the distinction matters, because
a band chosen to make the run green grades nothing.

Write `u` for the per-component relative rounding and `s` for the tensor. A
perturbation with `|ds_ij| <= u|s_ij|` has `||ds||_F <= u||s||_F`, so:

| quantity | bound | why | measured |
| --- | --- | --- | ---: |
| principal values | `1.000 u` | Weyl: `|dλ| ≤ ‖ds‖₂ ≤ ‖ds‖_F` | 4.231e-06 |
| von Mises | `1.225 u` | `σᵥ = √(3/2)‖dev s‖_F`, gradient norm `√(3/2)` | 4.036e-06 |

Both sit under their own bound and neither bound was moved to put them there.

Measuring a derived quantity against *itself* is the trap here, and it is the
same one `doc/divergences.md` exists to warn about: both of these lose relative
accuracy as they approach zero — an eigenvalue by conditioning, Mises by the
cancellation in the component differences — so that ratio reports the
conditioning of the formula rather than the accuracy of the read. Measured
that way the principal values come out at 5.8e-05 and look ten times worse
than the inputs they were computed from, which is not possible, and is the
tell that the denominator is wrong.

One more trap, worth writing down because it cost a wrong answer: the
Frobenius norm of a tensor stored as six components is **not**
`np.linalg.norm` of the six-vector. The off-diagonals each appear twice in the
matrix. Under-counting them inflates every ratio measured against it, which is
how a Mises figure of 5.07e-06 — apparently over its band — turned out to be
4.04e-06.

### CalculiX's own binary file

The suite publishes exactly one: `beampdouble.frd.ref`, format 3, which a
submodel deck reads back in as a boundary condition. It was invisible to every
sweep this project ran until `tools/fetch_corpus.py` started collecting the
files the suite ships rather than only the ones its decks produce.

This library reads its 261 points and 32 cells. Converting it to ASCII
reproduces `beamp.frd.ref` — CalculiX's own ASCII file of the same model —
apart from the four header lines recording each run's date and version, and
the solver produces the same results from either. `doc/writing.md` has that
experiment.

## The declared count, and why ASCII cannot be held to it

A binary block has to trust the record count in its header: there is no
terminator to scan for, and the count is the only statement of where the
payload ends. So it is worth knowing how good that number is. Measured across
the 839-file CalculiX corpus, counting the ASCII blocks where a count field is
present at all:

| block | header agrees with its records | disagrees |
| --- | ---: | ---: |
| `2C`, nodes | 784 | **0** |
| `3C`, elements | 779 | **5** |

A further 98 headers carry no count field whatsoever.

The five are three files. `concretebeam.frd` declares 10 elements and holds
110; `shell3.frd` declares 4 and holds 8; `shell4.frd` declares 242 and holds
968. The ratios give it away — CalculiX expands shell and beam elements into
solid elements for output, and the header is written with the count from
before the expansion.

This is the reason a declared-versus-parsed mismatch is **not** an error on
the ASCII path, and it is worth being explicit that the decision is evidence
rather than tolerance for its own sake: erroring there would refuse three
files CalculiX wrote and PyVista reads, and reading all 110 elements of
`concretebeam.frd` is the correct answer. The reader takes the records it
finds and ignores the count.

Binary has no such option, which is a real limitation rather than a caveat: a
binary file whose header count is wrong in the way `concretebeam.frd`'s is
would be misread, and this library would have no way to notice beyond the
landing check described above. No such file is known to exist -- CalculiX
writes the expansion cases in ASCII in every example available here -- but
nothing rules one out either.

## What is still thin

- **Format 2, binary `float32`, appears in no file anyone here has found.** It
  is implemented from the format's documented meaning and is checked only by
  this library reading back what it wrote.
- **Binary element blocks** appear only in files this project generates.
- **The whole binary tier rests on twelve decks and one published file.** Every
  one of them is a small mesh from a linear-elastic analysis.
