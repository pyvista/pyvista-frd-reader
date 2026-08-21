# Generated fixtures

FRD files in this directory were **written by CalculiX**, not by this project.
The input decks in `src/` are ours and carry this repository's MIT licence; the
`.frd` files beside them are what `ccx` produced from those decks.

That is the point of the directory. Every fixture in `../elements/` was written
by hand, which means it encodes what this project *believes* CalculiX writes —
and a hand-written fixture graded against a hand-written reader can agree
perfectly while both are wrong about the bytes a real solver emits.

Regenerate with:

```bash
python tools/generate_fixtures.py --out tests/fixtures/generated
```

The files change on every regeneration, because CalculiX stamps the date and
time into the header. That is not noise to suppress — it is the record of when
and by which version they were produced.

**Not here: pyramids.** CalculiX 2.22 answers `C3D5 is an unknown element type`
and stops, and a census of 688 files solved from CalculiX's own 2.23 regression
suite contains no pyramid among 295,626 cells. The reader's PY5/PY13 support
therefore has no authentic fixture available; `../elements/PY5.frd` and
`PY13.frd` are hand-written and are the only evidence there is. See
`doc/parity.md`.
