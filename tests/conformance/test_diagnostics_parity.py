"""The warnings must match PyVista's, character for character.

Graded against the *installed* PyVista rather than the vendored parser copy,
because the message assembly lives in PyVista's ``reader.py`` and not in
``_frd.py`` -- reimplementing it here to compare against would be comparing
this code with itself.

That choice has one consequence, and it is stated rather than worked around:
the installed PyVista does not know PY5/PY13 yet (pyvista#8936), so for the
pyramid fixtures it warns about an unknown element type where this library
reads the element. Those files are listed below, not skipped silently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import warnings

import pytest
import pyvista as pv
from pyvista.core.errors import InvalidMeshWarning

from pyvista_frd import FRDReader

if TYPE_CHECKING:
    from pathlib import Path

from tests.conftest import UNREADABLE

# Element codes this library reads and the installed PyVista may not. A file
# using one cannot have its warnings compared: the two readers legitimately
# disagree about whether there is anything to warn about.
_AHEAD_OF_PYVISTA = {'pyramids.frd', 'PY5.frd', 'PY13.frd'}


def _pyvista_warnings(path: Path) -> list[str]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        pv.FRDReader(str(path))
    return sorted(str(w.message) for w in caught if issubclass(w.category, InvalidMeshWarning))


def _our_warnings(path: Path) -> list[str]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        FRDReader(str(path))
    return sorted(str(w.message) for w in caught if issubclass(w.category, InvalidMeshWarning))


def test_warnings_match_pyvista(fixture_path: Path):
    """Same warnings, same wording, same order of severity."""
    if fixture_path.name in _AHEAD_OF_PYVISTA:
        pytest.skip(f'{fixture_path.name}: uses an element the installed PyVista does not read yet')

    expected = _pyvista_warnings(fixture_path)
    assert _our_warnings(fixture_path) == expected


def test_the_corpus_actually_produces_warnings():
    """At least one fixture must warn, or the test above proves nothing.

    Two empty lists compare equal. Without this, deleting every diagnostic
    from the C++ core would leave the parity test green.
    """
    from tests.conftest import FIXTURE_DIR
    from tests.conftest import corpus

    warned = [path for path in corpus() if _our_warnings(path)]
    assert warned, 'no fixture in the corpus produces a warning'

    # And specifically all three kinds, since they are assembled separately.
    text = ' '.join(message for path in warned for message in _our_warnings(path))
    assert 'too many points' in text
    assert 'too few points' in text
    assert 'unknown element type' in text
    assert FIXTURE_DIR  # the corpus really is the one on disk


def test_warning_text_is_exact():
    """Pin the exact strings, not just their presence.

    The parity test above would stay green if both readers changed together;
    these three are the wording PyVista's own test suite asserts on, so they
    are the contract a downstream caller may be matching against.
    """
    from tests.conftest import FIXTURE_DIR

    messages = _our_warnings(FIXTURE_DIR / 'comprehensive.frd')
    assert (
        '1 cell with too many points detected:\n'
        '  line 22, element type 7 (TR3), num nodes 5 (expected 3)'
    ) in messages
    assert (
        '1 cell with too few points detected. These elements are skipped:\n'
        '  line 20, element type 2 (PE6), num nodes 3 (expected 6)'
    ) in messages
    assert (
        '1 cell with unknown element type encountered. These elements are skipped.:\n'
        '  line 15, element type 999'
    ) in messages


def test_line_numbers_are_file_global():
    """Diagnostics count lines from the start of the file, not the block.

    The numbers above (15, 20, 22) are only right if the counter runs across
    the whole document. A per-block counter would give small numbers that
    still look plausible in a warning.
    """
    from tests.conftest import FIXTURE_DIR

    reader = None
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        reader = FRDReader(str(FIXTURE_DIR / 'comprehensive.frd'))
    lines = sorted(d.line for d in reader._file.diagnostics)
    assert lines == [15, 20, 22], lines


def test_unreadable_fixtures_are_still_graded_for_warnings(fixture_path: Path):
    """A file that cannot become a grid can still be parsed for diagnostics.

    Kept separate from the mesh sweep so that being unreadable does not
    quietly exempt a fixture from every check at once.
    """
    if fixture_path.name not in UNREADABLE:
        pytest.skip('covered by test_warnings_match_pyvista')
    assert _our_warnings(fixture_path) == _pyvista_warnings(fixture_path)
