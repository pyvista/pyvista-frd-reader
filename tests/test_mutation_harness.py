"""Keep the mutation harness pointing at real code.

``tools/mutate.py`` locates each planted defect by an exact substring of a
source file. Those anchors rot: a rename, a reflow, or a clang-format pass
moves one and the mutant silently stops being applied. The sweep itself
reports that as ``STALE``, but the sweep runs weekly, and by then the anchor
has been dead for a week's worth of commits.

This runs on every change, costs a few file reads, and turns "the harness
quietly stopped testing anything" into a failure at the moment it happens.

It deliberately does *not* build or run anything: that is the sweep's job.
What it checks is that the sweep still has somewhere to aim.
"""

from __future__ import annotations

import sys

import pytest

from tests.conftest import FIXTURE_DIR

sys.path.insert(0, str(FIXTURE_DIR.parent.parent / 'tools'))

import mutate


@pytest.mark.parametrize('mutant', mutate.MUTANTS, ids=lambda m: m.name)
def test_anchor_still_exists(mutant: mutate.Mutant):
    """Each mutant's anchor must appear exactly once in its file.

    Once, not merely at least once: ``str.replace(old, new, 1)`` would take
    the first of several matches, so a duplicated anchor means the sweep is
    mutating a line nobody chose.
    """
    source = (mutate.ROOT / mutant.path).read_text()
    count = source.count(mutant.old)
    assert count == 1, (
        f'{mutant.name}: its anchor appears {count} times in {mutant.path}, expected once. '
        f'The mutation sweep cannot apply this defect.'
    )


@pytest.mark.parametrize('mutant', mutate.MUTANTS, ids=lambda m: m.name)
def test_mutant_actually_changes_the_source(mutant: mutate.Mutant):
    """A mutant whose replacement equals its anchor is a no-op.

    Which would then be reported as a survivor, sending whoever reads the
    output looking for a hole in the tests that is not there.
    """
    assert mutant.new != mutant.old, f'{mutant.name}: replacement is identical to the anchor'


def test_every_mutant_names_a_gate():
    """Each mutant records which test is supposed to catch it.

    An unnamed expectation makes "killed by something" the whole result, and
    being killed by the wrong gate is how a test that looks targeted turns out
    to be catching things by accident.
    """
    for mutant in mutate.MUTANTS:
        assert mutant.expected_catcher, f'{mutant.name} names no expected catcher'


def test_the_mutant_set_has_not_shrunk():
    """A sweep over no mutants reports success.

    The count is pinned for the same reason the corpus count is: removing a
    mutant is a decision, and it should look like one in the diff.
    """
    assert len(mutate.MUTANTS) >= 19, 'mutants have been removed from the harness'
    names = [m.name for m in mutate.MUTANTS]
    assert len(names) == len(set(names)), 'two mutants share a name'
