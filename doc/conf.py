"""Sphinx configuration for the pyvista-frd-reader documentation.

The source directory is ``doc/`` itself rather than ``doc/source/``. The
Markdown files here predate the docs build, are linked from ``README.rst`` by
their repository paths, and are meant to stay readable on GitHub; moving them
under a ``source/`` directory would break those links for a layout preference.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

import pyvista

# -- Project ----------------------------------------------------------------

project = 'pyvista-frd-reader'
author = 'The PyVista developers'
copyright = f'{datetime.date.today().year}, {author}'  # noqa: A001, DTZ011

try:
    from pyvista_frd import __version__ as release
except ImportError:  # pragma: no cover - docs can build without the native core
    release = '0.0.0.dev0'
version = release

# -- General ----------------------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.extlinks',
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx_copybutton',
    'sphinx_design',
    'sphinx_gallery.gen_gallery',
    'myst_parser',
]

# releasing.md is maintainer-facing and lives in the repository, not the site.
exclude_patterns = [
    '_build',
    'Thumbs.db',
    '.DS_Store',
    'examples/README.rst',
    'releasing.md',
    '_data',
]
templates_path = ['_templates']
source_suffix = {'.rst': 'restructuredtext', '.md': 'markdown'}

# Every warning is an error. A docs build that reports a broken reference and
# then exits zero is a build nobody reads the output of.
nitpicky = False
suppress_warnings = ['config.cache']

myst_enable_extensions = ['colon_fence', 'deflist', 'linkify', 'substitution']
myst_heading_anchors = 3

extlinks = {
    'pr': ('https://github.com/pyvista/pyvista/pull/%s', 'pyvista#%s'),
    'issue': ('https://github.com/pyvista/pyvista/issues/%s', 'pyvista#%s'),
}

intersphinx_mapping = {
    'numpy': ('https://numpy.org/doc/stable/', None),
    'python': ('https://docs.python.org/3/', None),
    'pyvista': ('https://docs.pyvista.org/', None),
}

autodoc_default_options = {'members': True, 'member-order': 'bysource'}
autodoc_typehints = 'description'
napoleon_google_docstring = False
napoleon_numpy_docstring = True

# -- HTML -------------------------------------------------------------------

html_theme = 'pydata_sphinx_theme'
html_static_path = ['_static']
# GitHub Pages serves the custom domain from a CNAME file at the site root.
# _static is copied verbatim, so the file has to be lifted out of it; see the
# ``setup`` hook at the bottom.
html_extra_path: list[str] = []
html_css_files = ['custom.css']
html_title = 'pyvista-frd-reader'
html_favicon = '_static/favicon.svg'
html_show_sourcelink = False
html_baseurl = 'https://frd-reader.pyvista.org'

html_theme_options = {
    'github_url': 'https://github.com/pyvista/pyvista-frd-reader',
    'navbar_align': 'content',
    'show_prev_next': True,
    'show_toc_level': 2,
    'use_edit_page_button': True,
    'icon_links': [
        {
            'name': 'PyPI',
            'url': 'https://pypi.org/project/pyvista-frd-reader/',
            'icon': 'fa-solid fa-box',
        },
        {
            'name': 'PyVista',
            'url': 'https://docs.pyvista.org/',
            'icon': 'fa-solid fa-cube',
        },
    ],
    'logo': {'text': 'pyvista-frd-reader'},
}

html_context = {
    'github_user': 'pyvista',
    'github_repo': 'pyvista-frd-reader',
    'github_version': 'main',
    'doc_path': 'doc',
    'default_mode': 'light',
}

# -- Gallery ----------------------------------------------------------------

pyvista.OFF_SCREEN = True
pyvista.BUILDING_GALLERY = True
pyvista.set_plot_theme('document')
pyvista.global_theme.window_size = [900, 600]
pyvista.global_theme.font.size = 18
pyvista.global_theme.anti_aliasing = 'fxaa'

os.environ.setdefault('PYVISTA_BUILDING_GALLERY', 'true')

sphinx_gallery_conf = {
    'examples_dirs': ['examples'],
    'gallery_dirs': ['gallery'],
    'filename_pattern': r'.*\.py',
    'image_scrapers': (pyvista.plotting.utilities.sphinx_gallery.DynamicScraper(), 'matplotlib'),
    'first_notebook_cell': '%matplotlib inline',
    'doc_module': ('pyvista_frd', 'pyvista'),
    'remove_config_comments': True,
    'download_all_examples': False,
    'within_subsection_order': 'FileNameSortKey',
    'reference_url': {'pyvista_frd': None},
    'thumbnail_size': (450, 300),
}


def _write_cname(app, exception) -> None:  # noqa: ANN001
    """Put CNAME at the site root, which is where GitHub Pages reads it."""
    if exception is not None or app.builder.name != 'html':
        return
    (Path(app.outdir) / 'CNAME').write_text('frd-reader.pyvista.org\n')
    # No Jekyll: it would drop every directory beginning with an underscore,
    # which is _static, _images and _downloads.
    (Path(app.outdir) / '.nojekyll').write_text('')


def setup(app):  # noqa: ANN001, ANN201
    """Register the build hooks."""
    app.connect('build-finished', _write_cname)
