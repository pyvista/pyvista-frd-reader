"""Surface connectivity, orientation and results checked independently of VTK face indices."""

import numpy as np
import pytest
import pyvista as pv

import pyvista_frd
from pyvista_frd import FRDReader
from pyvista_frd import _capi
from tests.conftest import FIXTURE_DIR

# Original node IDs from the authored input decks, using the CCX *SURFACE
# face definitions and the documented midside edges of each element.
FACES = {
    'hex8': [(1, 2, 3, 4), (5, 6, 7, 8), (1, 2, 5, 6), (2, 3, 6, 7), (3, 4, 7, 8), (1, 4, 5, 8)],
    'hex20': [
        (1, 2, 3, 4, 9, 10, 11, 12),
        (5, 6, 7, 8, 13, 14, 15, 16),
        (1, 2, 5, 6, 9, 13, 17, 18),
        (2, 3, 6, 7, 10, 14, 18, 19),
        (3, 4, 7, 8, 11, 15, 19, 20),
        (1, 4, 5, 8, 12, 16, 17, 20),
    ],
    'tet4': [(1, 2, 3), (1, 2, 4), (2, 3, 4), (1, 3, 4)],
    'tet10': [(1, 2, 3, 5, 6, 7), (1, 2, 4, 5, 8, 9), (2, 3, 4, 6, 9, 10), (1, 3, 4, 7, 8, 10)],
    'wedge6': [(1, 2, 3), (4, 5, 6), (1, 2, 4, 5), (2, 3, 5, 6), (1, 3, 4, 6)],
    'wedge15': [
        (1, 2, 3, 7, 8, 9),
        (4, 5, 6, 10, 11, 12),
        (1, 2, 4, 5, 7, 10, 13, 14),
        (2, 3, 5, 6, 8, 11, 14, 15),
        (1, 3, 4, 6, 9, 12, 13, 15),
    ],
}


def reader_for(tmp_path, stem, surface_text, fmt=None):
    source = FIXTURE_DIR / 'generated' / f'{stem}.frd'
    inp = tmp_path / 'surface.inp'
    inp.write_text((source.parent / 'src' / f'{stem}.inp').read_text() + surface_text)
    if fmt is not None:
        target = tmp_path / 'encoded.frd'
        target.write_bytes(_capi.rewrite_bytes(source.read_bytes(), fmt))
        source = target
    return FRDReader(source, inp_path=inp)


@pytest.mark.parametrize('stem', list(FACES))
@pytest.mark.parametrize(
    'fmt',
    [
        _capi.FORMAT_SHORT_ASCII,
        _capi.FORMAT_LONG_ASCII,
        _capi.FORMAT_BINARY_FLOAT,
        _capi.FORMAT_BINARY_DOUBLE,
    ],
)
def test_every_solid_face_in_all_encodings(tmp_path, stem, fmt):
    definitions = ''.join(
        f'*SURFACE,NAME=Face{i}\n1,S{i}\n' for i in range(1, len(FACES[stem]) + 1)
    )
    reader = reader_for(tmp_path, stem, definitions, fmt)
    mesh = reader.read()
    original = {int(nid): i for i, nid in enumerate(mesh['original_node_ids'])}
    for i, expected in enumerate(FACES[stem], 1):
        face = reader.read_surface(f'face{i}')
        assert face.n_cells == 1
        assert set(face['original_node_ids'].astype(int)) == set(expected)
        assert face.n_points == len(expected)
        assert face['surface_face_labels'].tolist() == [f'S{i}']
        assert face['original_element_ids'].tolist() == [1]
        # Positive orientation is a separate geometric assertion, not a
        # restatement of the unordered connectivity table above.
        corners = face.get_cell(0).points[:3]
        normal = np.cross(corners[1] - corners[0], corners[2] - corners[0])
        assert np.dot(normal, face.points.mean(axis=0) - mesh.points.mean(axis=0)) > 0
        selected = [original[int(nid)] for nid in face['original_node_ids']]
        for name in mesh.point_data:
            np.testing.assert_array_equal(face.point_data[name], mesh.point_data[name][selected])
    assert list(reader.read_surfaces().keys()) == reader.surface_names


def test_surface_membership_parsing_and_includes(tmp_path):
    path = tmp_path / 'model.inp'
    path.write_text("""*NODE,NSET=N
3,0,0,0
8,1,0,0
*ELEMENT,TYPE=C3D8,ELSET=E
90,1,2,3,4,5,6,7,8
*SURFACE,NAME=Wall
E,S1
*INCLUDE,INPUT=more.inc
*ELSET,ELSET=E
100
*SURFACE,NAME=Points,TYPE=NODE
N,
""")
    (tmp_path / 'more.inc').write_text('*SURFACE,NAME=wall,TYPE=ELEMENT\n90,s2\n90,S1\n')
    data = pyvista_frd.read_sets(path)
    assert data.surfaces['WALL'].element_faces == ((90, 'S1'), (90, 'S2'))
    assert data.surfaces['POINTS'].node_ids == (3, 8)
    assert data.element_types == {90: 'C3D8'}


@pytest.mark.parametrize(
    ('stem', 'count'),
    [('tri3', 5), ('tri6', 5), ('quad4', 6), ('quad8', 6), ('beam2', 4), ('beam3', 4)],
)
def test_calculix_expanded_shells_and_beams(tmp_path, stem, count):
    labels = (
        ['S1', 'S2', 'S3', 'S5']
        if stem.startswith('beam')
        else [f'S{i}' for i in range(1, count + 1)]
    )
    definitions = ''.join(f'*SURFACE,NAME={label}\n1,{label}\n' for label in labels)
    reader = reader_for(tmp_path, stem, definitions)
    for label in labels:
        surface = reader.read_surface(label)
        assert surface.n_cells == 1
        assert surface.n_points in {3, 4, 6, 8}
        assert surface.get_cell(0).dimension == 2
        assert 'DISP' in surface.point_data
    if not stem.startswith('beam'):
        lower = reader.read_surface('S1')
        upper = reader.read_surface('S2')
        assert np.max(lower.points[:, 2]) < np.min(upper.points[:, 2])


@pytest.mark.parametrize(
    ('cell', 'source_type', 'edge', 'expected'),
    [
        ('TR3', 'CPE3', 'S2', {2, 3}),
        ('TR6', 'CPS6', 'S3', {1, 3, 6}),
        ('QU4', 'CAX4', 'S4', {1, 4}),
        ('QU8', 'CPS8', 'S1', {1, 2, 5}),
        ('TR6', 'S6', 'S3', {1, 2, 4}),
        ('QU8', 'S8R', 'S6', {1, 4, 8}),
    ],
)
def test_unexpanded_2d_edges(tmp_path, cell, source_type, edge, expected):
    inp = tmp_path / 'model.inp'
    mesh = pyvista_frd.read(FIXTURE_DIR / 'elements' / f'{cell}.frd')
    nodes = ','.join(str(i) for i in range(1, mesh.n_points + 1))
    inp.write_text(f'*ELEMENT,TYPE={source_type}\n1,{nodes}\n*SURFACE,NAME=EDGE\n1,{edge}\n')
    reader = FRDReader(FIXTURE_DIR / 'elements' / f'{cell}.frd', inp_path=inp)
    surface = reader.read_surface('edge')
    assert surface.get_cell(0).dimension == 1
    assert set(surface['original_node_ids'].astype(int)) == expected


@pytest.mark.parametrize(
    ('cell', 'source_type', 'negative', 'positive'),
    [
        ('TR3', 'S3', 'SNEG', 'SPOS'),
        ('TR6', 'S6', 'S1', 'S2'),
        ('QU4', 'CPS4', 'SN', 'SP'),
        ('QU8', 'S8', 'SNEG', 'SPOS'),
    ],
)
def test_unexpanded_positive_and_negative_sides(tmp_path, cell, source_type, negative, positive):
    inp = tmp_path / 'model.inp'
    mesh = pyvista_frd.read(FIXTURE_DIR / 'elements' / f'{cell}.frd')
    nodes = ','.join(str(i) for i in range(1, mesh.n_points + 1))
    inp.write_text(
        f'*ELEMENT,TYPE={source_type}\n1,{nodes}\n*SURFACE,NAME=NEG\n1,{negative}\n'
        f'*SURFACE,NAME=POS\n1,{positive}\n'
    )
    reader = FRDReader(FIXTURE_DIR / 'elements' / f'{cell}.frd', inp_path=inp)
    normals = []
    for name in ['NEG', 'POS']:
        face = reader.read_surface(name)
        assert face.n_points == mesh.n_points
        a, b, c = face.get_cell(0).points[:3]
        normals.append(np.cross(b - a, c - a))
    np.testing.assert_allclose(normals[0], -normals[1])
    assert normals[0][2] < 0 < normals[1][2]


def test_nodal_surface_and_missing_ids(tmp_path):
    reader = reader_for(tmp_path, 'hex8', '*SURFACE,NAME=N,TYPE=NODE\n1\n3\n999\n')
    with pytest.raises(ValueError, match='absent'):
        reader.read_surface('N')
    with pytest.warns(UserWarning, match='absent'):
        cloud = reader.read_surface('N', missing='warn')
    assert cloud['original_node_ids'].tolist() == [1, 3]
    assert cloud.celltypes.tolist() == [pv.CellType.VERTEX] * 2
    assert cloud.field_data['missing_node_ids'].tolist() == [999]
    assert 'DISP' in cloud.point_data


def test_missing_elements_empty_surface_and_bad_name(tmp_path):
    reader = reader_for(tmp_path, 'hex8', '*SURFACE,NAME=A\n900,S1\n*SURFACE,NAME=EMPTY\n')
    with pytest.raises(ValueError, match='absent'):
        reader.read_surface('A')
    with pytest.warns(UserWarning, match='absent'):
        assert reader.read_surface('A', missing='warn').n_cells == 0
    assert reader.read_surface('EMPTY').n_cells == 0
    with pytest.raises(KeyError, match='available'):
        reader.read_surface('unknown')
    with pytest.raises(ValueError, match='missing must'):
        reader.read_surface('EMPTY', missing='ignore')


@pytest.mark.parametrize(
    'definition',
    [
        '*SURFACE\n1,S1\n',
        '*SURFACE,NAME=A,TYPE=SEGMENTS\n',
        '*SURFACE,NAME=A\n1\n',
        '*SURFACE,NAME=A\n1,S9\n',
        '*SURFACE,NAME=A,COMBINE=UNION\nB,C\n',
        '*SURFACE,NAME=A\nUNDEFINED,S1\n',
    ],
)
def test_invalid_surface_definitions_report_line(tmp_path, definition):
    inp = tmp_path / 'invalid.inp'
    inp.write_text(definition)
    with pytest.raises(ValueError, match=r'invalid\.inp:'):
        pyvista_frd.read_sets(inp)


def test_time_steps_and_independent_result_buffers(tmp_path):
    inp = tmp_path / 'mock.inp'
    inp.write_text('*SURFACE,NAME=A\n1,S1\n')
    reader = FRDReader(FIXTURE_DIR / 'mock.frd', inp_path=inp)
    for step in range(reader.number_time_points):
        reader.set_active_time_point(step)
        face = reader.read_surface('A')
        mesh = reader.read()
        index = {str(n): i for i, n in enumerate(mesh['original_node_ids'])}
        selected = [index[str(n)] for n in face['original_node_ids']]
        for name in mesh.point_data:
            np.testing.assert_array_equal(face.point_data[name], mesh.point_data[name][selected])
    original = reader.read_surface('A').points.copy()
    face.points[:] = 0
    np.testing.assert_array_equal(reader.read_surface('A').points, original)


def test_node_and_element_surfaces_can_share_a_name(tmp_path):
    reader = reader_for(
        tmp_path,
        'hex8',
        '*SURFACE,NAME=A,TYPE=NODE\n1\n*SURFACE,NAME=A\n1,S1\n*SURFACE,NAME=A,TYPE=NODE\n2\n',
    )
    assert reader.surface_names == ['NODE:A', 'ELEMENT:A']
    assert reader.read_surface('NODE:A').n_points == 2
    assert reader.read_surface('ELEMENT:A').n_cells == 1
    with pytest.raises(KeyError, match='available'):
        reader.read_surface('A')


def test_unknown_user_planar_element_allows_only_explicit_side_labels(tmp_path):
    inp = tmp_path / 'user.inp'
    inp.write_text('*ELEMENT,TYPE=US3\n1,1,2,3\n*SURFACE,NAME=A\n1,SPOS\n*SURFACE,NAME=B\n1,S1\n')
    reader = FRDReader(FIXTURE_DIR / 'elements' / 'TR3.frd', inp_path=inp)
    assert reader.read_surface('A').n_points == 3
    with pytest.raises(ValueError, match='unsupported input element'):
        reader.read_surface('B')


def test_expanded_triangle_does_not_accept_a_fourth_edge(tmp_path):
    reader = reader_for(tmp_path, 'tri3', '*SURFACE,NAME=A\n1,S6\n')
    with pytest.raises(ValueError, match='invalid for S3'):
        reader.read_surface('A')


def test_mismatched_input_solid_type_is_rejected(tmp_path):
    reader = reader_for(tmp_path, 'hex8', '*SURFACE,NAME=A\n1,S1\n')
    reader.sets.element_types[1] = 'C3D4'
    with pytest.raises(ValueError, match='does not match'):
        reader.read_surface('A')


@pytest.mark.parametrize('stem', ['tri3', 'tri6', 'quad4', 'quad8'])
@pytest.mark.parametrize('prefix', ['CPS', 'CPE', 'CAX'])
def test_expanded_plane_edges_keep_the_corresponding_solid_face(tmp_path, stem, prefix):
    # Reuse the checked-in expanded geometry, changing only the input face
    # convention. A plane edge is the same solid side as shell face n + 2.
    corners = 3 if stem.startswith('tri') else 4
    definitions = ''.join(f'*SURFACE,NAME=E{i}\n1,S{i}\n' for i in range(1, corners + 1))
    reader = reader_for(tmp_path, stem, definitions)
    size = int(''.join(c for c in stem if c.isdigit()))
    expected = {}
    for i in range(1, corners + 1):
        reader.sets.surfaces['SIDE'] = pyvista_frd.INPSurface(
            'ELEMENT', element_faces=((1, f'S{i + 2}'),)
        )
        expected[i] = reader.read_surface('SIDE')
    reader.sets.element_types[1] = f'{prefix}{size}'
    for i in range(1, corners + 1):
        actual = reader.read_surface(f'E{i}')
        np.testing.assert_array_equal(actual['original_node_ids'], expected[i]['original_node_ids'])
        np.testing.assert_array_equal(actual.cells, expected[i].cells)
        assert actual.get_cell(0).dimension == 2


@pytest.mark.parametrize('stem', ['cantilever', 'modes'])
def test_gallery_companions_have_exact_named_geometry(stem):
    data = FIXTURE_DIR.parents[1] / 'doc' / '_data'
    reader = FRDReader(data / f'{stem}.frd', inp_path=data / f'{stem}-surfaces.inp')
    expected = {
        'TOP': (120, 2, 20),
        'TIP': (25, 0, 150),
        'MIDSPAN': (25, 0, 75),
        'CLAMP': (36, 0, 0),
    }
    for name, (count, axis, coordinate) in expected.items():
        surface = reader.read_surface(name)
        assert surface.n_cells == count
        np.testing.assert_allclose(surface.points[:, axis], coordinate)
