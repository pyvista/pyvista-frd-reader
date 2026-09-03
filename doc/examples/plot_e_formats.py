""".. _formats_example:

The four encodings
==================

FRD defines two ASCII and two binary encodings. CalculiX writes binary output
for ``*REFINE MESH`` and ``DOUBLE`` output cards.

The reader handles all four encodings. The writer creates long ASCII and both
binary encodings; the converter also preserves existing short ASCII records.
"""

from pathlib import Path
import tempfile

import matplotlib.pyplot as plt

import pyvista_frd

# Sphinx-Gallery runs this file from ``doc/examples``.
DATA = Path('../_data').resolve()
tmp = Path(tempfile.mkdtemp())

# %%
# :func:`pyvista_frd.convert` changes record encoding and preserves lines that
# the parser does not need to interpret.

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
# Compare file sizes. Binary keeps the stored doubles; ASCII writes six
# significant digits.

fig, ax = plt.subplots(figsize=(6, 3))
ax.barh(list(sizes), [v / 1024 for v in sizes.values()], color=['#4c72b0', '#dd8452', '#55a868'])
ax.set_xlabel('KB')
ax.set_title('Same document, three encodings')
fig.tight_layout()
plt.show()

# %%
# Confirm that the converted file has the same mesh structure.

original = pyvista_frd.read(source)
converted = pyvista_frd.read(tmp / 'binary_float64.frd')
print(f'points  {original.n_points} -> {converted.n_points}')
print(f'cells   {original.n_cells} -> {converted.n_cells}')
print(f'arrays  {len(original.point_data)} -> {len(converted.point_data)}')

# %%
# Binary-to-ASCII conversion creates a file that ASCII-only readers can open.
# CalculiX formats ASCII after casting to ``float32``; this writer formats its
# stored ``float64`` value. The final digit can differ at a rounding tie.
