# Named surfaces

Read a CalculiX `*SURFACE` definition as actual face, edge, or vertex cells,
with the active FRD step's results attached:

```python
import pyvista_frd

reader = pyvista_frd.FRDReader('model.frd', inp_path='model.inp')
print(reader.surface_names)
wall = reader.read_surface('WALL')
wall.plot(scalars='STRESS_Mises')

# Read every surface from the current step into a named PyVista MultiBlock.
regions = reader.read_surfaces()
```

This implements the `(element ID, face label)` approach discussed in
[PR #12](https://github.com/pyvista/pyvista-frd-reader/pull/12#issuecomment-5630415328).
A surface can contain internal faces, several faces of one element, or faces
from different supported element types. It is not restricted to the exterior
skin of the mesh. The parent volume remains available through `reader.read()`.

## Defining and inspecting surfaces

For a model with the referenced IDs, a companion deck can contain:

```text
*NSET, NSET=FIXED
1, 5, 9
*ELSET, ELSET=TOP_LAYER, GENERATE
101, 120
*SURFACE, NAME=WALL, TYPE=ELEMENT
TOP_LAYER, S2
125, S4
*SURFACE, NAME=CLAMP, TYPE=NODE
FIXED
17
```

`TYPE=ELEMENT` is the default. Each data row is an element ID or a previously
defined ELSET, followed by a face label. `TYPE=NODE` accepts one node ID or
previously defined NSET per row. A nodal surface is a vertex grid with nodal
results; the reader does not invent polygon connectivity between its nodes.

Includes, comments, continued keyword headers, mixed case, and repeated
surface definitions are supported. Repeated definitions add unique members.
Set references copy membership at the point of use. Later additions to a set
do not retroactively change a surface. See [set syntax](sets.md) for include
resolution, implicit sets, and generated ranges.

Names and face labels become uppercase. NODE and ELEMENT surfaces can share a
name, as they do in published CalculiX metalforming examples. When they do,
the keys are `NODE:NAME` and `ELEMENT:NAME`; use the complete key returned by
`surface_names`. Otherwise the key is simply `NAME`. A collision between a
literal name and a qualified name raises an error.

Read the metadata without opening any FRD:

```python
data = pyvista_frd.read_sets('model.inp')
assert data.surfaces['WALL'].kind == 'ELEMENT'
print(data.surfaces['WALL'].element_faces)  # sorted (original ID, label) tuples
print(data.surfaces['CLAMP'].node_ids)      # sorted original node IDs
print(data.element_types)                 # original element ID -> INP type
```

The same `INPSets` object is available through `reader.sets`. Its
`INPSurface` definitions retain all referenced IDs, including those absent
from the result. `element_types` records `*ELEMENT, TYPE=...` declarations
even when no ELSET is declared; these disambiguate plane, shell, and solid
face conventions. Supply the original deck or equivalent element type
metadata when selecting faces of a lower-dimensional input model.

## Face numbering and output cells

Face labels follow the documented CalculiX input interface, **not VTK face
indices**. These are the one-based local corner memberships of solid faces:

| Parent | S1 | S2 | S3 | S4 | S5 | S6 |
| --- | --- | --- | --- | --- | --- | --- |
| Hexahedron, 8 or 20 nodes | 1,2,3,4 | 5,8,7,6 | 1,5,6,2 | 2,6,7,3 | 3,7,8,4 | 4,8,5,1 |
| Tetrahedron, 4 or 10 nodes | 1,2,3 | 1,4,2 | 2,4,3 | 3,4,1 | — | — |
| Wedge, 6 or 15 nodes | 1,2,3 | 4,5,6 | 1,2,5,4 | 2,3,6,5 | 3,1,4,6 | — |

The corresponding VTK face supplies its winding and midside connectivity.
For valid, positively oriented solids the winding points outward from the
parent element, including on internal faces. This does not repair inverted
or degenerate elements. Linear and quadratic triangles and quadrilaterals
remain those cell types: quadratic faces keep all six or eight nodes and are
not silently linearized or triangulated. The reader also accounts for VTK's
linear-wedge ordering change in version 9.7. Older VTK quadratic-wedge face
winding is normalized using the reference cell's coordinates, without altering
user geometry. Compare the face tables in
[VTK 9.3.1](https://github.com/Kitware/VTK/blob/v9.3.1/Common/DataModel/vtkQuadraticWedge.cxx)
and [VTK 9.6.2](https://github.com/Kitware/VTK/blob/v9.6.2/Common/DataModel/vtkQuadraticWedge.cxx).

| INP family / FRD representation | Supported selection |
| --- | --- |
| `C3D`, `DC3D`, `F3D` supported solid topologies | Solid face table above |
| Triangular or quadrilateral shells (`S3`, `S6`, `S4`, `S8`, variants; `M3D`) | `S1`/`SNEG` negative side, `S2`/`SPOS` positive side; `S3` onward selects consecutive edges |
| Plane stress/strain and axisymmetric (`CPS`, `CPE`, `CAX`) | `S1` onward selects consecutive edges; `CPS` also accepts `SN`/`SP` for negative/positive sides |
| Shells or plane elements expanded by CalculiX into solids | The corresponding faces of the **stored expanded geometry**; plane edge number `n` maps to solid face `n + 2` |
| Beams expanded into hexahedra | Documented beam faces `S1`, `S2`, `S3`, `S5` |
| User elements (`U...`) stored as triangles/quadrilaterals | Explicit `SNEG`/`SPOS` only; numeric face numbering is not inferred |
| `TYPE=NODE` | One vertex per available original node ID |

For an unexpanded planar cell, selecting an edge produces a linear or
quadratic line; selecting a signed side produces the whole planar cell with
the appropriate winding. For expanded output, the reader selects the actual
stored solid face and its stored results. It does not reconstruct a midsurface,
unexpanded beam cross-section, or original node IDs lost during expansion.

The interface references are the `*SURFACE` and `*ELEMENT` sections of the
[CalculiX 2.23 manual](https://www.dhondt.de/ccx_2.23.pdf)
([HTML archive](https://www.dhondt.de/ccx_2.23.htm.tar.bz2)). The
[public HTML surface reference](https://web.mit.edu/calculix_v2.7/CalculiX/ccx_2.7/doc/ccx/node247.html)
also shows these face conventions. Published solver files are used strictly
for file-decoding, connectivity, and result-transfer interoperability; no
numerical formulation or solver acceptance threshold is derived from them.

## Results, time steps, and missing IDs

Each returned grid has compact point indexing, copied coordinates, and all
parent point arrays, including displacement, stress, derived values, NSET
masks, and `original_node_ids`. Element surfaces copy the parent cell arrays,
including ELSET masks and `original_element_ids`, once per selected face.
`surface_face_labels` identifies each cell's original face label. Multiple
faces of one element therefore legitimately repeat its element ID. Field
data is copied as well. Nodal surfaces have no parent-element cell arrays.

No interpolation, averaging, deformation, or new stress calculation is
performed by surface extraction. Returned arrays have independent storage.
Changing the result step affects subsequent reads, not already returned grids:

```python
reader.set_active_time_point(2)
wall = reader.read_surface('WALL')
deformed = wall.warp_by_vector('DISP', factor=10)
```

By default, an absent referenced node or element raises `ValueError`. This
can happen with restricted FRD output or expanded beam/shell nodes. To inspect
only the available members explicitly:

```python
wall = reader.read_surface('WALL', missing='warn')
print(wall.field_data['missing_element_ids'])
clamp = reader.read_surface('CLAMP', missing='warn')
print(clamp.field_data['missing_node_ids'])
```

The warning reports a count and a short ID preview; field data contains the
complete sorted missing-ID list, or an empty array when none are missing.
A surface with no available members returns an empty grid under `'warn'`;
check `n_cells` before plotting. Invalid labels, unsupported mappings, and
ambiguous duplicate FRD element IDs still raise. The missing-ID option never
suppresses a connectivity error.

Pyramid surface numbering, unexpanded beam surfaces, analytical surfaces,
automatic free-face generation, surface combinations/trimming, and nodal area
weights are unsupported. Part/assembly/instance namespaces and sets generated
by mesh-generation keywords retain the limitations documented in [sets](sets.md).
Unsupported surface syntax fails explicitly with source location. Unsupported
face mappings fail at extraction with the element ID and face label. The FRD
writer does not export surface metadata: retain the companion INP files.

## Reproduce the galleries

The [named-face gallery](gallery/plot_g_surfaces.rst) plots deformed top/tip
faces, an internal section, and a nodal clamp. The
[modal surface gallery](gallery/plot_h_surface_modes.rst) follows the same
surfaces through all four modes. Both use complete checked-in inputs and run
without a solver, network access, or external corpus downloads.

From a source checkout or extracted source distribution:

```bash
python -m pip install .
python doc/examples/plot_g_surfaces.py
python doc/examples/plot_h_surface_modes.py
```

For a headless machine, set `PYVISTA_OFF_SCREEN=true`. To build the illustrated
gallery pages, install the documentation dependencies and run:

```bash
python -m pip install '.[docs]'
PYVISTA_OFF_SCREEN=true python -m sphinx -b html doc doc/_build/html -W
```

The scripts resolve data relative to their own location. If downloading files
individually, preserve this directory structure:

| Location under `doc/` | Download |
| --- | --- |
| `examples/plot_g_surfaces.py` | {download}`Named-face script <examples/plot_g_surfaces.py>` |
| `examples/plot_h_surface_modes.py` | {download}`Modal script <examples/plot_h_surface_modes.py>` |
| `_data/cantilever.frd` | {download}`Static result <_data/cantilever.frd>` |
| `_data/modes.frd` | {download}`Four-mode result <_data/modes.frd>` |
| `_data/cantilever-surfaces.inp` | {download}`Static companion <_data/cantilever-surfaces.inp>` |
| `_data/modes-surfaces.inp` | {download}`Modal companion <_data/modes-surfaces.inp>` |
| `_data/surface-definitions.inc` | {download}`Shared surface definitions <_data/surface-definitions.inc>` |
| `_data/src/cantilever.inp` | {download}`Original static mesh/deck <_data/src/cantilever.inp>` |
| `_data/src/modes.inp` | {download}`Original modal mesh/deck <_data/src/modes.inp>` |

The existing result files were generated by CalculiX 2.22 with
`tools/generate_docs_data.py`. The new companion files add postprocessing
metadata through includes; regenerating the solver output is unnecessary.
The assertions in both scripts check their expected surface sizes during the
documentation build. The source distribution includes all these assets.

## Public dataset validation

The search covered the official CalculiX 2.22 and 2.23 regression archives,
CalculiX examples, FreeCAD FEM fixtures, gmsh2ccx, pybaqus input decks,
ccxmeshreader, preCICE tutorials/training, and all repositories returned by
these GitHub code queries:

- `extension:inp SURFACE calculix`
- `extension:sur SURFACE`
- `extension:inp SPOS ccx`

Every returned matching directory and its subdirectories was scanned for
supported input, include, and result extensions, preserving companion paths.
The additional surface search downloaded **7,623 files with zero download
errors**. Each repository revision is pinned, every downloaded Git blob is
verified, and SHA-256 hashes are recorded. Duplicate blobs share a local cache.
This is a broad reproducible search, not a claim to exhaust the internet:
GitHub indexing, access, changing page totals, and its 1,000-result query cap
bound discovery. These queries did not reach the cap or report incomplete
results. `.sur` also matches unrelated formats; downloads are never executed.

### Validation on 2026-09-11

| Check | Outcome |
| --- | --- |
| Input files attempted (`.inp` and `.sur`) | 7,371, with 1,983 distinct SHA-256 hashes |
| Parsing | 7,174 parsed; 197 rejected |
| Decks defining surfaces | 1,454; 3,655 definitions, including 700 nodal surfaces |
| Available companion FRD files for surface decks | 228 |
| Named surface outputs checked | 456 across 9,104 surface/time-step checks; zero extraction/transfer failures |
| Nonempty outputs / missing-only outputs | 435 / 21; all 21 missing-only outputs explicitly warned and recorded missing IDs |

Counts include duplicate files across sources. Parsed decks with no companion
FRD are **not** counted as extraction tests. The sweep checks exact surviving
membership and cardinality, face-parent membership, unchanged coordinates,
all point and parent-cell arrays, and missing-ID lists at every stored time
step. It does not independently prove face numbering; separate authored
regressions pin every face and midside membership of six solid topologies in
all four FRD encodings, plus shell/plane/beam mappings and orientation.
The audit itself is tested against deliberately empty and altered outputs.
The broader FRD comparison attempted 2,008 files: 1,347 agreed with the
independent reader, four binary files were beyond that reader, and 657 were
declined by both; there were no divergences. These counts include files
retrieved by the earlier FRD-only searches documented in [sets](sets.md).

Of the rejected files, 145 reference missing includes, 44 use assembly/instance
syntax, two reference undefined sets, two use generated sets, two contain
zero IDs, and two have invalid generated ranges. The
[complete rejection inventory](_static/surface-rejections.tsv) preserves every
failure. The {download}`complete surface audit <_static/surface-validation.json.gz>`
records parsed and rejected decks, hashes, paired result files, per-surface
checks, time-step counts, and missing-ID warnings. Unsupported or incomplete
input does not silently count as a pass.

Reproduce the pinned downloads and checks from the repository root:

```bash
python tools/fetch_inp_corpus.py
python tools/fetch_surface_corpus.py --replay doc/_static/surface-downloads.json.gz
python tools/sweep_surfaces.py external-corpus --json external-corpus/surface-sweep.json
python tools/sweep_external.py external-corpus --json external-corpus/frd-sweep.json
```

The surface sweep intentionally exits nonzero when a deck is rejected or a
pair fails; inspect the JSON inventory for the distinction. Omit `--replay`
to perform a new authenticated GitHub search (`gh auth login` is required for
discovery). Replaying the {download}`pinned manifest <_static/surface-downloads.json.gz>`
uses public immutable download URLs and does not require GitHub authentication.
The earlier FRD-only search inventory is documented in [sets](sets.md).
Files stay in the ignored `external-corpus/` directory with their upstream
licenses. The download manifests and full sweep reports retain per-file
provenance; no solver is run by these tools.
