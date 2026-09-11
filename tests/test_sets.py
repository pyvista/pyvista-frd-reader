"""Input-deck memberships, with independently specified IDs and mesh indices."""

import numpy as np
import pytest
import pyvista as pv
from pyvista.core.errors import InvalidMeshWarning

import pyvista_frd
from pyvista_frd import _capi
from pyvista_frd import read_sets
from tests.conftest import FIXTURE_DIR


def deck(tmp_path, text):
    path = tmp_path / 'model.inp'
    path.write_text(text, encoding='utf-8')
    return path


def test_explicit_generated_reopened_and_referenced_sets(tmp_path):
    path = deck(
        tmp_path,
        """** membership is case insensitive
*NSET, NSET=Mixed
30,10,30,
*Nset, Nset=Range, Generate
2,8,2
11,12
*NSET, NSET=Copy, UNSORTED
mixed, RANGE, 99
*NSET, NSET=mixed
50
*ELSET, ELSET=Mixed, GENERATE
20,24,2
*ELSET, ELSET=Joined
mixed, 101
""",
    )
    sets = read_sets(path)
    np.testing.assert_array_equal(sets.node_sets['MIXED'], [10, 30, 50])
    np.testing.assert_array_equal(sets.node_sets['RANGE'], [2, 4, 6, 8, 11, 12])
    # A later extension of MIXED does not retroactively extend COPY.
    np.testing.assert_array_equal(sets.node_sets['COPY'], [2, 4, 6, 8, 10, 11, 12, 30, 99])
    np.testing.assert_array_equal(sets.element_sets['JOINED'], [20, 22, 24, 101])
    assert sets.element_sets['MIXED'].dtype == np.int64


def test_implicit_sets_and_element_continuations(tmp_path):
    path = deck(
        tmp_path,
        """*NODE, NSET=All
30, 0, 0, 0
10, 1, 0, 0
*ELEMENT, TYPE=C3D20,
 ELSET=All
101,1,2,3,4,5,6,7,8,9,10,
** comment inside continuation
11,12,13,14,15,16,17,18,19,20
35,1,2,3,4,5,6,7,8,9,10,
11,12,13,14,15,16,17,18,19,20
*ELEMENT, TYPE=T3D2, ELSET=All
70,10,30
*ELSET, ELSET=Copy
all
""",
    )
    sets = read_sets(path)
    np.testing.assert_array_equal(sets.node_sets['ALL'], [10, 30])
    np.testing.assert_array_equal(sets.element_sets['ALL'], [35, 70, 101])
    np.testing.assert_array_equal(sets.element_sets['COPY'], [35, 70, 101])


def test_include_is_textual_and_relative_to_job_directory(tmp_path, monkeypatch):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'first.inc').write_text('*INCLUDE, INPUT="nodes, two.inc"\n30\n')
    (tmp_path / 'nodes, two.inc').write_text('10\n')
    path = deck(
        tmp_path,
        """*NSET, NSET=All
*INCLUDE, INPUT=sub/first.inc
50
*INCLUDE, INPUT="nodes, two.inc"
""",
    )
    monkeypatch.chdir(tmp_path.parent)
    np.testing.assert_array_equal(read_sets(path).node_sets['ALL'], [10, 30, 50])


@pytest.mark.parametrize('newline', ['\n', '\r\n', '\r'])
def test_comments_encoding_and_trailing_header_comma(tmp_path, newline):
    text = """** comment: \xe9
*NSET, NSET=All,
1,3,
*NSET, NSET=Other,
** comment
GENERATE
2,6,2
*NSET, NSET=Empty,
*STEP
*STATIC
1,1
"""
    path = tmp_path / 'model.inp'
    path.write_bytes(text.replace('\n', newline).encode('latin-1'))
    sets = read_sets(path)
    np.testing.assert_array_equal(sets.node_sets['ALL'], [1, 3])
    np.testing.assert_array_equal(sets.node_sets['OTHER'], [2, 4, 6])
    assert sets.node_sets['EMPTY'].size == 0


@pytest.mark.parametrize(
    ('text', 'message'),
    [
        ('*NSET\n1\n', 'requires NSET'),
        ('*ELSET,ELSET=\n1\n', 'requires ELSET'),
        ('*NODE,NSET=""\n1,0,0,0\n', 'empty'),
        ('*NSET,NSET=A\nB\n', 'undefined set'),
        ('*NSET,NSET=A\n-1\n', 'positive int64'),
        ('*NSET,NSET=A\n9223372036854775808\n', 'positive int64'),
        ('*NSET,NSET=A,GENERATE\n1\n', 'requires first'),
        ('*NSET,NSET=A,GENERATE\n1,8,0\n', 'positive int64'),
        ('*ELSET,ELSET=A,GENERATE\n8,1\n', 'ascending'),
        ('*NSET,NSET=A,ELSET=B\n', 'unsupported'),
        ('*NSET,NSET=A,INPUT=other.inp\n', 'unsupported'),
        ('*NGEN,NSET=A\n1,10\n', 'not supported'),
        ('*PART,NAME=A\n', 'namespaces'),
        ('*NSET,NSET=A,INSTANCE=B\n1\n', 'namespaces'),
        ('*INCLUDE\n', 'requires INPUT'),
    ],
)
def test_invalid_or_unsupported_deck_reports_source(tmp_path, text, message):
    path = deck(tmp_path, text)
    with pytest.raises(ValueError, match=message) as error:
        read_sets(path)
    assert f'{path}:' in str(error.value)


def test_missing_include_and_cycles(tmp_path):
    path = deck(tmp_path, '*INCLUDE,INPUT=missing.inc\n')
    with pytest.raises(FileNotFoundError, match=r'missing\.inc'):
        read_sets(path)
    path.write_text('*INCLUDE,INPUT=model.inp\n')
    with pytest.raises(ValueError, match=r'Cyclic \*INCLUDE'):
        read_sets(path)


def test_no_sets(tmp_path):
    sets = read_sets(deck(tmp_path, '*NODE\n1,0,0,0\n*STEP\n*STATIC\n'))
    assert sets.node_sets == sets.element_sets == {}


@pytest.mark.parametrize(
    'fmt',
    [
        _capi.FORMAT_SHORT_ASCII,
        _capi.FORMAT_LONG_ASCII,
        _capi.FORMAT_BINARY_FLOAT,
        _capi.FORMAT_BINARY_DOUBLE,
    ],
)
def test_original_ids_and_masks_across_encodings_and_steps(tmp_path, fmt):
    path = tmp_path / 'model.frd'
    # Node storage order, sorted node order, and element order all differ.
    with _capi.Writer(fmt) as writer:
        writer.set_nodes([[0, 0, 0], [1, 0, 0], [2, 0, 0]], [30, 10, 70])
        writer.set_cells([pv.CellType.LINE, pv.CellType.LINE], [0, 2, 4], [0, 1, 1, 2], [90, 20])
        for step in [1, 2]:
            writer.begin_step(step, float(step))
            writer.add_array('VALUE', np.array([1, 2, 3]) * step)
        path.write_bytes(writer.finish())
    inp = deck(
        tmp_path,
        """*NSET,NSET=VALUE
30,500
*ELSET,ELSET=VALUE
20,600
*NSET,NSET=Absent
1000
""",
    )
    reader = pyvista_frd.FRDReader(path, inp_path=inp)
    for step in [0, 1]:
        reader.set_active_time_point(step)
        mesh = reader.read()
        plain = pyvista_frd.read(path, time_point=step)
        np.testing.assert_array_equal(mesh['original_element_ids'], [90, 20])
        np.testing.assert_array_equal(mesh.point_data['NSET:VALUE'], [False, True, False])
        np.testing.assert_array_equal(mesh.cell_data['ELSET:VALUE'], [False, True])
        np.testing.assert_array_equal(mesh.point_data['NSET:ABSENT'], [False] * 3)
        np.testing.assert_array_equal(mesh['VALUE'], plain['VALUE'])
        assert mesh.point_data['NSET:VALUE'].dtype == bool
        assert mesh.extract_cells(mesh.cell_data['ELSET:VALUE']).n_cells == 1
        assert list(plain.cell_data) == []
    np.testing.assert_array_equal(reader.sets.node_sets['VALUE'], [30, 500])
    np.testing.assert_array_equal(reader.sets.element_sets['VALUE'], [20, 600])
    assert pyvista_frd.read(path, inp_path=inp, time_point=1).n_cells == 2


def test_skipped_cells_do_not_shift_element_membership(tmp_path):
    inp = deck(tmp_path, '*ELSET,ELSET=Kept\n8\n*ELSET,ELSET=Skipped\n4,5,6,7\n')
    with pytest.warns(InvalidMeshWarning):
        reader = pyvista_frd.FRDReader(FIXTURE_DIR / 'comprehensive.frd', inp_path=inp)
    mesh = reader.read()
    np.testing.assert_array_equal(mesh['original_element_ids'], [1, 2, 8])
    np.testing.assert_array_equal(mesh['ELSET:KEPT'], [False, False, True])
    assert not mesh['ELSET:SKIPPED'].any()


def test_set_arrays_are_independent_between_reads(tmp_path):
    inp = deck(tmp_path, '*NSET,NSET=A\n1\n')
    reader = pyvista_frd.FRDReader(FIXTURE_DIR / 'mock.frd', inp_path=inp)
    reader.read().point_data['NSET:A'][:] = False
    assert reader.read().point_data['NSET:A'].sum() == 1


def test_result_name_collision_is_reported(tmp_path):
    path = tmp_path / 'collision.frd'
    with _capi.Writer() as writer:
        writer.set_nodes([[0, 0, 0]])
        writer.begin_step(1, 1.0)
        writer.add_array('NSET:A', [42.0])
        path.write_bytes(writer.finish())
    inp = deck(tmp_path, '*NSET,NSET=A\n1\n')
    with pytest.raises(ValueError, match='conflicts with an FRD result'):
        pyvista_frd.read(path, inp_path=inp)


def test_companion_is_opt_in(tmp_path):
    path = tmp_path / 'model.frd'
    path.write_bytes((FIXTURE_DIR / 'mock.frd').read_bytes())
    deck(tmp_path, '*INCLUDE,INPUT=missing.inc\n')
    assert pyvista_frd.read(path).n_points == 8
    with pytest.raises(FileNotFoundError):
        pyvista_frd.read(path, inp_path=path.with_suffix('.inp'))


def test_element_rows_with_and_without_trailing_commas(tmp_path):
    path = deck(
        tmp_path,
        """*ELEMENT,TYPE=C3D20,ELSET=A
50,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15
16,17,18,19,20,
60,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,
16,17,18,19,20
*ELEMENT,TYPE=B31,ELSET=A
80,1,2,
90,2,3,
""",
    )
    np.testing.assert_array_equal(read_sets(path).element_sets['A'], [50, 60, 80, 90])


def test_generate_stops_at_upper_bound(tmp_path):
    sets = read_sets(deck(tmp_path, '*NSET,NSET=A,GENERATE\n1,8,2\n'))
    np.testing.assert_array_equal(sets.node_sets['A'], [1, 3, 5, 7])
