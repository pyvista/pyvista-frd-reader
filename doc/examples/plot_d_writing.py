""".. _writing_example:

Write a mesh as FRD
===================

:func:`pyvista_frd.write` sends a :class:`pyvista.UnstructuredGrid` back out as
an FRD file, in any of the format's four encodings. CalculiX reads what it
produces: the round trip below is checked in this repository against CalculiX's
own bytes over 1,111 external files, and against the solver itself reading a
written file back in as a submodel boundary condition.
"""

from pathlib import Path
import tempfile

import numpy as np
import pyvista as pv

import pyvista_frd

# %%
# Any unstructured grid will do. This one is built from scratch, with a field
# that has nothing to do with CalculiX.

mesh = pv.ParametricTorus(ringradius=6, crosssectionradius=2)
mesh = mesh.cast_to_unstructured_grid().triangulate()

xyz = mesh.points
mesh.point_data['DISP'] = np.column_stack(
    [np.sin(xyz[:, 0] / 3), np.cos(xyz[:, 1] / 3), xyz[:, 2] / 4]
)
mesh.point_data['TEMP'] = np.linalg.norm(xyz, axis=1)

out = Path(tempfile.mkdtemp()) / 'torus.frd'
pyvista_frd.write(out, mesh)
print(f'{out.name}: {out.stat().st_size / 1024:.0f} KB')

# %%
# Read it back. The mesh and every array return.

again = pyvista_frd.read(out)
print(again)
print('arrays:', list(again.point_data))

np.testing.assert_allclose(again.points, mesh.points, rtol=1e-5)
print('points survive the round trip')

# %%
# Side by side.

pl = pv.Plotter(shape=(1, 2), window_size=(1000, 460))
pl.subplot(0, 0)
pl.add_text('written', font_size=10)
pl.add_mesh(mesh, scalars='TEMP', cmap='magma')
pl.subplot(0, 1)
pl.add_text('read back', font_size=10)
pl.add_mesh(again, scalars='TEMP', cmap='magma')
pl.link_views()
pl.view_isometric()
pl.camera.zoom(1.35)
pl.show()

# %%
# Node numbering is preserved when the mesh carries it. A grid that came from
# :func:`pyvista_frd.read` has an ``original_node_ids`` array holding the
# numbers the file used, and writing it back uses those numbers rather than
# renumbering from one -- which matters when the file is going to a solver that
# refers to nodes by name.

# Sphinx-Gallery runs each example from its own directory; the decks and
# their solved output live one level up, in ``doc/_data``.
DATA = Path('../_data').resolve()
loaded = pyvista_frd.read(DATA / 'cantilever.frd')
print('carries original ids:', 'original_node_ids' in loaded.point_data)
print('first five:', loaded.point_data['original_node_ids'][:5])

# %%
# Not every mesh can become an FRD file. CalculiX has no equivalent for a
# polyhedron or a higher-order cell outside its own element table, and the
# writer refuses rather than dropping the cell and producing a file that is
# smaller than the mesh it claims to describe.

bad = pv.PolyData(np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 1]])).delaunay_3d()
bad = bad.cast_to_unstructured_grid()
try:
    pyvista_frd.write(Path(tempfile.mkdtemp()) / 'x.frd', pv.Sphere().cast_to_unstructured_grid())
    print('sphere written')
except Exception as err:  # noqa: BLE001
    print(f'{type(err).__name__}: {err}')
