""".. _quickstart_example:

Read a result file
==================

:func:`pyvista_frd.read` turns a CalculiX ``.frd`` file into a
:class:`pyvista.UnstructuredGrid`. Every nodal result in the file arrives as
point data, and the mesh is ready to plot, clip, warp, or save in any format
PyVista writes.

The file here is a cantilever: 600 linear hexahedra fixed at one end and
loaded at the other, solved by CalculiX 2.22.
"""

from pathlib import Path

import pyvista as pv

import pyvista_frd

# Sphinx-Gallery runs each example from its own directory; the decks and
# their solved output live one level up, in ``doc/_data``.
DATA = Path('../_data').resolve()

# %%
# Reading is one call.

mesh = pyvista_frd.read(DATA / 'cantilever.frd')
mesh

# %%
# The arrays are named as CalculiX named them. ``DISP`` and ``STRESS`` came off
# the file; the ``_Mises`` and ``_PS*`` arrays are computed from the stress
# tensor on the way through, matching what PyVista's own reader appends.

for name in mesh.point_data:
    array = mesh.point_data[name]
    print(f'{name:16s} {array.shape}')

# %%
# Deflection under load, drawn on the deformed shape. The displacements are
# small, so :meth:`pyvista.DataSetFilters.warp_by_vector` exaggerates them.

warped = mesh.warp_by_vector('DISP', factor=200)

pl = pv.Plotter(window_size=(1000, 380))
pl.add_mesh(warped, scalars='DISP', component=2, cmap='coolwarm', show_edges=True)
pl.add_mesh(mesh, style='wireframe', color='grey', opacity=0.3)
pl.camera.tight(padding=0.05, adjust_render_window=False, view='xz')
pl.show()

# %%
# Nothing about the result is special to this package once it is read. It is an
# ordinary PyVista mesh, so the usual filters apply.

pl = pv.Plotter(window_size=(1000, 380))
pl.add_mesh(warped.clip('y'), scalars='STRESS_Mises', cmap='inferno', show_edges=True)
pl.camera.tight(padding=0.05, adjust_render_window=False, view='xz')
pl.show()
