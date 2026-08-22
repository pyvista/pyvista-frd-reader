""".. _derived_example:

Derived stress quantities
=========================

CalculiX writes a six-component stress tensor. It does not write von Mises
stress or the principal values, because those are functions of what is already
there. This reader computes them on the way through, under the names PyVista's
own reader uses, so a script written against one works against the other.

For any array whose name contains ``STRESS`` or ``STRAIN`` and which has six
components, five arrays are appended.
"""

from pathlib import Path

import numpy as np
import pyvista as pv

import pyvista_frd

# Sphinx-Gallery runs each example from its own directory; the decks and
# their solved output live one level up, in ``doc/_data``.
DATA = Path('../_data').resolve()
mesh = pyvista_frd.read(DATA / 'cantilever.frd')

# %%
# The tensor and what comes from it.

print('stored :', mesh.point_data['STRESS'].shape, '(xx, yy, zz, xy, yz, zx)')
for name in ('STRESS_Mises', 'STRESS_sgMises', 'STRESS_PS1', 'STRESS_PS2', 'STRESS_PS3'):
    print(f'derived: {name:16s} {mesh.point_data[name].shape}')

# %%
# ``_Mises`` is the equivalent stress and ``_sgMises`` the same magnitude
# carrying the sign of the trace, which separates tension from compression in a
# single scalar. The cantilever is in bending, so the two faces disagree.

warped = mesh.warp_by_vector('DISP', factor=200)

pl = pv.Plotter(shape=(2, 1), window_size=(1000, 640))
for row, (name, cmap) in enumerate((('STRESS_Mises', 'inferno'), ('STRESS_sgMises', 'coolwarm'))):
    pl.subplot(row, 0)
    pl.add_text(name, font_size=10)
    pl.add_mesh(warped.copy(), scalars=name, cmap=cmap)
    pl.camera.tight(padding=0.12, adjust_render_window=False, view='xz')
pl.show()

# %%
# The principal values are the eigenvalues of the tensor, ascending, so
# ``PS1`` is the largest and ``PS3`` the smallest. In a bent beam the largest
# principal stress picks out the tension side.

pl = pv.Plotter(shape=(3, 1), window_size=(1000, 840))
for row, name in enumerate(('STRESS_PS1', 'STRESS_PS2', 'STRESS_PS3')):
    pl.subplot(row, 0)
    pl.add_text(name, font_size=9)
    pl.add_mesh(warped.copy(), scalars=name, cmap='coolwarm')
    pl.camera.tight(padding=0.12, adjust_render_window=False, view='xz')
pl.show()

# %%
# These are not approximations of the solver's own numbers -- CalculiX never
# wrote them. They are computed here, and the conformance suite requires the
# von Mises arrays to be **bit-identical** to PyVista's, which is why the
# expression order in the C++ core is fixed rather than merely equivalent.
#
# The principal values come from an eigensolver, where bit-identity is not an
# achievable goal, so those are held to a stated band instead. ``doc/
# divergences.md`` records the band and why it is measured against the
# magnitude of the tensor rather than of the eigenvalue.

mises = mesh.point_data['STRESS_Mises']
tensor = mesh.point_data['STRESS']
trace = tensor[:, :3].sum(axis=1)
print(f'peak von Mises      {mises.max():10.3f}')
print(f'nodes in tension    {int(np.count_nonzero(trace > 0)):10d} of {len(trace)}')
