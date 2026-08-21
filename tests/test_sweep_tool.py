"""The external sweep tool must be able to report a divergence.

``tools/sweep_external.py`` is what produced the headline in ``doc/parity.md``:
1,615 files, no divergences. That number is worth exactly as much as the tool's
ability to say the opposite, and nothing in the repository exercised that --
the corpus it is aimed at cannot live here, so every run of it that has ever
happened was a run that found nothing.

The obvious control does not work, and it is worth saying why. Corrupting a
fixture and sweeping it proves nothing: the sweep gives the *same* file to both
readers, so a bent coordinate is read identically by both and the file still
agrees with itself. What has to be perturbed is one side of the comparison.

So these tests reach into the oracle and change what it returns, which is the
only way to manufacture the disagreement the tool exists to detect.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

from tests.conftest import FIXTURE_DIR

sys.path.insert(0, 'tools')

from sweep_external import bitwise_equal
from sweep_external import compare


def test_a_clean_file_agrees():
    """The baseline. Without it, a tool that always says `differ` would pass below."""
    result = compare(FIXTURE_DIR / 'mock.frd')
    assert result.verdict == 'agree', result.differences


def test_a_perturbed_oracle_is_reported_as_a_divergence(monkeypatch):
    """Move one coordinate on the oracle's side and require the sweep to notice."""
    from tests.conformance.ref_frd import _FRDParser

    original = _FRDParser._build_grid

    def bent(data, step):
        grid = original(data, step)
        points = np.asarray(grid.points, dtype=np.float64).copy()
        points[1, 0] += 1.0
        grid.points = points
        return grid

    monkeypatch.setattr(_FRDParser, '_build_grid', staticmethod(bent))

    result = compare(FIXTURE_DIR / 'mock.frd')
    assert result.verdict == 'differ', 'the sweep did not notice a moved node'
    assert any('points' in d for d in result.differences), result.differences


def test_a_perturbed_array_is_reported_as_a_divergence(monkeypatch):
    """The same for result arrays, which take a different path through the tool."""
    from tests.conformance.ref_frd import _FRDParser

    original = _FRDParser._build_grid

    def bent(data, step):
        grid = original(data, step)
        if 'STRESS' in grid.point_data:
            values = np.asarray(grid.point_data['STRESS'], dtype=np.float64).copy()
            values[0, 0] = np.nextafter(values[0, 0], np.inf)
            grid.point_data['STRESS'] = values
        return grid

    monkeypatch.setattr(_FRDParser, '_build_grid', staticmethod(bent))

    result = compare(FIXTURE_DIR / 'mock.frd')
    assert result.verdict == 'differ', 'a one-ulp change in an array went unreported'
    assert any('STRESS' in d for d in result.differences), result.differences


def test_the_both_decline_branch_is_reached():
    """A node-free file must be recorded as agreement, not as a harness error.

    This branch is why 34 CalculiX files stopped being reported as errors, and
    it is the one place the tool is allowed to call an exception a pass -- so
    it should be exercised rather than trusted.
    """
    result = compare(FIXTURE_DIR / 'empty.frd')
    assert result.verdict == 'both-decline', result.detail


def test_a_ragged_block_is_a_refusal_by_both_not_a_harness_error():
    """Both readers reject it, deliberately not in the same words.

    PyVista's reader fails because NumPy refuses the assignment; this library
    reports PVFRD_E_RAGGED. doc/divergences.md says that difference is on
    purpose -- what matters is that neither stores a short row. The sweep has
    to model that, or a documented divergence reads as a fault in the tool.
    """
    result = compare(FIXTURE_DIR / 'ragged.frd')
    assert result.verdict == 'both-refuse', result.detail
    assert 'oracle:' in result.detail
    assert 'native:' in result.detail


@pytest.mark.parametrize(
    ('a', 'b', 'expected'),
    [
        ([1.0, 2.0], [1.0, 2.0], True),
        ([np.nan, 2.0], [np.nan, 2.0], True),
        ([np.nan, 2.0], [0.0, 2.0], False),
        ([0.0], [-0.0], False),
        ([1.0], [1.0 + 2**-52], False),
    ],
)
def test_bitwise_equal_is_strict_where_equality_is_not(a, b, expected):
    """The two cases `==` gets wrong: matching NaNs, and the sign of zero."""
    assert bitwise_equal(np.array(a), np.array(b)) is expected
