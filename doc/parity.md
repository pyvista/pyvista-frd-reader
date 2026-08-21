# The external parity sweep

The conformance suite grades this reader against PyVista's over
`tests/fixtures/`, which is a corpus this project wrote. That is the right
instrument for pinning behaviour we already understand and the wrong one for
finding behaviour nobody has thought of: an authored corpus contains the cases
its author knew to author. A green sweep over it says the two readers agree on
the files we wrote.

This document records what happened when the same comparison was pointed at
**1,766 FRD files this project did not write**, and what it found — including
the places where the instrument was wrong rather than the reader.

## Result

| Corpus | Files | Agree, bit for bit | Read only here | Declined by both | Divergences |
| --- | ---: | ---: | ---: | ---: | ---: |
| CalculiX regression suite | 839 | 832 | 1 | 6 | **0** |
| GitHub code search, `extension:frd` | 927 | 239 | 0 | 688 | **0** |
| **Total** | **1,766** | **1,071** | **1** | **694** | **0** |

No file in either corpus produced a different answer from PyVista's reader.

**"Declined by both" needs care, and an earlier version of this document did
not give it any.** It means both readers refused the file in the same way —
same exception type, same message — which is a real result only when the file
genuinely has no mesh in it. It is not a licence to file every refusal as a
success, and reading it that way is how a missing half of the format went
unnoticed here for a while. The 694 break down as:

- **688 files that are not CalculiX FRD at all.** The extension is shared with
  loudspeaker measurements and at least one fractal renderer. Declining these
  is the correct answer and the interesting half of the GitHub corpus.
- **6 files CalculiX wrote with no mesh in them.** Checked individually rather
  than counted: `spring6.frd` declares `0` nodes and `0` elements in its own
  headers, two `.rfn.frd` files are five bytes containing only the ` 9999`
  trailer, and three more are 86-byte headers with no blocks. A file that
  states it has no nodes has no mesh, and both readers say so.

**"Read only here" is the column that used to be missing.** One file —
`beampdouble.frd.ref`, which CalculiX publishes and reads back as a submodel
input — is binary FRD. PyVista's reader parses FRD as text, so it answers `No
nodes found in FRD file`; this library reads its 261 points and 32 cells. See
`doc/binary.md` for how that decode is graded, since the oracle cannot grade
it.

## The corpora, and why these two

### CalculiX's own regression suite

The strongest available evidence, because these files were written by the
program that defines the format. There is no independent FRD specification;
FRD is what `ccx` writes and `cgx` reads.

`tools/fetch_corpus.py --source calculix` builds it, from three sources rather
than the one an earlier version of this document described:

- **216 FRD files the suite ships.** Mostly `*.frd.ref`, the reference output
  each deck is graded against. They cost nothing to collect and were being
  ignored entirely, which is how the only binary FRD CalculiX publishes stayed
  invisible to every sweep.
- **595 written by running the decks**, `ccx -i <job>` in the directory the
  deck lives in.
- **28 written by running the decks under a name that is not the deck's.**
  `<job>.net.frd` for a network analysis, `<job>.rfn.frd` for a refined mesh.
  Collecting only `<job>.frd` discarded these, and they are not a random
  sample: the extra outputs come from different code paths in `frd.c` than the
  main one.

Pinned to `http://www.dhondt.de/ccx_2.22.test.tar.bz2` and solved with
CalculiX 2.22, so the suite and the solver are the same release. **839 FRD
files, 125 MB.** Of 610 decks, 599 wrote at least one FRD and 11 wrote none
— no FRD requested, or a solver error.

The per-deck bound is 900 s and nothing reached it. The previous run used
180 s, and 23 decks that hit it left **truncated** FRD files behind that were
collected as though they were complete CalculiX output. A partial file is
indistinguishable from a small one; the bound is now generous enough that
reaching it means the deck really is long-running, and a deck that reaches it
has its output deleted rather than kept.

### GitHub

Worth having for a reason that has nothing to do with volume. **The `.frd`
extension is overloaded.** Of 927 files retrieved, only 318 are CalculiX FRD.
The other 609 are loudspeaker frequency-response measurements from REW and
OmniMic, satellite laser-ranging data, XML documents, and at least one fractal
renderer's project files.

That population cannot be authored. A fixture written here to look like "a file
that is not FRD" would only ever contain what we already expected a non-FRD
file to look like. All 609 are declined by both readers identically, which is
the behaviour that matters: a reader that met one of these and invented a mesh
would be worse than one that crashed.

Retrieved with `gh api search/code`, which caps at 1,000 results; 927 unique
blobs remained after de-duplication by SHA. Provenance for every file — the
repository, the path, the blob SHA — is recorded in `provenance.tsv` by
`tools/fetch_corpus.py`.

### Why neither corpus is in this repository

CalculiX is GPL, and the GitHub files carry whatever licence each repository
does. Vendoring either into an MIT project would be a licensing problem and a
several-hundred-megabyte one. `tools/fetch_corpus.py` rebuilds them instead, so
the corpus is reproducible without this repository having to carry it.

## The corpus that did come into the repository

The sweep corpora stay out of tree for licensing reasons, but the reason to
want them applies to the repository's own fixtures too. Every file under
`tests/fixtures/elements/` was written by hand, which means it encodes what
this project *believes* CalculiX writes — and a hand-written fixture graded
against a hand-written reader can agree perfectly while both are wrong about
the bytes a real solver emits.

`tools/generate_fixtures.py` closes that loop without touching anyone's
licence: the input decks are **ours**, written here and MIT like the rest of
the repository, and the FRD files are what `ccx` produced from them. Twelve
decks, one element of each supported type, solved with CalculiX 2.22 — 160 KB
in `tests/fixtures/generated/`, discovered by the same `rglob` as everything
else, so the entire conformance suite now runs over genuine solver output as
well. All twelve agree bit for bit. The corpus went from 33 files to 45 and the
suite from 298 tests to 358.

`tests/test_fixture_bytes.py` requires each of them to carry CalculiX's own
`1UPGM`/`1UVERSION` banner, because nothing else in the suite would notice if
one were quietly replaced by an authored file — after which the directory would
still be *named* `generated`.

### The pyramids have no official fixture, and cannot get one

Worth stating rather than leaving as an asymmetry someone trips over.

CalculiX 2.22 answers `*ERROR reading *ELEMENT: C3D5 is an unknown element
type` and stops. That is not a quirk of one deck: none of the 610 official
decks mentions `C3D5` or `C3D13`, and a census of the 839 files finds **11
distinct cell types across 188,951 cells and no pyramid among them**:

| cell type | cells | files | | cell type | cells | files |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| `HEXAHEDRON` | 93,512 | 228 | | `LINE` | 289 | 132 |
| `QUADRATIC_HEXAHEDRON` | 64,772 | 429 | | `QUADRATIC_TRIANGLE` | 64 | 2 |
| `QUADRATIC_TETRA` | 18,413 | 23 | | `WEDGE` | 42 | 4 |
| `TRIANGLE` | 7,991 | 21 | | `QUAD` | 8 | 2 |
| `QUADRATIC_QUAD` | 1,479 | 38 | | | | |
| `QUADRATIC_WEDGE` | 1,292 | 3 | | | | |
| `QUADRATIC_EDGE` | 1,089 | 122 | | | | |

Linear `TETRA` is absent from this corpus, which the previous run did contain.
That is a difference between the two corpora rather than a change in the
reader, and it is the sort of thing a census restated from memory would have
carried over silently.

So the PY5/PY13 support added by [pyvista#8936] is the one corner of the
element table that **no file in either corpus corroborates**. Whatever writes
those records, it is not this solver, and `tests/fixtures/elements/PY5.frd` and
`PY13.frd` — both hand-written — remain the only evidence there is. The sweep
cannot strengthen that claim, and this document should not be read as though
it had.

[pyvista#8936]: https://github.com/pyvista/pyvista/pull/8936

## Method

`tools/sweep_external.py` runs both readers over each file and compares
everything: point coordinates, node ids, cell types, offsets, connectivity,
step times, array names *and their order*, shapes, component counts, and every
value of every array. Two standards, the same two the conformance suite uses:

- **bit for bit** for everything read off the file and for the von Mises
  arrays;
- **a stated band** for the principal values, which come from an eigensolver —
  32 ulp of the *tensor's* magnitude, not the eigenvalue's. See
  `doc/divergences.md` for why that distinction is the whole point.

A file gets one of six verdicts. `agree` and `differ` are the obvious two.
`both-decline` means both readers refused it in the same words. `both-refuse`
means both refused it in *different* words — the ragged-block case, where the
difference in wording is itself documented in `doc/divergences.md`; neither
reader stores a short row, which is the part that matters. `beyond-oracle`
means this library read the file and the oracle could not, which is not an
agreement and must never be counted as one: it is the verdict for binary FRD,
and the file it applies to has to be graded some other way. `error` is
reserved for a fault in the sweep, so that a defect in the instrument can
never be reported as a property of the reader.

The sweep exits non-zero on `differ` and on `error`. It exits zero on the
agreements and on `beyond-oracle`, because a corpus that legitimately contains
files neither reader should accept — which the GitHub one very much does —
would otherwise make a clean run indistinguishable from a broken one.

## What the sweep found

Four things. Two were defects in the sweep itself, one was a real gap in the
test suite, and one was a latent defect in the repository that had nothing to
do with FRD.

### 1. The comparison reported three divergences that were not

`channel8.net.frd`, `channel9.net.frd` and `backstepturb.frd` came back as
*differ*: `points: 24 of 936 values differ`.

They do not. CalculiX writes a literal `NaN` into the coordinate records of
network nodes — nodes in a fluid deck that have no geometric position:

```
 -1        61         NaN         NaN         NaN
```

Both readers produce NaN, in the same places, with the same bits. The
comparison was `numpy.array_equal`, and `NaN != NaN`. A false red is not a
harmless one in a sweep of this size — it is the result that teaches you to
skim the output.

### 2. Thirty-four files were reported as errors when both readers agreed

`ValueError: No nodes found in FRD file`. CalculiX writes node-free FRD files
for spring-only and substructure decks, and PyVista refuses to build a grid
from one rather than returning an empty mesh. This library refuses in exactly
the same way, with the same message — but the sweep called the oracle's
grid-building step outside its comparison logic and let the exception classify
the file as a harness error.

Both of these were the instrument, not the subject. They are recorded here
because the first version of this document would otherwise have reported "3
divergences and 34 errors" from a reader that had none.

### 3. The suite could not have detected a dropped sign on zero

Fixing (1) required deciding what "equal" means for a parser, and `==` is
wrong in *both* directions:

| | `numpy.array_equal` | bit patterns |
| --- | --- | --- |
| NaN vs the same NaN | `False` — false red | `True` |
| `-0.0` vs `+0.0` | `True` — **false green** | `False` |

The second is the one that matters. `-0.0 == 0.0` is true in IEEE 754, so a
reader that lost the sign of a negative zero would pass a value comparison
unnoticed — and `numpy.testing.assert_array_equal`, which the conformance
suite used, has the same blind spot.

**21 files in CalculiX's regression suite contain `-0.00000E+00`. This
repository's fixtures contained none.** So the gap was doubled: an assertion
that could not see the bug, over a corpus that could not produce it.

Both readers do handle it correctly — `scheibe2f2f.frd` has 65 negative zeros
in `DISP` and they agree bit for bit. What was missing was the ability to
notice if they ever stopped. Closed by:

- `tests/fixtures/signed_zero.frd` and `tests/fixtures/nan_coords.frd`, written
  here but modelled on what the sweep found in real files;
- `assert_bitwise_equal` in the conformance suite, replacing
  `assert_array_equal` for every array claimed to be bit-exact;
- `tests/test_fixture_bytes.py`, so a formatter quietly rewriting
  `-0.00000E+00` cannot remove the coverage while leaving the suite green.

Verified by control: against a sign-stripped array, `assert_array_equal`
passes and `assert_bitwise_equal` fails, naming the reason. Matching NaNs still
pass, so it does not cry wolf.

### 4. Git could have destroyed two fixtures, and a test would have gone green

Not an FRD finding, but found while setting the corpus up. The repository had
no `.gitattributes`, so git classified fixtures by guesswork:
`mock_crlf.frd` was stored `i/crlf` and treated as **text**. A clone with
`core.autocrlf=true` — what the Git for Windows installer sets by default — or
`input` normalises CRLF to LF on the way into the index, turning that fixture
into a byte-for-byte copy of `mock.frd`.

What makes it worth a document entry is what the suite would have done next.
`test_newline_variants_read_identically` reads all three encodings and requires
the same arrays from each. Once they are all LF they are identical, and the
test passes **because** its subject was destroyed. The gate reports green at
the moment it stops testing anything.

Fixed with `*.frd binary` in `.gitattributes`, and `tests/test_fixture_bytes.py`
as the detector for the case where that line is ever removed. Confirmed by
control: normalising `mock_crlf.frd` fails the new test while
`test_newline_variants_read_identically` still passes.

## Performance

`tools/bench_corpus.py`, over the 839-file CalculiX corpus, 125 MB, best of
three per file.

Both readers are driven to the same end state — every array of every step
materialised — because otherwise the comparison is unfair in this library's
favour: opening a file here indexes the blocks and defers a step's values until
they are asked for, while PyVista's reader parses everything during `parse()`.
Timing "open" against "parse" would be measuring work not yet done.

| | PyVista | this library |
| --- | ---: | ---: |
| total, 839 files, 125 MB | 8.72 s | 1.17 s |

**Aggregate 7.42x.** The per-file distribution matters more than the aggregate,
which is dominated by the largest files:

| p0 | p10 | p25 | p50 | p75 | p90 | p100 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.83x | 1.50x | 3.26x | 5.49x | 7.26x | 9.60x | 37.67x |

- **Slower on 2 of 839 files.** Both are tiny files where the whole read is
  scheduler noise, not a regression.
- Files over 1 MB (24 of them): median **5.25x**.
- Files under 64 KB (658 of them): median **3.51x**.

The README's two-file table is a quick check on a machine; this is the number
to quote.

## Reproducing it

Everything below is a command in this repository. The previous version of this
section had a `# ... solve each .inp ...` in the middle of it, which is the
part that was hardest to get right and the part that was not written down.

```bash
# CalculiX corpus: fetch the pinned suite, run every deck, collect every FRD.
# Needs ccx 2.22. Takes a while; nothing else should touch the tree meanwhile.
python tools/fetch_corpus.py --source calculix --ccx ccx

# GitHub corpus: needs an authenticated `gh`.
python tools/fetch_corpus.py --source github

# Parity against PyVista, and the writer's byte-for-byte gate.
python tools/sweep_external.py external-corpus/calculix --json sweep.json
python tools/sweep_external.py external-corpus/github --json gh-sweep.json
python tools/sweep_rewrite.py  external-corpus --json rewrite.json

# Timings
python tools/bench_corpus.py external-corpus/calculix --json bench.json
```

## What this does not establish

Worth stating plainly, because a number like 1,766 invites more weight than it
can carry.

- **It is agreement, not correctness.** The oracle is PyVista's reader. Where
  both readers are wrong about the format in the same way, this sweep is
  silent by construction, and no amount of corpus fixes that. The hand-computed
  values in the gtest tier, the fixtures taken from CalculiX itself, and the
  byte-for-byte writer gate in `doc/writing.md` are what carry that half.
- **The oracle cannot see binary FRD at all.** For the one binary file in the
  corpus the sweep has no opinion, and for the twelve binary fixtures this
  project generates it has none either. Those are graded against CalculiX's
  own ASCII encoding of the same computation instead.
- **The two corpora are not independent of each other.** Both consist mostly of
  files written by `ccx`, so a CalculiX quirk that both readers mishandle is
  present in both.
- **11 decks wrote no FRD**, so whatever they would have exercised is not here.
- **The GitHub search caps at 1,000 results.** It is a sample of what GitHub
  will admit to having, not a census of FRD files in the world.
- **It is one run on one machine.** The timings especially are a property of
  this hardware; the ratios travel better than the absolutes.
- **Two element types are untouched by it.** PY5 and PY13 appear nowhere in
  either corpus, for the reason above. Every other supported type is covered
  by both hand-written and solver-written fixtures. Linear `TETRA` is covered
  by fixtures but, in this run of the corpus, by no external file.
- **A green sweep says nothing about the files that are not in it.** The
  corpus grew by 40% between two runs of the same tool, and the growth was not
  random: it was the shipped reference outputs, the differently-named deck
  outputs, and the files a 180-second timeout had been truncating. Each of
  those was invisible, and each was invisible in a way that made the previous
  result look complete.
