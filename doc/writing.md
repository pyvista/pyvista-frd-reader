# Writing FRD

This library writes the format as well as reading it, in all four encodings,
and converts between them. This document is about how that is checked, because
a writer is unusually easy to check badly.

## The trap

Write a file, read it back with your own reader, find the mesh you started
with. It feels like a test. It is satisfied exactly as well by a matched pair
of defects as by a correct pair: a writer that puts the node id in the wrong
columns and a reader that looks for it there agree with each other perfectly,
and the round trip is green.

So the round trip is not the gate here. The gate is **CalculiX's bytes**.

## The gate

`tools/sweep_rewrite.py` reads a document and emits it again, and requires the
output to be the input byte for byte. Every field width, every wrapping rule
and every way of spelling a number has to be right for that to hold, and none
of them is being compared against this project's opinion of the format.

| corpus | files with FRD blocks | byte-identical | differing |
| --- | ---: | ---: | ---: |
| CalculiX regression suite, solved | 834 | 834 | **0** |
| GitHub code search, `extension:frd` | 277 | 277 | **0** |
| **total** | **1,111** | **1,111** | **0** |

A further 655 files in those corpora contain no node, element or result block
-- the `.frd` extension is shared with loudspeaker measurements and at least
one fractal renderer -- and they round-trip by being copied. They are counted
separately, and the sweep exits non-zero if *no* file with blocks round-trips,
so a run that graded nothing cannot report success.

In tree, `tests/test_writer.py` runs the same gate over the 24 fixtures under
`tests/fixtures/generated/`, which are CalculiX output. The hand-written
fixtures are deliberately not in CalculiX's spelling -- they carry `0.0` where
a solver writes `0.00000E+00` -- so they get a different claim: the document
may be respelled, but it must not come back describing a different mesh or
different numbers, compared by bit pattern.

## What the gate found

Three things, none of which could have been authored as a fixture.

### A second dialect of the format

Two files in the GitHub corpus turned out to be `cgx_2.x/examples/result.frd`,
shipped with CalculiX GraphiX itself, and they are not written the way `ccx`
writes:

```
 -1    1 0.86430E-07-0.16898E+02 0.55880E+02      cgx's example file
 -1         1 8.64300E-08-1.68980E-01 5.58800E+01  everything else
```

Five-column id fields rather than ten, fifteen element ids to a line rather
than ten, and Fortran's `E12.5` edit descriptor -- mantissa in [0.1, 1), five
significant digits -- where `ccx` uses C's `%12.5E` with six. The block header
states no format code at all, so there is nothing to read the width off.

The writer now measures both from the first record of each block and
reproduces what it read. Imposing one dialect on a file written in the other
would be reformatting somebody's data on the way through.

### CalculiX writes ASCII through single precision; this writer does not

`frd.c` casts every value to `float` before printing it, so its ASCII output is
the six-digit rounding of a `float32`. This writer renders the `double` it
holds. The two agree except at a rounding tie: `6.464285098e-04` prints as
`6.46429E-04` from the double and `6.46428E-04` from the float.

Converting the twelve binary fixtures to ASCII and comparing against the ASCII
CalculiX wrote from the same run of the same deck: **800 of 825 record lines
match, and 25 differ by one in the last digit.** Every one of the 25 is a tie,
and matching all 825 needs only a `static_cast<float>` before the `snprintf`.

That cast is deliberately not there. A value this library writes is the nearest
six-digit decimal to the number it is holding, which is the stronger of the two
guarantees and the only one that stays true when the source was never a float
in the first place -- a mesh handed to the builder from NumPy, or a `float64`
binary block. Reproducing CalculiX's tie-breaking would mean discarding
precision on every value in order to agree about the 25 that differ -- 3% of
the record lines, and 0.8% of the 3,044 values on them.

The consequence is stated where it can be acted on: this is the one respect in
which a *converted* file is not byte-identical to what CalculiX would have
written, and `doc/divergences.md` carries it. A file read and written back in
its own format is unaffected -- there is no cast on that path, in either
direction, and the byte gate below covers it over 1,111 files.

Both claims are pinned exactly rather than by a band.
`test_converted_ascii_is_the_double_rounded_not_the_float` requires our text to
be the rounding of the stored double *and* CalculiX's to be the rounding of its
float, so a decode reading the wrong bytes cannot satisfy either.
`test_the_float_cast_explains_a_few_percent_and_no_more` bounds the population
from both sides: nothing differing would mean the cast is never exercised, and
a large fraction differing would mean something other than a tie is at work.

### Glued element ids

Five-column fields holding five-digit ids leave nothing between them:

```
 -21000110002100031000410005100061000710008
```

That is eight ids. Read as one token it overflows, is dropped, and the element
loses its connectivity in silence. The reader already chunked these
fixed-width; the writer's own parser did not, and the repository's
short-format fixture could not have caught it -- `glued_ids_short.frd` has a
malformed element header, so its element block is passed through verbatim and
never reaches the face-parsing path it is named for.
`test_glued_face_ids_survive_the_writer` builds the case the fixture missed.

## What the byte gate cannot see

It compares a file with itself, so anything that is only wrong when the
encoding *changes* is invisible to it. That is not a hypothetical either.

Binary blocks carry no ` -3` terminator -- CalculiX writes it only in ASCII
mode -- so converting binary to ASCII has to invent one. The first version did
not, and every same-format round trip still passed: a binary block with no
terminator still has none afterwards.

What found it was CalculiX. Its regression suite reads an FRD file back in as
a submodel boundary condition, so a converted file can be handed to the solver:

```
*SUBMODEL,TYPE=NODE,INPUT=beampdouble.frd.ref
```

| what CalculiX was given | solver | its `.dat` output |
| --- | --- | --- |
| its own binary file | accepted | the baseline |
| our re-emission of it | accepted | **byte-identical to the baseline** |
| our binary → ASCII conversion, before the fix | **rejected** | — |
| our binary → ASCII conversion, after the fix | accepted | identical to CalculiX's own ASCII file |

The rejection read `*ERROR in getglobalresults: there are either no nodes or
no elements ... in the master frd-file`. CalculiX's reader ends a block on the
terminator, so without one the whole rest of the file is still the node block.

The last row is the strongest single result here: our conversion of
`beampdouble.frd.ref` is identical to `beamp.frd.ref`, the ASCII file CalculiX
wrote of the same model, apart from the four header lines recording each run's
date and version -- and the solver produces the same `.dat` from either.

Reproducing it needs `ccx` and the test suite, so it is here rather than in the
suite.

## What is *not* covered by any of it

Worth stating plainly.

- **The constructed path has no original to be compared against.** A mesh
  handed in through the builder produces header lines that no CalculiX file
  can be diffed against, because CalculiX never wrote this document. The
  records go through the same emitter the byte gate covers; the headers are
  backed by the reader accepting them, by `WriteTest` in the gtest tier, and
  by the solver experiment above for the rewriting path only.
- **The short ASCII format is barely represented.** Two files in 1,766 use it.
  Every other file in both corpora is long ASCII, apart from one binary.
- **Binary is thinner still.** CalculiX publishes exactly one binary FRD --
  `beampdouble.frd.ref` -- plus the twelve this project generates by adding
  `DOUBLE` to a `*NODE FILE` card. Format 2, binary float32, appears in
  neither: it is implemented from the format's documented meaning and is
  checked only by this library reading back what it wrote.
- **`NaN` is covered by two files.** CalculiX spells it `NaN`; glibc's printf
  spells it `NAN` and Windows spells it `nan`, so the spelling is fixed in the
  emitter rather than left to the C library. Two files in the corpus would
  notice if that changed.
- **It is agreement about bytes, not about meaning.** A field this library and
  CalculiX both consider decorative would round-trip perfectly while being
  misunderstood by both.

## Mutants

A gate at 100% on its first run is indistinguishable from one that copies its
input. `tools/mutate.py` carries ten planted writer defects; each is a mistake
a careful implementation could actually make, and each names the gate that is
supposed to catch it, so being killed by the *wrong* gate is visible as such.

| mutant | the gate that catches it |
| --- | --- |
| `writer-value-precision` — `%12.5E` becomes `%12.6E` | byte-for-byte round trip |
| `writer-narrows-through-float32` — cast before formatting | binary → ASCII vs CalculiX |
| `writer-faces-wrap-at-nine` | byte-for-byte round trip |
| `writer-values-wrap-at-five` | byte-for-byte round trip |
| `writer-face-width-assumed` — inherit the parse heuristic | byte-for-byte round trip |
| `writer-faces-split-on-whitespace` | the glued-ids test |
| `writer-converts-without-a-terminator` | the terminator test |
| `writer-truncates-array-names` | write-then-read |
| `writer-reuses-the-readers-permutation` | `WriteTest`, in the gtest tier |
| `writer-hoists-unparsed-lines` | the stray-line test |

All ten are killed by the gate named against them. The sweep also reports a
count of failing tests per mutant; those counts include
`test_mutation_harness.py`, which asserts each mutant's anchor is still in the
source and therefore fails for *every* applied mutant. It is not evidence
about the writer.

Three of them are worth recording for what they cost.

**Restoring a file's timestamp between mutants made them leak into each
other.** The suite refuses to grade a native library older than its sources, so
the harness was changed to put each source's original mtime back after
restoring its contents — which is also exactly what tells the build system
there is nothing to recompile. The next mutant's build reused the previous
one's object file. The symptom was a mutant reported as killed by a test that
does not test it, and inflated counts: `writer-truncates-array-names` read as
29 tests and is 4. Timestamps are now restored once, at the end of the sweep,
after the final rebuild.

**A mutant applied to a comment is a no-op.** The first attempt at
`writer-value-precision` left all 60 files green, which read as a hole in the
gate. The replacement had landed on `%12.5E` in a *comment* — the string
appears in the header of `document.cpp` describing the layout — and a no-op
mutant reports exactly as a surviving one does.

**`writer-hoists-unparsed-lines` survived its first real run**, killed only by
the harness's own anchor check while the gate named as its catcher stayed
green. That was correct: nothing tested it. Byte identity is claimed only for
solver-written files, which contain no unparsed lines, and moving a line the
parser cannot read changes no value the reader returns — so the semantic gate
could not see it either. `test_an_unreadable_line_keeps_its_place_in_the_block`
was written because the mutant said so, and it covers a result block as well as
a node block, because the two are separate branches of the parser and the first
version of the test only reached one of them.

## Using it

```python
import pyvista_frd

mesh = pyvista_frd.read('result.frd')
pyvista_frd.write('copy.frd', mesh)                 # ASCII, six digits
pyvista_frd.write('small.frd', mesh, binary=True)   # a third of the size, exact

# Convert without going through a mesh: no precision is lost either way that
# the target format can hold.
pyvista_frd.convert('binary.frd', 'ascii.frd', binary=False)
```

Files this library writes identify it as their writer. They are not labelled
as CalculiX output -- several checks in this repository, and possibly in
yours, use that banner to tell solver output from anything else, and a writer
that stamped somebody else's name on its work would make every one of them a
lie.
