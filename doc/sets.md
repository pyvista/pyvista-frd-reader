# Node and element sets

Supply the input deck explicitly to attach its sets to an FRD result:

```python
import pyvista_frd

reader = pyvista_frd.FRDReader('model.frd', inp_path='model.inp')
mesh = reader.read()
fixed = mesh.extract_points(mesh.point_data['NSET:FIXED'])
body = mesh.extract_cells(mesh.cell_data['ELSET:BODY'])

# The convenience function accepts the same option.
mesh = pyvista_frd.read('model.frd', inp_path='model.inp', time_point=0)
```

Node sets become boolean `NSET:<NAME>` point arrays; element sets become
boolean `ELSET:<NAME>` cell arrays. Names are uppercase and the two namespaces
are separate. Masks are attached to every time step. An FRD result array
colliding with a set array name raises `ValueError` instead of being overwritten.
Calls without `inp_path` retain the existing output and never open a nearby deck.

When sets are present, `original_element_ids` contains integer FRD element IDs
in returned cell order. `original_node_ids` retains its existing string format.
Mapping uses the original IDs, including when they are sparse, out of order,
or belong to elements skipped by the FRD reader. It never assumes ID minus one
is a mesh index.

You can also read sets without an FRD file:

```python
sets = pyvista_frd.read_sets('model.inp')
fixed_node_ids = sets.node_sets['FIXED']
body_element_ids = sets.element_sets['BODY']
```

`read_sets` returns `INPSets`, with dictionaries of sorted, unique `int64` IDs.
The same object is available as `reader.sets`. These dictionaries retain IDs
absent from the FRD output, while mesh masks contain only IDs actually present.
This matters when output is restricted to a subset, or CalculiX expands beams
or shells into different output nodes. The reader does not infer a relationship
between original and newly generated IDs.

## Supported input syntax

- `*NSET` and `*ELSET`, with explicit IDs, references to previously defined
  sets, or `GENERATE` ranges with an optional increment (default 1).
- Repeated definitions add members; references copy membership as it exists
  when encountered, so later additions do not retroactively change other sets.
- Implicit sets on `*NODE, NSET=...` and `*ELEMENT, ELSET=...`, including
  continued element connectivity records.
- `*INCLUDE, INPUT=...`, nested includes, quoted filenames, comments, mixed
  keyword case, keyword continuations, and LF/CRLF/CR line endings.

Relative includes are resolved against the top-level deck's directory, treated
as the CalculiX job directory. Included content is inserted at the directive's
position, including inside a data block. Missing files and include cycles are
reported. Syntax errors identify the source file and line.

This API describes membership, not input-deck ordering: `UNSORTED` does not
preserve equation/constraint ordering. It does not evaluate a model. Surfaces
and their element-face mappings are not imported. Part/assembly/instance
namespaces, `*NSET, ELSET=...`, parameter substitution, and sets created by
mesh-generation keywords such as `*NGEN` are unsupported. Other analysis
keywords are ignored. The FRD writer does not export an INP deck or preserve
set semantics; use the original deck when importing sets again.

Syntax and connectivity counts follow the `*NODE`, `*ELEMENT`, `*NSET`,
`*ELSET`, and `*INCLUDE` entries in the
[CalculiX 2.23 manual](https://www.dhondt.de/ccx_2.23.pdf)
([HTML archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2)).

## Reproducing the external checks

```bash
python tools/fetch_inp_corpus.py
python tools/fetch_corpus.py --source github
python tools/fetch_corpus.py --source github --query 'extension:frd calculix'
python tools/sweep_inp.py external-corpus --json external-corpus/inp-sweep.json
python tools/sweep_external.py external-corpus --json external-corpus/frd-sweep.json
```

The fetcher pins repository commits, preserves companion paths, and records
source URLs and SHA-256 hashes. It downloads the published CalculiX 2.22 and
2.23 regression suites, CalculiX example collections, and FreeCAD FEM fixtures.
GitHub search adds more FRD files, including unrelated formats using the same
extension. Files remain in the ignored `external-corpus/` directory with their
upstream licenses. No solver is run: their purpose is file decoding and set
membership interoperability, not numerical solver validation.

The INP sweep attempts every deck, reports every rejection, and checks available
companion FRDs at every time step for membership mapping and unchanged geometry
and result arrays. It is a compatibility check, not an independent oracle for
INP parsing; authored tests pin set semantics and original-ID mappings. The
command exits nonzero if any deck is rejected or a companion check fails, so
unsupported or incomplete public examples cannot silently count as passes.

### Validation on 2026-09-10

| Check | Files attempted | Outcome |
| --- | ---: | --- |
| Input-deck parsing | 2,401 (1,313 distinct SHA-256 hashes) | 2,298 parsed; 103 rejected |
| Companion FRD set mapping | 432 | All passed, across 4,670 time steps |
| Existing FRD conformance | 1,355 (1,182 distinct SHA-256 hashes) | 698 agree, 2 binary beyond the reference reader, 655 declined by both; no divergences |

The input corpus comprises 1,040 decks from `calculix/examples`, 80 from
`calculix/CalculiX-Examples`, 33 from FreeCAD, and 610/638 from the CalculiX
2.22/2.23 archives. The FRD corpus comprises 907 GitHub downloads, 216/230
published reference files from the two archives, and two FreeCAD fixtures.
Totals include repeated files across sources; distinct-content counts are
reported separately. No newly computed solver output contributes to these counts.

Of the 103 rejected decks, 87 reference include files that are not present in
the downloaded collections, 14 use part/assembly/instance syntax, one uses
`*NGEN` to create a set, and one contains node ID zero. See the
[complete rejection inventory](_static/inp-rejections.tsv). A successfully
parsed deck may have no companion FRD; it does not count as a tested pair.

The [GitHub provenance inventory](_static/frd-github-provenance.tsv) records
repository paths and immutable Git blob SHAs for the additional FRD downloads.
The repository snapshots and official archive hashes are pinned in
`tools/fetch_inp_corpus.py`. Full local sweep reports and per-file download
hashes are written to `external-corpus/` by the commands above.
