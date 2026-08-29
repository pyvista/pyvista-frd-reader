""".. _elements_example:

Element types
=============

CalculiX names its elements by a numeric code in the second field of each
element record. This reader maps fourteen of them onto VTK cell types, which is
every type CalculiX's own ``frd.c`` writes plus the two experimental pyramids.

Each mesh below was solved by CalculiX from a one-element deck in
``tests/fixtures/generated/src``.
"""

from pathlib import Path

import pyvista as pv

import pyvista_frd

# %%
# The table the reader works from.

for code, name in sorted(pyvista_frd.ELEMENT_TYPE_NAMES.items()):
    print(f'  {code:3d}  {name}')

# %%
# One solved fixture per type, drawn together. The FRD files here are genuine
# CalculiX output; the decks that produced them are this repository's.
#
# Twelve of the fourteen appear. CalculiX 2.22 answers ``C3D5 is an unknown
# element type`` and stops, so there is no solver-written pyramid to draw --
# the PY5 and PY13 fixtures this package is tested against are hand-written.

root = Path('../../tests/fixtures/generated').resolve()
files = sorted(root.glob('*.frd'))

columns = 4
rows = -(-len(files) // columns)
pl = pv.Plotter(shape=(rows, columns), window_size=(900, 200 * rows))
for index, path in enumerate(files):
    mesh = pyvista_frd.read(path)
    pl.subplot(index // columns, index % columns)
    pl.add_text(path.stem, font_size=8)
    pl.add_mesh(mesh, show_edges=True, color='#c4a484', line_width=2)
    pl.add_points(mesh.points, color='crimson', point_size=8, render_points_as_spheres=True)
pl.show()

# %%
# An element the reader does not recognise, or one whose record holds the wrong
# number of nodes, is reported rather than silently dropped.
# :class:`pyvista.InvalidMeshWarning` is raised at construction naming the line
# it was found on, and the rest of the file still reads.
#
# The wedge is worth a note of its own. VTK changed the node order of a linear
# wedge at 9.7, so the correct connectivity depends on which VTK the cells are
# destined for. The Python layer reads that from the installed VTK; a C++
# caller has to say which convention it wants, because there is nothing to
# detect it from.

print('VTK', pv.vtk_version_info)
mesh = pyvista_frd.read(root / 'wedge6.frd')
print('wedge6 cell type:', mesh.celltypes, '->', pv.CellType(mesh.celltypes[0]).name)
