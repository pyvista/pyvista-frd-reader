""".. _named_surfaces_example:

Plot named faces, an internal section, and a nodal surface
==========================================================

Named surfaces retain results on the exact faces identified by the input deck.
They can include internal faces, which an exterior-skin extraction would omit.
This example uses the checked-in cantilever result and companion input files;
no download or solver is needed. See :doc:`/surfaces` for the input syntax,
face numbering, limitations, and links to every required file.

Run from any working directory::

    python / path / to / checkout / doc / examples / plot_g_surfaces.py
"""

from pathlib import Path

import numpy as np
import pyvista as pv

import pyvista_frd

# Sphinx-Gallery executes code blocks without __file__, from doc/examples.
DATA = (
    Path(__file__).resolve().parents[1] / '_data'
    if '__file__' in globals()
    else Path('../_data').resolve()
)
reader = pyvista_frd.FRDReader(DATA / 'cantilever.frd', inp_path=DATA / 'cantilever-surfaces.inp')
mesh = reader.read()
surfaces = reader.read_surfaces()
print({name: surfaces[name].n_cells for name in reader.surface_names})
assert {name: surfaces[name].n_cells for name in reader.surface_names} == {
    'TOP': 120,
    'TIP': 25,
    'MIDSPAN': 25,
    'CLAMP': 36,
}

# %%
# The included ``surface-definitions.inc`` selects the upper layer's S2 faces,
# the tip's S4 faces, an internal plane of S4 faces, and the FIXED node set.
# The surface carries DISP and STRESS_Mises directly from its original nodes.
# Warping is an explicit visualization operation, using the same factor for
# both the parent mesh and its surfaces.

peak = np.linalg.norm(mesh['DISP'], axis=1).max()
factor = 0.08 * mesh.length / peak
pl = pv.Plotter(shape=(1, 2), window_size=(1400, 650))
pl.set_background('#f3f5f7')
pl.subplot(0, 0)
pl.add_text('Named top and tip faces', color='#172c45', font_size=14)
pl.add_text(f'Displacement magnified {factor:.1f}x', position='lower_left', font_size=9)
pl.add_mesh(mesh.warp_by_vector('DISP', factor=factor), color='#acb8c4', opacity=0.16)
for name in ['TOP', 'TIP']:
    pl.add_mesh(
        surfaces[name].warp_by_vector('DISP', factor=factor),
        scalars='STRESS_Mises',
        cmap='inferno',
        clim=mesh.get_data_range('STRESS_Mises'),
        show_edges=True,
        edge_color='#4f4545',
        scalar_bar_args={'title': 'von Mises stress', 'color': '#172c45'},
    )
pl.view_isometric()
pl.camera.zoom(0.98)

# An internal face is still a surface member. Plot it with the nodal clamp and
# an undeformed wireframe to show exactly where the deck places both regions.
# NODE surfaces contain vertices; no faces are invented between their nodes.

pl.subplot(0, 1)
pl.add_text('Internal section and nodal clamp', color='#172c45', font_size=14)
pl.add_mesh(mesh, style='wireframe', color='#8a9aad', opacity=0.18)
pl.add_mesh(
    surfaces['MIDSPAN'],
    scalars='STRESS_Mises',
    cmap='inferno',
    show_edges=True,
    edge_color='#4f4545',
    scalar_bar_args={'title': 'Section von Mises stress', 'color': '#172c45'},
)
pl.add_mesh(surfaces['CLAMP'], color='#008c95', point_size=12, render_points_as_spheres=True)
pl.add_point_labels(
    [[0.0, 10.0, 10.0], [75.0, 10.0, 10.0]],
    ['CLAMP: 36 nodes', 'MIDSPAN: 25 faces'],
    font_size=12,
    always_visible=True,
    show_points=False,
)
pl.view_isometric()
pl.camera.zoom(0.98)
pl.show()
