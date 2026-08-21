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


def _newest_native_source() -> tuple[Path, float] | None:
    """The most recently modified C++ source, or None outside a checkout."""
    root = Path(__file__).parent.parent
    cpp = root / 'cpp'
    if not cpp.is_dir():
        return None  # installed from a wheel; there is nothing to be stale against
    newest: tuple[Path, float] | None = None
    for pattern in ('src/**/*.cpp', 'src/**/*.h', 'include/**/*.h'):
        for path in cpp.glob(pattern):
            stamp = path.stat().st_mtime
            if newest is None or stamp > newest[1]:
                newest = (path, stamp)
    return newest


def pytest_collection_modifyitems(
    session: pytest.Session,  # noqa: ARG001
    config: pytest.Config,  # noqa: ARG001
    items: list[pytest.Item],  # noqa: ARG001
) -> None:
    """Refuse to grade a library older than the source it was built from.

    Editing C++ and running pytest does not rebuild anything: the package
    loads the copy under ``src/pyvista_frd/lib/``, which only setup.py
    refreshes. So the suite happily reports a green run against a library
    predating every change being tested, and nothing about that green is
    distinguishable from a real one.

    This is not hypothetical. It happened during this project for a whole
    afternoon: four C++ changes were made, pytest was run and reported clean
    after each, and the library it exercised was hours old. The gtest tier was
    unaffected -- it builds from source -- and so was CI, which installs
    fresh. Only the local Python tier lied, which is the tier where the lie is
    hardest to notice.

    Deliberately an error rather than a warning. A warning at the top of a
    green run is a thing people learn to scroll past.
    """
    newest = _newest_native_source()
    if newest is None:
        return
    try:
        import pyvista_frd
    except ImportError:  # pragma: no cover - the import error speaks for itself
        return

    library = Path(pyvista_frd.library_path())
    if not library.exists():  # pragma: no cover
        return
    source, source_time = newest
    library_time = library.stat().st_mtime
    if library_time >= source_time:
        return

    age = source_time - library_time
    message = (
        f'the native library is older than the C++ it should have been built from:\n'
        f'  library : {library} ({age / 60:.1f} minutes older)\n'
        f'  source  : {source}\n'
        f'Rebuild before grading, or every result below is about the wrong binary:\n'
        f'  uv pip install -e . --no-deps --no-build-isolation\n'
        f'  (or: pip install -e . --no-deps)'
    )
    raise pytest.UsageError(message)
