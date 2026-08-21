# The external parity sweep

The conformance suite grades this reader against PyVista's over
`tests/fixtures/`, which is a corpus this project wrote. That is the right
instrument for pinning behaviour we already understand and the wrong one for
finding behaviour nobody has thought of: an authored corpus contains the cases
its author knew to author. A green sweep over it says the two readers agree on
the files we wrote.

This document records what happened when the same comparison was pointed at
**1,615 FRD files this project did not write**, and what it found — including
the two places where the instrument was wrong rather than the reader.

## Result

| Corpus | Files | Agree, bit for bit | Declined by both | Divergences |
| --- | ---: | ---: | ---: | ---: |
| CalculiX regression suite, solved | 688 | 654 | 34 | **0** |
| GitHub code search, `extension:frd` | 927 | 239 | 688 | **0** |
| **Total** | **1,615** | **893** | **722** | **0** |

No file in either corpus produced a different answer from PyVista's reader.

"Declined by both" is not a shrug. It means both readers refused the file *in
the same way* — same exception type, same message — and it is checked, not
assumed. It covers two quite different populations, described below.

## The corpora, and why these two

### CalculiX's own regression suite

The strongest available evidence, because these files were written by the
program that defines the format. There is no independent FRD specification;
FRD is what `ccx` writes and `cgx` reads.

The suite ships 673 input decks and only four `.frd` files, because it grades
itself on `.dat` output. Running the decks turns it into the largest
authoritative FRD corpus that exists:

- source: `http://www.dhondt.de/ccx_2.23.test.tar.bz2` and
  `ccx_2.23.fluidtest.tar.bz2`
- solved with CalculiX 2.22, `OMP_NUM_THREADS=1`, 180 s per deck
- 673 deck runs: 620 completed, 31 hit the timeout, 22 exited non-zero (the
  2.23 decks against a 2.22 solver; three of those were solver segfaults)
- **688 FRD files, 251 MB**

The 53 decks that did not complete are a coverage gap and are named here
rather than rounded away: whatever those decks would have exercised is not in
this result.

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

A file gets one of five verdicts. `agree` and `differ` are the obvious two.
`both-decline` means both readers refused it in the same words. `both-refuse`
means both refused it in *different* words — the ragged-block case, where the
difference in wording is itself documented in `doc/divergences.md`; neither
reader stores a short row, which is the part that matters. `error` is reserved
for a fault in the sweep, so that a defect in the instrument can never be
reported as a property of the reader. Neither corpus produced a `both-refuse`
or an `error`; the fixture corpus produces one of each, which is what keeps
those branches exercised.

The sweep exits non-zero on `differ`, `error`, or a file only one reader could
read. It exits zero on the two agreements, because a corpus that legitimately
contains files neither reader should accept — which the GitHub one very much
does — would otherwise make a clean run indistinguishable from a broken one.

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

`tools/bench_corpus.py`, over the 688-file CalculiX corpus, 251 MB, best of
three per file.

Both readers are driven to the same end state — every array of every step
materialised — because otherwise the comparison is unfair in this library's
favour: opening a file here indexes the blocks and defers a step's values until
they are asked for, while PyVista's reader parses everything during `parse()`.
Timing "open" against "parse" would be measuring work not yet done.

| | PyVista | this library |
| --- | ---: | ---: |
| total, 688 files, 251 MB | 14.59 s | 2.40 s |

**Aggregate 6.08x.** The per-file distribution matters more than the aggregate,
which is dominated by the largest files:

| p0 | p10 | p25 | p50 | p75 | p90 | p100 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.97x | 1.38x | 1.94x | 3.45x | 6.27x | 8.68x | 39.75x |

- **Slower on 2 of 688 files**, both at 0.97–0.99x. Both are empty files read
  in 0.02 ms by both readers; at that size the ratio is scheduler noise, not a
  regression.
- Files over 1 MB (35 of them): median **5.45x**. `cylfine.frd`, 38.8 MB:
  2252 ms → 366 ms.
- Files under 64 KB (552 of them): median **3.40x**.
- The extreme is `beamnldyeortho.frd` at **39.75x** — 43 KB, 107 ms → 2.7 ms.
  Many time steps in a small file: the oracle parses every value of every step
  eagerly, and that is where the deferred approach pays.

The README's two-file table is a quick check on a machine; this is the number
to quote.

## Reproducing it

```bash
# CalculiX corpus: fetch, solve, sweep. Needs ccx on PATH.
curl -O http://www.dhondt.de/ccx_2.23.test.tar.bz2
tar -xjf ccx_2.23.test.tar.bz2 -C external-corpus/
# ... solve each .inp with `ccx -i <deck>` ...
python tools/sweep_external.py external-corpus/ --json sweep.json

# GitHub corpus: needs an authenticated `gh`.
python tools/fetch_corpus.py --source github --out external-corpus
python tools/sweep_external.py external-corpus/github --json gh-sweep.json

# Timings
python tools/bench_corpus.py external-corpus/ --json bench.json
```

## What this does not establish

Worth stating plainly, because a number like 1,615 invites more weight than it
can carry.

- **It is agreement, not correctness.** The oracle is PyVista's reader. Where
  both readers are wrong about the format in the same way, this sweep is
  silent by construction, and no amount of corpus fixes that. The hand-computed
  values in the gtest tier and the fixtures taken from CalculiX itself are what
  carry that half.
- **The two corpora are not independent of each other.** Both consist mostly of
  files written by `ccx`, so a CalculiX quirk that both readers mishandle is
  present in both.
- **53 decks did not solve**, so their FRD output was never compared.
- **The GitHub search caps at 1,000 results.** It is a sample of what GitHub
  will admit to having, not a census of FRD files in the world.
- **It is one run on one machine.** The timings especially are a property of
  this hardware; the ratios travel better than the absolutes.
