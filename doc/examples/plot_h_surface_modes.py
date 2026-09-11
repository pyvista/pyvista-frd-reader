""".. _surface_modes_example:

Follow named surfaces through vibration modes
=============================================

:class:`pyvista_frd.FRDReader` extracts a surface using the active result step.
Connectivity stays fixed while each read copies that step's nodal fields.
These four panels show the same TOP and TIP surfaces in four vibration modes.
All input files are checked in; see :doc:`/surfaces` for download links.

Run from any working directory::

    python / path / to / checkout / doc / examples / plot_h_surface_modes.py
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
reader = pyvista_frd.FRDReader(DATA / 'modes.frd', inp_path=DATA / 'modes-surfaces.inp')
assert reader.number_time_points == 4  # noqa: PLR2004 - the bundled four-mode result

# %%
# A modal eigenvector has arbitrary amplitude. Normalize the plotted magnitude
# and use the full mesh's peak to give TOP and TIP the same deformation scale.
# The reader's original DISP array is retained, unchanged, on each surface.

pl = pv.Plotter(shape=(2, 2), window_size=(1400, 850))
for index, frequency in enumerate(reader.time_values):
    reader.set_active_time_point(index)
    mesh = reader.read()
    peak = np.linalg.norm(mesh['DISP'], axis=1).max()
    factor = 0.12 * mesh.length / peak
    pl.subplot(index // 2, index % 2)
    pl.set_background('#f3f5f7')
    pl.add_text(f'Mode {index + 1}  |  {frequency:.1f} Hz', color='#172c45', font_size=12)
    pl.add_mesh(mesh, style='wireframe', color='#8a9aad', opacity=0.15)
    for name, count in [('TOP', 120), ('TIP', 25)]:
        surface = reader.read_surface(name)
        assert surface.n_cells == count
        surface['Relative amplitude'] = np.linalg.norm(surface['DISP'], axis=1) / peak
        pl.add_mesh(
            surface.warp_by_vector('DISP', factor=factor),
            scalars='Relative amplitude',
            cmap='viridis',
            clim=(0, 1),
            show_edges=True,
            edge_color='#41516b',
            scalar_bar_args={'title': 'Relative amplitude', 'color': '#172c45'},
        )
    pl.view_isometric()
    pl.camera.zoom(1.3)
pl.show()

# %%
# Selecting by the stored time value gives the same surface as selecting by
# index. Here the stored values are natural frequencies, not elapsed seconds.

reader.set_active_time_value(reader.time_values[-1])
print(f'TIP at {reader.active_time_value:.1f} Hz: {reader.read_surface("TIP").n_cells} faces')
