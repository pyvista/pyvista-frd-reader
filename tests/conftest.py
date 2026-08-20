"""Shared fixtures: the corpus, and the oracle it is graded against."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / 'fixtures'

# Fixtures that no reader can turn into a grid, and why. Listed rather than
# discovered so that a corpus file quietly becoming unreadable is a failure
# instead of a silent exclusion.
UNREADABLE = {
    'empty.frd': 'has no node block at all',
    'ragged.frd': 'one block gives two nodes different component counts',
}


def corpus() -> list[Path]:
    """Every FRD file in the corpus, in a stable order.

    Recursive, so the per-element files under ``elements/`` are graded by the
    same sweep as everything else -- a second corpus directory is a second
    thing to forget to add a file to.
    """
    return sorted(FIXTURE_DIR.rglob('*.frd'))


def corpus_ids() -> list[str]:
    return [str(path.relative_to(FIXTURE_DIR)) for path in corpus()]


@pytest.fixture(params=corpus(), ids=corpus_ids())
def fixture_path(request: pytest.FixtureRequest) -> Path:
    """One FRD file from the corpus."""
    return request.param


def pytest_report_header(config: pytest.Config) -> str:  # noqa: ARG001
    """Print the corpus size, so a shrunken corpus is visible in the log.

    A sweep over an empty corpus passes. Printing the count is the cheapest
    thing that makes that state distinguishable from a real green run.
    """
    return f'frd corpus: {len(corpus())} files under {FIXTURE_DIR}'
