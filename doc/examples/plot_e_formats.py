""".. _formats_example:

The four encodings
==================

The last field of every FRD block header is a format code, and there are four
of them: two ASCII widths and two binary ones. CalculiX writes binary
unconditionally from ``*REFINE MESH`` and on demand from a ``DOUBLE`` output
card, and a reader that handles only the ASCII codes returns an empty mesh for
those files without raising anything.

This package reads and writes all four, and can convert between them without
going through a mesh at all.
"""

from pathlib import Path
import tempfile

import matplotlib.pyplot as plt

import pyvista_frd

# Sphinx-Gallery runs each example from its own directory; the decks and
# their solved output live one level up, in ``doc/_data``.
DATA = Path('../_data').resolve()
tmp = Path(tempfile.mkdtemp())

# %%
# :func:`pyvista_frd.convert` reads a document and writes it out again in
# another encoding. Nothing is re-derived: the records are re-spelled and every
# line the parser does not need to understand is copied through untouched.

source = DATA / 'cantilever.frd'
sizes = {'long ASCII (source)': source.stat().st_size}

for label, kwargs in (
    ('binary float64', {'binary': True}),
    ('long ASCII', {'binary': False}),
):
    target = tmp / f'{label.replace(" ", "_")}.frd'
    pyvista_frd.convert(source, target, **kwargs)
    sizes[label] = target.stat().st_size

for label, size in sizes.items():
    print(f'{label:22s} {size / 1024:8.0f} KB')

# %%
# Binary is about a third of the size, and exact: the values are the stored
# doubles rather than a six-significant-digit rendering of them.

fig, ax = plt.subplots(figsize=(6, 3))
ax.barh(list(sizes), [v / 1024 for v in sizes.values()], color=['#4c72b0', '#dd8452', '#55a868'])
ax.set_xlabel('KB')
ax.set_title('Same document, three encodings')
fig.tight_layout()
plt.show()

# %%
# The conversion is lossless in the direction that matters and the mesh is
# unchanged either way.

original = pyvista_frd.read(source)
converted = pyvista_frd.read(tmp / 'binary_float64.frd')
print(f'points  {original.n_points} -> {converted.n_points}')
print(f'cells   {original.n_cells} -> {converted.n_cells}')
print(f'arrays  {len(original.point_data)} -> {len(converted.point_data)}')

# %%
# Going the other way -- binary to ASCII -- is the conversion the format code
# has always implied and no tool offered. A binary FRD that no ASCII-only
# reader can open becomes one any of them can, including CalculiX's own.
#
# One caveat, recorded in ``doc/divergences.md``: CalculiX casts every value to
# ``float`` before printing it, and this writer does not. The text it produces
# is the nearest six-digit decimal to the number actually held, which differs
# from CalculiX's own at a rounding tie -- about 3% of record lines.
