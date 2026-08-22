""".. _time_steps_example:

Step through a multi-step file
==============================

An FRD file holds one block per result per step. :class:`pyvista_frd.FRDReader`
implements PyVista's :class:`~pyvista.TimeReader` interface, so the steps are
addressed the same way they are for any other time-varying format.

The file here is a modal analysis: CalculiX writes one step per mode, and the
"time value" of each is the natural frequency in Hz.
"""

from pathlib import Path

import numpy as np
import pyvista as pv

import pyvista_frd

# Sphinx-Gallery runs each example from its own directory; the decks and
# their solved output live one level up, in ``doc/_data``.
DATA = Path('../_data').resolve()

reader = pyvista_frd.FRDReader(DATA / 'modes.frd')

# %%
# What the file holds.

print(f'{reader.number_time_points} steps')
for i, value in enumerate(reader.time_values):
    print(f'  mode {i + 1}: {value:10.2f} Hz')

# %%
# Selecting a step and reading it. Only the step asked for is parsed -- the
# blocks are indexed when the file is opened and the values of a step are
# materialised the first time that step is requested, so reading one mode of a
# many-mode file does not cost the whole file.

reader.set_active_time_point(0)
first = reader.read()
print(f'mode 1 peak displacement: {first.point_data["DISP"].max():.4f}')

# %%
# Every mode, drawn on its own deformed shape.

pl = pv.Plotter(shape=(2, 2), window_size=(1100, 620))
for index in range(reader.number_time_points):
    reader.set_active_time_point(index)
    mesh = reader.read()

    # A mode shape is an eigenvector, so its amplitude is arbitrary. Scale each
    # one to a fixed fraction of the beam instead of applying one factor to all
    # four, which would leave the stiffer modes invisible.
    peak = np.linalg.norm(mesh.point_data['DISP'], axis=1).max()
    warped = mesh.warp_by_vector('DISP', factor=0.12 * mesh.length / peak)

    pl.subplot(index // 2, index % 2)
    pl.add_text(f'mode {index + 1}   {reader.time_values[index]:.0f} Hz', font_size=9)
    pl.add_mesh(warped, scalars='DISP', cmap='viridis', show_scalar_bar=False)
    pl.add_mesh(mesh, style='wireframe', color='lightgrey', opacity=0.4)
    pl.view_xz()
    pl.camera.zoom(1.3)
pl.show()

# %%
# :meth:`~pyvista_frd.FRDReader.set_active_time_value` selects by value rather
# than by index, and requires an exact match: a frequency that is not in the
# file is an error, not the nearest neighbour.

reader.set_active_time_value(reader.time_values[-1])
print(f'active step is now {reader.active_time_value:.2f} Hz')
