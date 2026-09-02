""".. _derived_example:

Derived stress quantities
=========================

CalculiX stores a six-component stress tensor. This reader derives von Mises
stress and principal values under the names used by PyVista's FRD reader.

For any array whose name contains ``STRESS`` or ``STRAIN`` and which has six
components, five arrays are appended.
"""

from pathlib import Path

import numpy as np
import pyvista as pv

import pyvista_frd

# Sphinx-Gallery runs this file from ``doc/examples``.
DATA = Path('../_data').resolve()
mesh = pyvista_frd.read(DATA / 'cantilever.frd')

# %%
# List the stored tensor and derived arrays.

print('stored :', mesh.point_data['STRESS'].shape, '(xx, yy, zz, xy, yz, zx)')
for name in ('STRESS_Mises', 'STRESS_sgMises', 'STRESS_PS1', 'STRESS_PS2', 'STRESS_PS3'):
    print(f'derived: {name:16s} {mesh.point_data[name].shape}')

# %%
# ``_sgMises`` applies the sign of the tensor trace to the von Mises magnitude.
# The sign separates the tensile and compressive faces of this bent beam.

warped = mesh.warp_by_vector('DISP', factor=200)

pl = pv.Plotter(shape=(2, 1), window_size=(1000, 640))
for row, (name, cmap) in enumerate((('STRESS_Mises', 'inferno'), ('STRESS_sgMises', 'coolwarm'))):
    pl.subplot(row, 0)
    pl.add_text(name, font_size=10)
    pl.add_mesh(warped.copy(), scalars=name, cmap=cmap)
    pl.camera.tight(padding=0.12, adjust_render_window=False, view='xz')
pl.show()

# %%
# The principal values are ordered from largest (``PS1``) to smallest
# (``PS3``).

pl = pv.Plotter(shape=(3, 1), window_size=(1000, 840))
for row, name in enumerate(('STRESS_PS1', 'STRESS_PS2', 'STRESS_PS3')):
    pl.subplot(row, 0)
    pl.add_text(name, font_size=9)
    pl.add_mesh(warped.copy(), scalars=name, cmap='coolwarm')
    pl.camera.tight(padding=0.12, adjust_render_window=False, view='xz')
pl.show()

# %%
# CalculiX does not store these derived arrays. The conformance tests require
# the von Mises arrays to match PyVista bit for bit. Principal values use a
# tolerance because the two implementations use different eigensolvers.

mises = mesh.point_data['STRESS_Mises']
tensor = mesh.point_data['STRESS']
trace = tensor[:, :3].sum(axis=1)
print(f'peak von Mises      {mises.max():10.3f}')
print(f'nodes in tension    {int(np.count_nonzero(trace > 0)):10d} of {len(trace)}')
