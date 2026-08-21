# Where this work came from

This library did not invent anything. It is a reimplementation, in C++ behind a
C ABI, of a reader that already existed and already worked, and the design it
implements — which records matter, how a block becomes an array, what the
derived quantities are named, what happens at each edge case — is not ours.
Getting the credit for that right is the point of this file, and it comes
before the technical history because it is the more important half.

## The reader

**Rafal ([@3rav](https://github.com/3rav)) wrote the FRD reader.** Every
behavioural decision this project reproduces is one he made first.

| | |
| --- | --- |
| [pyvista#8255](https://github.com/pyvista/pyvista/pull/8255) | *Add the ability to read CalculiX .frd files.* Opened 2026-01-22, merged 2026-03-10. The original implementation. |
| [pyvista#8448](https://github.com/pyvista/pyvista/pull/8448) | *Refactor FRD parsing to handle multiple formats.* Merged 2026-04-26. The short/long/fixed-width format handling this library reproduces in `cpp/src/parse.cpp`. |
| [pyvista#8936](https://github.com/pyvista/pyvista/pull/8936) | *Support C3D5/C3D13 pyramid elements in FRDReader*, from his own issue [#8923](https://github.com/pyvista/pyvista/issues/8923). Open at the time of writing; this library reads those elements because that pull request does. |

The feature was requested by
**[@efirvida](https://github.com/efirvida)** in
[pyvista#5350](https://github.com/pyvista/pyvista/issues/5350) on 2023-12-15,
and waited two years for someone to pick it up.

Later maintenance on the same file — VTK 9.7 compatibility in
[pyvista#8819](https://github.com/pyvista/pyvista/pull/8819) and the standard
library import conventions in
[pyvista#8868](https://github.com/pyvista/pyvista/pull/8868) — is
**[@user27182](https://github.com/user27182)**'s. The VTK 9.7 work is the
reason this library has a wedge-ordering option at all: see
`doc/divergences.md`.

A copy of that reader lives in this repository at
`tests/conformance/ref_frd.py`, taken verbatim from
`pyvista/core/utilities/_frd.py` and deliberately never edited. It is the
oracle every conformance test is graded against, so in a real sense his code
is still the specification here — this project's claim is not "a better FRD
reader" but "the same answers, from C++, available to callers who are not
Python".

## The format

The FRD format belongs to **CalculiX**, by **Guido Dhondt** (the CrunchiX
solver, which writes these files) and **Klaus Wittig** (the CalculiX GraphiX
pre- and post-processor, which reads them). CalculiX is free software under the
GPL, and its documentation and source are at <http://www.dhondt.de/>.

There is no independent specification of FRD to implement against. The format
is what `ccx` writes and what `cgx` reads, which is why the parity sweep in
`doc/parity.md` runs against files produced by CalculiX itself rather than
against files we wrote to look like its output.

## What this project added

The parts that are ours are the ones that follow from moving the work into
C++, and they are narrower than the line count suggests:

- a C ABI (`cpp/include/pvfrd/pvfrd.h`) that hands mesh and result arrays to
  any language, with the ownership and error-reporting rules a C ABI needs;
- a parser written against bytes rather than decoded text, which is where the
  divergences in `doc/divergences.md` come from and where four genuine
  compatibility bugs were found and fixed;
- the derived quantities (von Mises, principal values) computed without a
  LAPACK dependency, in an association order chosen to reproduce NumPy's
  bit for bit;
- the test apparatus: a gtest tier, a mutation harness, a fuzzer, and the
  conformance sweep that grades all of it against the oracle above.

None of that is a claim to have improved the reader. Where this library is
faster it is faster because C++ is, not because the algorithm is better; where
it is more careful about a byte, that care is in service of matching what the
Python reader already does.

## Licensing

| Thing | Licence | Where it lives |
| --- | --- | --- |
| This library | MIT | `LICENSE` |
| PyVista, including the reader this reimplements | MIT | upstream |
| The vendored oracle | MIT, as part of PyVista | `tests/conformance/ref_frd.py` |
| CalculiX, and its regression suite | GPL | **not vendored** — see below |

The MIT-to-MIT relationship is why the oracle can be vendored at all, and the
header of that file states where it came from and at which commit.

CalculiX's regression suite is the best FRD corpus in existence and it is GPL,
so none of it is in this repository. `tools/fetch_corpus.py` downloads it and
`tools/sweep_external.py` grades against it, which keeps the corpus
reproducible without taking on a licence this project cannot carry. The
fixtures under `tests/fixtures/` are written here, for this repository, and are
covered by its MIT licence.
