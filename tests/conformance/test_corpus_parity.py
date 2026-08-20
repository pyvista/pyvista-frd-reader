"""Grade the C++ core against PyVista's reader, file by file and array by array.

This is the suite that makes the port safe. Everything else here tests a
piece; this tests the claim: *the same bytes produce the same arrays*.

Two standards of agreement are used, and which one applies to which array is
not a matter of taste:

- **Bit-exact** for points, connectivity, node ids, every array read off the
  file, and the two von Mises arrays. These are parsing and closed-form
  arithmetic. If they are not identical, something is wrong -- a tolerance
  here would hide a mis-parsed exponent as easily as a rounding difference.
- **A stated band** for the principal values, which come from an eigensolver.
  The reference uses LAPACK; this uses Jacobi. The band is on the absolute
  difference scaled by the *tensor's* magnitude, not by the eigenvalue's,
  because an eigenvalue near zero has no relative accuracy to speak of and a
  relative test on it measures nothing but noise. See doc/divergences.md.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np
import pytest
import pyvista as pv

from pyvista_frd import _capi
from pyvista_frd.reader import _default_wedge_order

from .ref_frd import _FRDParser

if TYPE_CHECKING:
    from pathlib import Path

from tests.conftest import UNREADABLE

# Eigenvalue agreement, expressed against the magnitude of the tensor the
# eigenvalues came from. Backward stability gives an error of order
# eps * ||A||; the constant is the headroom over that, and the measured
# maximum across the whole corpus is printed on failure so a red says which
# it was.
EIGEN_TOLERANCE_ULPS = 32.0
_EPS = float(np.finfo(np.float64).eps)


def _oracle(path: Path):
    """Parse with the vendored PyVista reader."""
    return _FRDParser(str(path)).parse()


def _native(path: Path) -> _capi.NativeFile:
    """Open with the C++ core, ordering wedges the way this VTK expects."""
    return _capi.NativeFile(str(path), wedge_order=_default_wedge_order())


def _is_principal(name: str) -> bool:
    return bool(re.search(r'_PS[123]$', name))


def _tensor_scale(grid, name: str) -> np.ndarray:
    """Row-wise magnitude of the tensor a principal array was derived from."""
    base = name.rsplit('_', 1)[0]
    tensor = np.asarray(grid.point_data[base], dtype=np.float64)
    return np.linalg.norm(tensor, axis=1)


def test_corpus_is_not_empty():
    """A parity sweep over nothing passes. Make that state impossible.

    Deliberately not a lower bound of 1: the corpus is the instrument, and a
    number here that drifts below what the fixtures directory holds would be
    the kind of silent shrinkage the rest of this file cannot see.
    """
    from tests.conftest import corpus

    assert len(corpus()) >= 31, 'the fixture corpus has shrunk'


def test_mesh_matches_reference(fixture_path: Path):
    """Points, node ids and cells must be identical, not close."""
    if fixture_path.name in UNREADABLE:
        pytest.skip(f'{fixture_path.name}: {UNREADABLE[fixture_path.name]}')

    data = _oracle(fixture_path)
    grid = _FRDParser._build_grid(data, {})
    native = _native(fixture_path)

    assert native.n_points == grid.n_points
    assert native.n_cells == grid.n_cells
    np.testing.assert_array_equal(native.points, np.asarray(grid.points, dtype=np.float64))
    np.testing.assert_array_equal(native.cell_types, grid.celltypes)
    np.testing.assert_array_equal(native.cell_offsets, grid.offset)
    np.testing.assert_array_equal(native.cell_connectivity, grid.cell_connectivity)

    # The reference stores node ids as strings; the ABI hands out integers and
    # the Python layer does the rendering. Compare what the grid would hold.
    expected = np.asarray(grid.point_data['original_node_ids'])
    np.testing.assert_array_equal(np.array([str(i) for i in native.node_ids]), expected)


def test_time_steps_match_reference(fixture_path: Path):
    """Step times, and the order they come in."""
    if fixture_path.name in UNREADABLE:
        pytest.skip(f'{fixture_path.name}: {UNREADABLE[fixture_path.name]}')

    data = _oracle(fixture_path)
    native = _native(fixture_path)
    assert native.step_times == sorted(data.results_by_step)


def test_arrays_match_reference(fixture_path: Path):
    """Every array of every step: names, order, shapes and values."""
    if fixture_path.name in UNREADABLE:
        pytest.skip(f'{fixture_path.name}: {UNREADABLE[fixture_path.name]}')

    data = _oracle(fixture_path)
    native = _native(fixture_path)
    worst_eigen = 0.0

    for step_index, step_time in enumerate(sorted(data.results_by_step)):
        grid = _FRDParser._build_grid(data, data.results_by_step[step_time])
        expected_names = [n for n in grid.point_data if n != 'original_node_ids']
        got = native.array_infos(step_index)

        assert [name for name, _, _ in got] == expected_names, (
            f'step {step_time}: array names or their order differ'
        )

        for index, (name, n_components, _kind) in enumerate(got):
            reference = np.asarray(grid.point_data[name], dtype=np.float64)
            actual = native.array(step_index, index)
            assert actual.shape == reference.shape, f'{name}: shape'
            expected_components = 1 if reference.ndim == 1 else reference.shape[1]
            assert n_components == expected_components, f'{name}: component count'

            if not _is_principal(name):
                np.testing.assert_array_equal(
                    actual, reference, err_msg=f'{name} at step {step_time} is not bit-identical'
                )
                continue

            scale = _tensor_scale(grid, name)
            error = np.abs(actual - reference)
            # A zero-magnitude tensor has zero eigenvalues; both readers must
            # produce exactly that, so the scaled error stays defined.
            scaled = np.where(scale > 0.0, error / np.maximum(scale, np.finfo(float).tiny), error)
            measured = float(np.max(scaled)) / _EPS if len(scaled) else 0.0
            worst_eigen = max(worst_eigen, measured)
            assert measured <= EIGEN_TOLERANCE_ULPS, (
                f'{name} at step {step_time}: eigenvalue error {measured:.2f} ulp of the '
                f'tensor magnitude exceeds the {EIGEN_TOLERANCE_ULPS} ulp band '
                f'(max abs error {error.max():.3e}, max tensor magnitude {scale.max():.3e})'
            )

    if worst_eigen:
        # Printed, not asserted on: a margin that quietly creeps toward the
        # bound is the thing a pass/fail line cannot report.
        print(f'\n{fixture_path.name}: worst principal-value error {worst_eigen:.2f} ulp')


def test_ragged_block_is_an_error_in_both():
    """A block with mismatched component counts must fail, not half-succeed.

    The reference fails because NumPy refuses the assignment. This library
    reports PVFRD_E_RAGGED. What matters is that neither one silently stores a
    short row, which is the failure mode a reimplementation falls into.
    """
    from tests.conftest import FIXTURE_DIR

    path = FIXTURE_DIR / 'ragged.frd'

    data = _oracle(path)
    with pytest.raises(ValueError, match=r'could not broadcast|setting an array element'):
        _FRDParser._build_grid(data, data.results_by_step[1.0])

    native = _native(path)
    with pytest.raises(_capi.FRDError) as excinfo:
        native.array_infos(0)
    assert excinfo.value.status == 6
    assert 'components' in str(excinfo.value)


def test_broadcast_row_matches_numpy():
    """A one-value record fills the whole row, exactly as NumPy does.

    Copied behaviour, not chosen behaviour. It is here because a C++ author
    reading the format would write a bounds check and reject the record, and
    then this library and PyVista would disagree about a file both can read.
    """
    from tests.conftest import FIXTURE_DIR

    path = FIXTURE_DIR / 'broadcast.frd'
    data = _oracle(path)
    grid = _FRDParser._build_grid(data, data.results_by_step[1.0])
    native = _native(path)

    reference = np.asarray(grid.point_data['STRESS'], dtype=np.float64)
    actual = native.array(0, 0)
    np.testing.assert_array_equal(actual, reference)
    # The row that carried one value: every component is that value.
    np.testing.assert_array_equal(actual[1], np.full(6, 7.0))


def test_newline_variants_read_identically():
    """LF, CRLF and a lone CR are the same document.

    Python's text mode normalises all three; a C++ reader that splits on '\\n'
    alone puts a CR-terminated file on one line and finds nothing in it. This
    compares the native reader against itself across the three encodings, so
    it stays a real check even if the oracle were ever to change.
    """
    from tests.conftest import FIXTURE_DIR

    base = _native(FIXTURE_DIR / 'mock.frd')
    for variant in ('mock_crlf.frd', 'mock_cr.frd'):
        other = _native(FIXTURE_DIR / variant)
        np.testing.assert_array_equal(base.points, other.points)
        np.testing.assert_array_equal(base.cell_connectivity, other.cell_connectivity)
        assert base.step_times == other.step_times
        assert base.array_infos(0) == other.array_infos(0)
        np.testing.assert_array_equal(base.array(0, 0), other.array(0, 0))


def test_open_from_memory_matches_open_from_path(fixture_path: Path):
    """The in-memory entry point is the same parser, not a second one."""
    if fixture_path.name in UNREADABLE:
        pytest.skip(f'{fixture_path.name}: {UNREADABLE[fixture_path.name]}')

    from_path = _native(fixture_path)
    from_bytes = _capi.NativeFile.from_bytes(
        fixture_path.read_bytes(), wedge_order=_default_wedge_order()
    )
    np.testing.assert_array_equal(from_path.points, from_bytes.points)
    np.testing.assert_array_equal(from_path.cell_connectivity, from_bytes.cell_connectivity)
    assert from_path.step_times == from_bytes.step_times
    assert from_path.diagnostics == from_bytes.diagnostics


def test_wedge_order_option_actually_changes_the_wedge():
    """The PE6 option must do something, and only to PE6.

    Without this the option could be wired to nothing and every other test
    here would still pass, because they all run with whichever value the
    installed VTK selects.
    """
    from tests.conftest import FIXTURE_DIR

    path = FIXTURE_DIR / 'elements' / 'PE6.frd'
    asis = _capi.NativeFile(str(path), wedge_order=_capi.WEDGE_ASIS)
    swapped = _capi.NativeFile(str(path), wedge_order=_capi.WEDGE_SWAP)

    a = asis.cell_connectivity
    b = swapped.cell_connectivity
    assert not np.array_equal(a, b), 'the wedge order option changed nothing'
    np.testing.assert_array_equal(b, a[[0, 2, 1, 3, 5, 4]])

    # A tetrahedron is untouched by either setting.
    tet = FIXTURE_DIR / 'elements' / 'TE4.frd'
    np.testing.assert_array_equal(
        _capi.NativeFile(str(tet), wedge_order=_capi.WEDGE_ASIS).cell_connectivity,
        _capi.NativeFile(str(tet), wedge_order=_capi.WEDGE_SWAP).cell_connectivity,
    )


def test_vtk_version_decides_the_default_wedge_order():
    """The default follows the installed VTK, and nothing else."""
    expected = _capi.WEDGE_SWAP if pv.vtk_version_info < (9, 7) else _capi.WEDGE_ASIS
    assert _default_wedge_order() == expected
