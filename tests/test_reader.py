"""The PyVista-facing surface.

Every test here is PyVista's own FRD test, pointed at this reader instead. The
point is not that the assertions are novel -- it is that they are *not*: this
package claims to be a drop-in, and the incumbent's test suite is the closest
thing to a written statement of what "drop-in" means.

Cases PyVista's suite covers by reaching into parser internals are rewritten
against the public surface, and each one says so.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
import warnings

import numpy as np
import pytest
import pyvista as pv
from pyvista.core.errors import InvalidMeshWarning

import pyvista_frd
from pyvista_frd import FRDReader

if TYPE_CHECKING:
    from pathlib import Path

from tests.conftest import FIXTURE_DIR

ELEMENT_EXPECTATIONS = {
    'HE8': (pv.CellType.HEXAHEDRON, 8),
    'PE6': (pv.CellType.WEDGE, 6),
    'TE4': (pv.CellType.TETRA, 4),
    'HE20': (pv.CellType.QUADRATIC_HEXAHEDRON, 20),
    'PE15': (pv.CellType.QUADRATIC_WEDGE, 15),
    'TE10': (pv.CellType.QUADRATIC_TETRA, 10),
    'TR3': (pv.CellType.TRIANGLE, 3),
    'TR6': (pv.CellType.QUADRATIC_TRIANGLE, 6),
    'QU4': (pv.CellType.QUAD, 4),
    'QU8': (pv.CellType.QUADRATIC_QUAD, 8),
    'BE2': (pv.CellType.LINE, 2),
    'BE3': (pv.CellType.QUADRATIC_EDGE, 3),
    'PY5': (pv.CellType.PYRAMID, 5),
    'PY13': (pv.CellType.QUADRATIC_PYRAMID, 13),
}


@pytest.fixture
def mock_frd() -> Path:
    return FIXTURE_DIR / 'mock.frd'


def test_read_returns_an_unstructured_grid(mock_frd: Path):
    mesh = pyvista_frd.read(mock_frd)
    assert isinstance(mesh, pv.UnstructuredGrid)
    assert mesh.n_points == 8
    assert mesh.n_cells == 1
    assert 'original_node_ids' in mesh.point_data

    mesh = FRDReader(mock_frd).read()
    assert mesh.n_points == 8
    assert mesh.n_cells == 1


def test_time_steps(mock_frd: Path):
    reader = FRDReader(mock_frd)

    assert reader.number_time_points == 3
    assert reader.time_values == [0.1, 0.2, 0.3]
    assert reader.time_point_value(0) == 0.1
    assert reader.active_time_value == 0.1

    reader.set_active_time_point(2)
    assert reader.active_time_value == 0.3

    mesh = reader.read()
    assert 'DISP' in mesh.point_data
    assert mesh.point_data['DISP'].shape == (8, 3)


def test_set_active_time_value_requires_an_exact_match(mock_frd: Path):
    reader = FRDReader(mock_frd)

    with pytest.raises(ValueError, match='Not a valid time'):
        reader.set_active_time_value(0.18)

    reader.set_active_time_value(0.2)
    assert reader.active_time_value == 0.2

    with pytest.raises(ValueError, match='Not a valid time'):
        reader.active_time_value = 0.29

    reader.active_time_value = 0.3
    assert reader.active_time_value == 0.3


def test_time_point_out_of_range(mock_frd: Path):
    reader = FRDReader(mock_frd)
    with pytest.raises(IndexError, match='out of range'):
        reader.set_active_time_point(99)
    with pytest.raises(IndexError, match='out of range'):
        reader.set_active_time_point(-1)


def test_derived_stress(mock_frd: Path):
    reader = FRDReader(mock_frd)
    reader.set_active_time_point(0)
    mesh = reader.read()

    assert 'STRESS' in mesh.point_data
    # xx=10, yy=20, zz=30, no shear.
    expected = np.sqrt(300.0)
    np.testing.assert_allclose(mesh.point_data['STRESS_Mises'], expected)
    np.testing.assert_allclose(mesh.point_data['STRESS_sgMises'], expected)
    np.testing.assert_allclose(mesh.point_data['STRESS_PS3'], 10.0)
    np.testing.assert_allclose(mesh.point_data['STRESS_PS2'], 20.0)
    np.testing.assert_allclose(mesh.point_data['STRESS_PS1'], 30.0)


def test_derived_strain(mock_frd: Path):
    reader = FRDReader(mock_frd)
    reader.set_active_time_point(1)
    mesh = reader.read()

    assert 'STRAIN' in mesh.point_data
    expected = np.sqrt(3.0) / 15.0
    np.testing.assert_allclose(mesh.point_data['STRAIN_Mises'], expected)
    np.testing.assert_allclose(mesh.point_data['STRAIN_sgMises'], expected)
    np.testing.assert_allclose(mesh.point_data['STRAIN_PS3'], 0.1)
    np.testing.assert_allclose(mesh.point_data['STRAIN_PS2'], 0.2)
    np.testing.assert_allclose(mesh.point_data['STRAIN_PS1'], 0.3)


def test_comprehensive_file_warns_the_same_way():
    """PyVista's comprehensive case, warnings and all."""
    match1 = (
        '1 cell with too many points detected:\n'
        '  line 22, element type 7 (TR3), num nodes 5 (expected 3)'
    )
    match2 = (
        '1 cell with too few points detected. These elements are skipped:\n'
        '  line 20, element type 2 (PE6), num nodes 3 (expected 6)'
    )
    match3 = (
        '1 cell with unknown element type encountered. These elements are skipped.:\n'
        '  line 15, element type 999'
    )
    path = FIXTURE_DIR / 'comprehensive.frd'
    # Nested rather than combined: each context asserts a different warning was
    # raised, which is how PyVista's own suite states it.
    with pytest.warns(InvalidMeshWarning, match=re.escape(match1)):  # noqa: PT031, SIM117
        with pytest.warns(InvalidMeshWarning, match=re.escape(match2)):
            with pytest.warns(InvalidMeshWarning, match=re.escape(match3)):
                reader = FRDReader(path)

    mesh = reader.read()
    assert mesh.n_points == 4
    assert reader.number_time_points == 3
    assert 'STRESS_Mises' in mesh.point_data
    assert 'STRESS_sgMises' in mesh.point_data

    reader.set_active_time_point(2)
    assert 'SCALAR' in reader.read().point_data


def test_a_block_with_no_usable_records_contributes_no_array():
    """PyVista covers this by injecting an empty dict into the parser.

    Reached here through the file instead: ``comprehensive.frd`` has a block
    (``EMPTY_BLOCK``) whose records are all header lines. Going through the
    file rather than the internals means this still tests something after the
    internals change.
    """
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', InvalidMeshWarning)
        reader = FRDReader(FIXTURE_DIR / 'comprehensive.frd')
    reader.set_active_time_point(1)  # the 0.2 step, which holds only that block
    assert list(reader.read().point_data) == ['original_node_ids']


def test_no_time_steps():
    reader = FRDReader(FIXTURE_DIR / 'no_steps.frd')
    assert reader.active_time_value == 0.0
    with pytest.raises(RuntimeError, match='No time steps found'):
        reader.set_active_time_value(0.5)


def test_a_file_with_no_nodes_cannot_become_a_grid():
    reader = FRDReader(FIXTURE_DIR / 'empty.frd')
    with pytest.raises(ValueError, match='No nodes found'):
        reader.read()


@pytest.mark.parametrize('element', sorted(ELEMENT_EXPECTATIONS))
def test_element_type_and_point_count(element: str):
    mesh = FRDReader(FIXTURE_DIR / 'elements' / f'{element}.frd').read()
    expected_type, expected_points = ELEMENT_EXPECTATIONS[element]
    assert mesh.n_cells == 1
    assert mesh.celltypes[0] == expected_type
    assert mesh.get_cell(0).n_points == expected_points


@pytest.mark.parametrize('element', sorted(ELEMENT_EXPECTATIONS))
def test_element_size_is_positive(element: str):
    """Node ordering must give a positive length, area or volume.

    A permutation that is wrong but self-consistent produces a valid-looking
    cell with an inside-out winding, which no count or type check can see.
    """
    if element == 'PE15' and pv.vtk_version_info < (9, 7):
        pytest.xfail(
            'VTK bug with negative volume for quadratic wedge '
            'https://gitlab.kitware.com/vtk/vtk/-/issues/19639'
        )

    mesh = FRDReader(FIXTURE_DIR / 'elements' / f'{element}.frd').read()
    vtk_type, _ = ELEMENT_EXPECTATIONS[element]
    sizes = mesh.compute_cell_sizes().cell_data
    measure = {1: 'Length', 2: 'Area', 3: 'Volume'}[vtk_type.dimension]
    value = sizes[measure][0]
    assert value > 0.0, f'{element} gave a non-positive {measure.lower()} ({value})'


def test_pyramid_nodes_land_unpermuted():
    """PY5/PY13 need no reordering; CalculiX and VTK already agree."""
    mesh = FRDReader(FIXTURE_DIR / 'pyramids.frd').read()

    assert mesh.n_cells == 2
    assert mesh.celltypes[0] == pv.CellType.PYRAMID
    assert mesh.celltypes[1] == pv.CellType.QUADRATIC_PYRAMID

    expected_py5 = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.5, 0.5, 1.0]]
    )
    np.testing.assert_allclose(mesh.get_cell(0).points, expected_py5)

    expected_py13 = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.5, 0.5, 1.0],
            [0.5, 0.0, 0.0],
            [1.0, 0.5, 0.0],
            [0.5, 1.0, 0.0],
            [0.0, 0.5, 0.0],
            [0.25, 0.25, 0.5],
            [0.75, 0.25, 0.5],
            [0.75, 0.75, 0.5],
            [0.25, 0.75, 0.5],
        ]
    )
    np.testing.assert_allclose(mesh.get_cell(1).points, expected_py13)


def test_coverage_edge_cases():
    match = r'too few points detected'
    with pytest.warns(InvalidMeshWarning, match=match):
        reader = FRDReader(FIXTURE_DIR / 'coverage_edge_cases.frd')

    mesh = reader.read()
    node_ids = mesh.point_data['original_node_ids']
    # The node whose first coordinate would not parse was skipped.
    assert '1' not in node_ids
    assert '2' in node_ids


def test_original_node_ids_are_strings(mock_frd: Path):
    """The reference stores them as strings, and callers compare that way."""
    mesh = FRDReader(mock_frd).read()
    ids = mesh.point_data['original_node_ids']
    assert ids.dtype.kind == 'U'
    assert list(ids) == [str(i) for i in range(1, 9)]


def test_read_accepts_a_time_point(mock_frd: Path):
    assert 'STRESS' in pyvista_frd.read(mock_frd, time_point=0).point_data
    assert 'DISP' in pyvista_frd.read(mock_frd, time_point=2).point_data


def test_reading_a_real_calculix_file():
    """The one fixture no one here authored.

    Everything else in the corpus was written to exercise a branch, which
    means the corpus can only confirm what its author already thought of.
    This file came out of CalculiX 2.23.
    """
    reader = FRDReader(FIXTURE_DIR / 'mesh.frd')
    assert reader.time_values == [0.5, 1.0]

    mesh = reader.read()
    assert mesh.n_points == 190
    assert mesh.n_cells == 61
    for name in ('DISP', 'NDTEMP', 'STRESS', 'TOSTRAIN', 'FORC', 'ERROR'):
        assert name in mesh.point_data, name
    assert mesh.point_data['STRESS'].shape == (190, 6)
    assert mesh.point_data['STRESS_Mises'].shape == (190,)

    # A DISP header declaring four components while its records carry three:
    # the data decides, not the header.
    assert mesh.point_data['DISP'].shape == (190, 3)


def test_library_path_points_at_a_real_file():
    from pathlib import Path as _Path

    assert _Path(pyvista_frd.library_path()).exists()


def test_closing_twice_is_safe(mock_frd: Path):
    handle = pyvista_frd.NativeFile(str(mock_frd))
    handle.close()
    handle.close()
    with pytest.raises(ValueError, match='already been closed'):
        _ = handle.n_points


def test_native_file_is_a_context_manager(mock_frd: Path):
    with pyvista_frd.NativeFile(str(mock_frd)) as handle:
        assert handle.n_points == 8
    with pytest.raises(ValueError, match='already been closed'):
        _ = handle.n_points


def test_arrays_outlive_the_reader(mock_frd: Path):
    """A grid must not borrow memory the reader owns.

    If the arrays were views into the native buffers, this would read freed
    memory once the reader is collected -- intermittently, and only under
    memory pressure, which is the worst way to find out.
    """
    mesh = FRDReader(mock_frd).read()
    import gc

    gc.collect()
    np.testing.assert_allclose(mesh.point_data['STRESS_PS1'], 30.0)


def test_missing_file_raises():
    with pytest.raises(pyvista_frd.FRDError, match='could not be opened'):
        FRDReader(FIXTURE_DIR / 'not-here.frd')


def test_ctypes_struct_layouts_match_the_library():
    """The handwritten struct declarations must agree with the compiled ones.

    Checked at import too, but asserted here so the failure is a named test
    rather than an import error somewhere unrelated. This is the check that a
    Windows or macOS run can fail while Linux passes: nothing about the
    binding is verified by the compiler.
    """
    import ctypes

    from pyvista_frd import _capi

    for name, struct in (
        ('pvfrd_open_options', _capi._OpenOptions),
        ('pvfrd_array_info', _capi._ArrayInfo),
        ('pvfrd_diagnostic', _capi._Diagnostic),
    ):
        native = _capi._lib.pvfrd_struct_size(_capi._STRUCT_IDS[name])
        assert native == ctypes.sizeof(struct), name


def test_a_mismatched_struct_is_refused():
    """The layout check must actually reject something.

    Without this, the comparison above could be reading the same number twice
    and would agree forever.
    """
    import ctypes

    from pyvista_frd import _capi

    class _Wrong(ctypes.Structure):
        _fields_ = (('a', ctypes.c_int32),)

    original = _capi._ArrayInfo
    try:
        _capi._ArrayInfo = _Wrong
        with pytest.raises(_capi.NativeUnavailableError, match='pvfrd_array_info'):
            _capi._check_struct_layouts(_capi._lib, 'test')
    finally:
        _capi._ArrayInfo = original


def test_reading_one_step_does_not_parse_the_others(tmp_path):
    """Laziness, asserted by counting rather than by timing.

    A fixture small enough to time is a fixture small enough to sit in page
    cache, where an eager implementation looks identical. The count is what
    tells the two designs apart.
    """
    lines = ['2C', ' -1    1 0.0 0.0 0.0', ' -1    2 1.0 0.0 0.0', ' -3']
    for i in range(30):
        lines += [f'100CL {i + 1} {i + 1}.0', ' -4 ALPHA 1', f' -1    1 {i}.0', ' -3']
    path = tmp_path / 'many_steps.frd'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    handle = pyvista_frd.NativeFile(str(path))
    assert handle.n_steps == 30
    assert handle.steps_parsed == 0

    handle.array(11, 0)
    assert handle.steps_parsed == 1

    handle.array(11, 0)
    assert handle.steps_parsed == 1, 'a repeat read parsed the step again'

    handle.array(29, 0)
    assert handle.steps_parsed == 2


def test_the_reader_builds_only_the_active_step(tmp_path):
    """FRDReader.read() must not drag in every step's arrays."""
    lines = ['2C', ' -1    1 0.0 0.0 0.0', ' -1    2 1.0 0.0 0.0', ' -3']
    for i in range(12):
        lines += [f'100CL {i + 1} {i + 1}.0', ' -4 ALPHA 1', f' -1    1 {i}.0', ' -3']
    path = tmp_path / 'many_steps.frd'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    reader = FRDReader(path)
    assert reader._file.steps_parsed == 0
    reader.set_active_time_point(5)
    mesh = reader.read()
    assert mesh.point_data['ALPHA'][0] == 5.0
    assert reader._file.steps_parsed == 1
