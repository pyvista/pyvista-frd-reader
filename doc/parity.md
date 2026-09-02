# External parity results

The conformance suite compares this reader with PyVista's FRD reader. Project
fixtures pin known cases; an external corpus tests files that were not written
for this implementation.

## Results

| Corpus | Files | Exact agreement | Read only here | Declined by both | Divergences |
| --- | ---: | ---: | ---: | ---: | ---: |
| CalculiX 2.22 regression suite | 839 | 832 | 1 | 6 | 0 |
| GitHub code search, `extension:frd` | 927 | 239 | 0 | 688 | 0 |
| **Total** | **1,766** | **1,071** | **1** | **694** | **0** |

No file produced an undocumented difference from PyVista.

The 694 files declined by both readers are:

- 688 files that are not CalculiX FRD. The `.frd` extension is also used by
  loudspeaker measurements, satellite laser-ranging data, XML documents, and
  a fractal renderer.
- Six CalculiX files with no mesh. One declares zero nodes and elements, two
  contain only the five-byte ` 9999` trailer, and three contain only an
  86-byte header.

The file read only by this package is CalculiX's binary
`beampdouble.frd.ref`, with 261 points and 32 cells. PyVista's reader supports
ASCII FRD only. [Binary FRD](binary.md) describes the separate binary checks.

The writer was run over the same corpus. It reproduced 1,111 files byte for
byte, passed through 655 files with no FRD blocks, and changed none. See
[Writing FRD](writing.md).

## Corpora

### CalculiX regression suite

`tools/fetch_corpus.py --source calculix` builds this corpus from CalculiX
2.22:

- 216 FRD reference files shipped with the suite;
- 595 files produced by running the input decks;
- 28 additional outputs such as `.net.frd` and `.rfn.frd`.

The result is 839 files totaling 125 MB. Of 610 decks, 599 wrote at least one
FRD file and 11 wrote none. Each deck has a 900-second limit. Output from a
timed-out deck is deleted to avoid grading a truncated file.

### GitHub code search

`tools/fetch_corpus.py --source github` retrieves files returned by GitHub
code search for `extension:frd`. GitHub caps the search at 1,000 results. After
deduplication by blob SHA, the corpus contains 927 files. The generated
`provenance.tsv` records each repository, path, and blob SHA.

Only 318 of these files are CalculiX FRD. The non-FRD population is useful
because it checks that arbitrary files do not produce an invented mesh.

Neither external corpus is committed. CalculiX is GPL-licensed, and files from
GitHub retain their source repository licenses. The fetch script records and
reproduces the corpus without adding it to this MIT repository.

## Generated fixtures

Handwritten fixtures reflect the cases their author expected. To add solver
output, `tools/generate_fixtures.py` solves 12 one-element decks with CalculiX
2.22. The input decks were written for this repository and are MIT-licensed.
The resulting 160 KB of FRD files is stored under
`tests/fixtures/generated/`.

`tests/test_fixture_bytes.py` requires each generated fixture to contain
CalculiX's `1UPGM` and `1UVERSION` banner. This prevents a handwritten file
from silently replacing solver output.

CalculiX 2.22 does not accept the experimental C3D5 or C3D13 pyramid elements.
Those two types appear in neither external corpus and are covered only by the
handwritten `PY5.frd` and `PY13.frd` fixtures. Linear tetrahedra are covered by
fixtures but not by this external CalculiX corpus.

## Comparison method

`tools/sweep_external.py` compares:

- point coordinates and original node IDs;
- cell types, offsets, and connectivity;
- time values;
- array names, order, shape, component count, and values.

Values read directly from the file and von Mises arrays must match bit for
bit. Principal values use a tolerance of 32 ulp of the source tensor magnitude
because the readers use different eigensolvers. See
[Differences from PyVista](divergences.md).

Each file receives one verdict:

| Verdict | Meaning |
| --- | --- |
| `agree` | Both readers return matching data. |
| `differ` | Returned data differs. |
| `both-decline` | Both reject the file with the same exception and message. |
| `both-refuse` | Both reject the file with documented error-message differences. |
| `beyond-oracle` | This reader succeeds but PyVista cannot grade the file. |
| `error` | The sweep itself failed. |

The command exits nonzero for `differ` or `error`.

## Findings from the sweep

The external run found two problems in the comparison harness and two fixture
coverage gaps.

### NaN comparison

Three network-analysis files contain literal `NaN` coordinates. Both readers
returned matching NaNs, but `numpy.array_equal` reported a difference because
`NaN != NaN`. The comparison now checks floating-point bit patterns.

### Expected empty files

The harness classified 34 matching `ValueError` exceptions as internal errors
because the PyVista grid-building call was outside its exception handling. The
comparison now distinguishes matching rejection from a harness failure.

### Signed zero

Bit-pattern comparison also distinguishes `-0.0` from `+0.0`, which ordinary
NumPy equality does not. Twenty-one CalculiX files contain negative zero, but
the original project fixtures contained none. The suite now includes
`signed_zero.frd` and uses `assert_bitwise_equal` for exact comparisons.

### Newline preservation

Git treated `mock_crlf.frd` as text, so a checkout with newline conversion
could make it identical to the LF fixture while the newline test still passed.
The repository now marks `*.frd binary` in `.gitattributes`, and
`tests/test_fixture_bytes.py` checks the expected bytes.

## Performance

`tools/bench_corpus.py` measured all 839 CalculiX files, totaling 125 MB. Each
reader materialized every result array. Values are the best of three runs per
file.

| Reader | Total time |
| --- | ---: |
| PyVista | 8.72 s |
| pyvista-frd-reader | 1.17 s |

The aggregate ratio is 7.42x. Per-file ratios were:

| p0 | p10 | p25 | p50 | p75 | p90 | p100 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.83x | 1.50x | 3.26x | 5.49x | 7.26x | 9.60x | 37.67x |

Two small files were slower with this package. Files larger than 1 MB had a
median ratio of 5.25x; files smaller than 64 KB had a median ratio of 3.51x.
Absolute times apply to the measured workstation.

## Reproduce the sweep

The CalculiX run requires `ccx` 2.22. The GitHub fetch requires an
authenticated `gh` client.

```bash
python tools/fetch_corpus.py --source calculix --ccx ccx
python tools/fetch_corpus.py --source github

python tools/sweep_external.py external-corpus/calculix --json sweep.json
python tools/sweep_external.py external-corpus/github --json gh-sweep.json
python tools/sweep_rewrite.py external-corpus --json rewrite.json
python tools/bench_corpus.py external-corpus/calculix --json bench.json
```

## Limits

- Agreement with PyVista is not independent proof of correctness.
- PyVista cannot grade binary FRD. Binary checks use paired CalculiX output and
  one published binary file.
- Most files in both corpora were produced by `ccx`, so the corpora are not
  independent.
- Eleven CalculiX decks produced no FRD output.
- GitHub code search is capped at 1,000 results.
- Performance was measured on one machine.
- PY5 and PY13 appear in no external file. Linear tetrahedra appear in project
  fixtures but not in this external CalculiX run.
- The result applies only to the files in these corpora.
