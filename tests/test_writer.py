"""The writer, graded against files this project did not write.

A writer can be checked two ways and only one of them is worth much. Writing a
file, reading it back with our own reader, and finding the mesh we started
with says that the two halves agree with each other -- which a matched pair of
defects satisfies exactly as well as a correct pair does. What settles it is
comparing against bytes CalculiX produced.

Three claims here, in increasing order of what they establish:

  round trip     a document read and emitted again is the input, byte for
                 byte. Over the fixtures below and, out of tree, over 1,111
                 external files including two dialects of the format.

  conversion     a binary fixture converted to ASCII equals the ASCII file
                 CalculiX wrote from the same run of the same deck, record for
                 record. Neither side of that comparison is our idea of what
                 the format looks like.

  construction   a mesh and some arrays, written from scratch, read back as
                 themselves. This is the round-trip check, and it is the weak
                 one -- what backs the constructed path is that CalculiX reads
                 those files, which is out of tree in doc/writing.md because
                 it needs a solver.
"""

from __future__ import annotations

import numpy as np
import pytest

from pyvista_frd import _capi
from tests.conftest import FIXTURE_DIR

FORMATS = [
    (_capi.FORMAT_SHORT_ASCII, 'short-ascii'),
    (_capi.FORMAT_LONG_ASCII, 'long-ascii'),
    (_capi.FORMAT_BINARY_FLOAT, 'binary-float32'),
    (_capi.FORMAT_BINARY_DOUBLE, 'binary-float64'),
]

CORPUS = sorted(FIXTURE_DIR.rglob('*.frd'))
CORPUS_IDS = [str(p.relative_to(FIXTURE_DIR)) for p in CORPUS]

# Byte identity is a claim about CalculiX's spelling, so it is asked only of
# files CalculiX wrote. The hand-written fixtures are deliberately not in that
# spelling -- they carry `0.0` where a solver writes `0.00000E+00`, because
# their job is to exercise what the *reader* tolerates -- and normalising them
# is the writer working, not failing. They get the semantic claim below
# instead.
SOLVER_WRITTEN = [p for p in CORPUS if p.parent.name in ('generated', 'binary')]
SOLVER_IDS = [str(p.relative_to(FIXTURE_DIR)) for p in SOLVER_WRITTEN]

BINARY_PAIRS = [
    (b.stem, b, FIXTURE_DIR / 'generated' / b.name.replace('_binary.frd', '.frd'))
    for b in sorted((FIXTURE_DIR / 'generated' / 'binary').glob('*.frd'))
    if (FIXTURE_DIR / 'generated' / b.name.replace('_binary.frd', '.frd')).exists()
]


def _assert_same_bits(got, expected, what: str) -> None:
    """Compare floats by bit pattern.

    `==` is wrong in both directions for this: a matching NaN compares unequal
    and a sign flipped on a zero compares equal. doc/parity.md records the
    sweep that made the second one matter.
    """
    a = np.ascontiguousarray(got, dtype=np.float64).view(np.uint64)
    b = np.ascontiguousarray(expected, dtype=np.float64).view(np.uint64)
    assert a.shape == b.shape, f'{what}: shape {a.shape} vs {b.shape}'
    differing = int((a != b).sum())
    assert differing == 0, f'{what}: {differing} of {a.size} values changed through the writer'


def _has_blocks(data: bytes) -> bool:
    """Whether a file holds anything the writer actually has to regenerate."""
    return any(
        line.strip().startswith((b'2C', b'3C', b'100C')) for line in data.split(b'\n')[:4000]
    )


def test_the_byte_gate_has_solver_written_files_to_grade():
    """The premise. An empty parametrisation passes every test under it."""
    assert len(SOLVER_WRITTEN) >= 24, (
        f'only {len(SOLVER_WRITTEN)} solver-written fixtures found; regenerate with '
        f'tools/generate_fixtures.py, or the byte gate below grades nothing'
    )
    with_blocks = sum(1 for p in SOLVER_WRITTEN if _has_blocks(p.read_bytes()))
    assert with_blocks == len(SOLVER_WRITTEN), (
        f'{len(SOLVER_WRITTEN) - with_blocks} of them contain no FRD block, so they '
        f'round-trip by being copied and the gate is weaker than it looks'
    )


@pytest.mark.parametrize('path', SOLVER_WRITTEN, ids=SOLVER_IDS)
def test_solver_written_files_survive_a_round_trip_byte_for_byte(path):
    """Read and emit again: the output is the input, byte for byte.

    Every field width and wrapping rule has to be right, and none of it is
    graded against this project's opinion of the format -- these files came
    out of CalculiX. The same gate runs out of tree over 1,111 external files,
    which is where it found the two dialects; see doc/writing.md.
    """
    data = path.read_bytes()
    assert _capi.rewrite_bytes(data) == data


def _materialise(data: bytes):
    """Everything a document says, or the refusal it answers with instead.

    Steps are parsed on demand here, so a malformed block surfaces when its
    values are asked for and not when the file is opened. A comparison that
    only opened both files would miss it entirely.
    """
    reader = _capi.NativeFile.from_bytes(data)
    try:
        state = {
            'points': np.array(reader.points, dtype=np.float64, copy=True),
            'node_ids': np.array(reader.node_ids, copy=True),
            'cell_types': np.array(reader.cell_types, copy=True),
            'connectivity': np.array(reader.cell_connectivity, copy=True),
            'step_times': list(reader.step_times),
            'arrays': [],
        }
        for step in range(reader.n_steps):
            for index, (name, n_components, kind) in enumerate(reader.array_infos(step)):
                state['arrays'].append(
                    (
                        step,
                        name,
                        n_components,
                        kind,
                        np.array(reader.array(step, index), dtype=np.float64, copy=True),
                    )
                )
    finally:
        reader.close()
    return state


def _materialise_or_refusal(data: bytes):
    """Materialise a document, or return the exception it answered with.

    Written as a value rather than propagated so the comparison below can hold
    both outcomes side by side: a file refused before the writer touched it
    must be refused identically after, and a writer that quietly repaired a
    malformed file would otherwise pass by making the problem go away.
    """
    try:
        return _materialise(data), None
    except Exception as refusal:  # noqa: BLE001 - the refusal is the result here
        return None, refusal


@pytest.mark.parametrize('path', CORPUS, ids=CORPUS_IDS)
def test_every_fixture_keeps_its_meaning_through_the_writer(path):
    """What the hand-written fixtures get instead of byte identity.

    A file may be respelled -- `0.0` becomes `0.00000E+00` -- but not come
    back a different mesh. Compared by bit pattern, so a lost negative zero
    fails. A fixture the reader refuses must be refused identically: a writer
    quietly repairing a ragged block would otherwise pass by making the
    problem go away.
    """
    data = path.read_bytes()
    rewritten = _capi.rewrite_bytes(data)

    before, refusal = _materialise_or_refusal(data)
    if refusal is not None:
        after_state, after_refusal = _materialise_or_refusal(rewritten)
        assert after_refusal is not None, (
            f'the original was refused with "{refusal}", the rewritten one was accepted '
            f'-- the writer repaired a file it should have reproduced'
        )
        assert type(after_refusal) is type(refusal)
        assert str(after_refusal) == str(refusal), (
            f'original refused with "{refusal}", rewritten with "{after_refusal}"'
        )
        assert after_state is None
        return

    after, _ = _materialise_or_refusal(rewritten)

    np.testing.assert_array_equal(after['node_ids'], before['node_ids'])
    np.testing.assert_array_equal(after['cell_types'], before['cell_types'])
    np.testing.assert_array_equal(after['connectivity'], before['connectivity'])
    assert after['step_times'] == before['step_times']
    _assert_same_bits(after['points'], before['points'], 'points')

    assert [a[:4] for a in after['arrays']] == [a[:4] for a in before['arrays']], 'array list'
    for (step, name, _nc, _kind, got), (_s, _n, _c, _k, expected) in zip(
        after['arrays'], before['arrays'], strict=True
    ):
        _assert_same_bits(got, expected, f'{name} at step {step}')


@pytest.mark.parametrize('path', SOLVER_WRITTEN, ids=SOLVER_IDS)
def test_rewriting_twice_changes_nothing_more(path):
    """Idempotence: whatever the writer normalises, it normalises once.

    A writer that shifted a field by a column on each pass would still satisfy
    the semantic test above on every pass, and would corrupt a file a little
    more each time it was touched.
    """
    once = _capi.rewrite_bytes(path.read_bytes())
    assert _capi.rewrite_bytes(once) == once


def _all_values(data: bytes) -> np.ndarray:
    """Return every value a document actually stores, in order.

    Raw arrays only. Mises and the principal values are computed by the reader
    from the tensor rather than read, so they are full-precision results of
    rounded inputs and say nothing about how a field was written.
    """
    reader = _capi.NativeFile.from_bytes(data)
    try:
        out = [np.asarray(reader.points, dtype=np.float64).ravel()]
        for step in range(reader.n_steps):
            for index, (_name, _n, kind) in enumerate(reader.array_infos(step)):
                if kind != 0:  # PVFRD_ARRAY_RAW
                    continue
                out.append(np.asarray(reader.array(step, index), dtype=np.float64).ravel())
        return np.concatenate(out)
    finally:
        reader.close()


def _rendered(values: np.ndarray) -> np.ndarray:
    """Return `values` as ASCII six-digit fields would hold them."""
    return np.array([float(f'{v:12.5E}') for v in values])


@pytest.mark.parametrize(
    ('name', 'binary', 'ascii_twin'), BINARY_PAIRS, ids=[p[0] for p in BINARY_PAIRS]
)
def test_converted_ascii_is_the_double_rounded_not_the_float(name, binary, ascii_twin):
    """Convert binary to ASCII and account for every difference from CalculiX.

    Ours is the six-digit rounding of the stored ``float64``; CalculiX's is
    that value cast to ``float`` first, because ``frd.c`` casts on its ASCII
    path. Both exact rather than banded, so a decode reading the wrong bytes
    cannot pass.
    """
    exact = _all_values(binary.read_bytes())
    ours = _all_values(_capi.rewrite_bytes(binary.read_bytes(), _capi.FORMAT_LONG_ASCII))
    theirs = _all_values(ascii_twin.read_bytes())

    assert exact.size, f'{name} holds no values'
    assert ours.shape == exact.shape == theirs.shape, f'{name}: value counts differ'

    np.testing.assert_array_equal(
        ours, _rendered(exact), err_msg=f'{name}: our ASCII is not the rounded double'
    )
    np.testing.assert_array_equal(
        theirs,
        _rendered(exact.astype(np.float32).astype(np.float64)),
        err_msg=f"{name}: CalculiX's ASCII is not the rounded float",
    )


def test_the_float_cast_explains_a_few_percent_and_no_more():
    """The population, so that a change in it is visible rather than local.

    Both bounds matter. Nothing differing would mean the cast is never
    exercised and the test above never reaches the claim that separates the
    two renderings; a large fraction differing would mean something other than
    a rounding tie is at work.
    """
    total = differing = 0
    for _name, binary, ascii_twin in BINARY_PAIRS:
        exact = _all_values(binary.read_bytes())
        theirs = _all_values(ascii_twin.read_bytes())
        total += exact.size
        differing += int((_rendered(exact) != theirs).sum())

    assert total > 500, 'too few values to say anything about the population'
    assert differing, 'nothing differs, so the float cast is never exercised'
    assert differing < total * 0.1, (
        f'{differing} of {total} values differ from CalculiX; a rounding tie explains '
        f'a few percent, so more than that is a different problem'
    )


@pytest.mark.parametrize(
    ('name', 'binary', 'ascii_twin'), BINARY_PAIRS, ids=[p[0] for p in BINARY_PAIRS]
)
def test_converting_to_ascii_writes_the_terminator_ascii_requires(name, binary, ascii_twin):  # noqa: ARG001
    """Binary blocks have no ` -3`; ASCII ones must get one.

    CalculiX writes the terminator only in ASCII mode, so converting has to
    invent it. Without it CalculiX rejects the file: its reader ends a block on
    the terminator, so the rest of the file is still the node block. The
    round-trip gate cannot see this -- it compares a file with itself, where a
    missing terminator stays missing on both sides.
    """
    converted = _capi.rewrite_bytes(binary.read_bytes(), _capi.FORMAT_LONG_ASCII)
    original = binary.read_bytes()

    assert b'\n -3' not in original, f'{name} is not binary; this test grades nothing'
    assert converted.count(b'\n -3') >= 2, (
        f'{name} converted to ASCII has {converted.count(b" -3")} block terminators; '
        f'a mesh with results needs one after the nodes, the elements and each result block'
    )


@pytest.mark.parametrize(
    'path',
    [p for p in SOLVER_WRITTEN if 'binary' not in str(p)],
    ids=[i for i in SOLVER_IDS if 'binary' not in i],
)
def test_ascii_survives_a_trip_through_binary(path):
    """ASCII -> binary float64 -> ASCII returns the original bytes.

    Binary float64 holds every value ASCII can express, so this direction has
    to be lossless. It is the check on the binary *emitter*, which the
    round-trip gate only covers for files that were already binary.
    """
    data = path.read_bytes()
    if not _has_blocks(data):
        pytest.skip('no blocks to convert')
    binary = _capi.rewrite_bytes(data, _capi.FORMAT_BINARY_DOUBLE)
    assert _capi.rewrite_bytes(binary, _capi.FORMAT_LONG_ASCII) == data


def _mesh_of(path):
    return _capi.NativeFile(str(path))


@pytest.mark.parametrize(('fmt', 'label'), FORMATS, ids=[f[1] for f in FORMATS])
def test_a_document_built_from_a_mesh_reads_back_as_that_mesh(fmt, label):
    """Construction, in every format the writer offers."""
    source = _mesh_of(FIXTURE_DIR / 'generated' / 'hex20.frd')
    try:
        infos = source.array_infos(0)
        raw = [
            (name, source.array(0, i))
            for i, (name, _nc, kind) in enumerate(infos)
            if kind == 0  # PVFRD_ARRAY_RAW: the derived ones are recomputed on read
        ]
        with _capi.Writer(fmt) as writer:
            writer.set_nodes(source.points, source.node_ids)
            writer.set_cells(source.cell_types, source.cell_offsets, source.cell_connectivity)
            writer.begin_step(1, 1.0)
            for name, values in raw:
                writer.add_array(name, values)
            data = writer.finish()

        back = _capi.NativeFile.from_bytes(data)
        try:
            assert back.n_points == source.n_points, f'{label}: point count'
            assert back.n_cells == source.n_cells, f'{label}: cell count'
            np.testing.assert_array_equal(back.node_ids, source.node_ids)
            np.testing.assert_array_equal(back.cell_types, source.cell_types)
            np.testing.assert_array_equal(back.cell_connectivity, source.cell_connectivity)

            written = {name for name, _ in raw}
            names_back = {name for name, _, _ in back.array_infos(0)}
            assert written <= names_back, f'{label}: {written - names_back} did not survive'
        finally:
            back.close()
    finally:
        source.close()


@pytest.mark.parametrize(('fmt', 'label'), FORMATS, ids=[f[1] for f in FORMATS])
def test_each_format_keeps_values_to_its_own_precision(fmt, label):
    """What each format promises about a value, stated rather than assumed.

    float64 is exact. float32 is not, and a test claiming it were would be
    wrong rather than strict: one of this repository's own fixtures has a
    coordinate of -0.05, which no float32 holds. ASCII carries six significant
    digits.
    """
    source = _mesh_of(FIXTURE_DIR / 'generated' / 'tri3.frd')
    try:
        points = np.asarray(source.points, dtype=np.float64)
        with _capi.Writer(fmt) as writer:
            writer.set_nodes(points, source.node_ids)
            writer.set_cells(source.cell_types, source.cell_offsets, source.cell_connectivity)
            data = writer.finish()
        back = _capi.NativeFile.from_bytes(data)
        try:
            got = np.asarray(back.points, dtype=np.float64)
            scale = np.maximum(np.abs(points), 1e-300)
            worst = float((np.abs(got - points) / scale).max())
        finally:
            back.close()
    finally:
        source.close()

    bound = {
        _capi.FORMAT_BINARY_DOUBLE: 0.0,
        _capi.FORMAT_BINARY_FLOAT: 6e-8,  # float32 has 24 bits of significand
        _capi.FORMAT_LONG_ASCII: 5e-6,  # %12.5E is six significant digits
        _capi.FORMAT_SHORT_ASCII: 5e-6,
    }[fmt]
    assert worst <= bound, f'{label}: coordinates moved by {worst:.3e}, more than {bound:.0e}'


def test_a_cell_type_with_no_calculix_equivalent_is_refused():
    """Refused, and named. Dropping it would write a smaller mesh in silence."""
    with _capi.Writer(_capi.FORMAT_LONG_ASCII) as writer:
        writer.set_nodes(np.zeros((4, 3)))
        with pytest.raises(Exception, match='VTK type') as caught:
            # VTK_POLYGON: readable as a concept, not an FRD element.
            writer.set_cells([7], [0, 4], [0, 1, 2, 3])
    assert '7' in str(caught.value)


def test_a_cell_whose_point_count_is_wrong_is_refused():
    with _capi.Writer(_capi.FORMAT_LONG_ASCII) as writer:
        writer.set_nodes(np.zeros((8, 3)))
        with pytest.raises(Exception, match='points, but its type needs'):
            writer.set_cells([12], [0, 4], [0, 1, 2, 3])  # HEXAHEDRON needs eight


def test_a_writer_rejects_a_format_that_is_not_one():
    with pytest.raises(ValueError, match='format code'):
        _capi.Writer(9)


def _canonical_glued_document() -> bytes:
    """A short-format element whose face ids are written with no gap.

    Five-wide fields holding five-digit ids leave nothing between them, so
    eight ids come out as `1000110002100031...` and read as one forty-digit
    number, which overflows and is silently dropped. Built here because the
    committed short-format fixture has a malformed element header and never
    reaches the face-parsing path it was named for.
    """
    lines = ['1C glued faces', '2C']
    lines += [f' -1{10000 + i:5d}{float(i):12.5E}{0.0:12.5E}{0.0:12.5E}' for i in range(1, 9)]
    lines += [' -3', '3C', ' -1    1    1    0    1']
    lines.append(' -2' + ''.join(f'{10000 + i:5d}' for i in range(1, 9)))
    lines += [' -3', ' 9999', '']
    return '\n'.join(lines).encode()


def test_glued_face_ids_survive_the_writer():
    """The regression. Before the fix the face line vanished entirely."""
    data = _canonical_glued_document()
    assert _capi.rewrite_bytes(data) == data


def test_glued_face_ids_are_read_as_eight_nodes_not_one():
    """And the premise: the fixture really is the glued form.

    Without this, the test above would still pass over a document whose ids
    happened to be separated by spaces, and would be grading nothing.
    """
    data = _canonical_glued_document()
    faces = next(line for line in data.split(b'\n') if line.startswith(b' -2'))
    assert b' ' not in faces[3:], f'{faces!r} is not the glued form'

    reader = _capi.NativeFile.from_bytes(data)
    try:
        assert reader.n_cells == 1
        assert len(reader.cell_connectivity) == 8, 'the element lost nodes on the way in'
    finally:
        reader.close()


# --- the PyVista-facing API -------------------------------------------------


@pytest.mark.parametrize(
    ('kwargs', 'label', 'bound'),
    [
        ({}, 'ascii', 5e-6),
        ({'binary': True}, 'binary-float64', 0.0),
        ({'binary': True, 'double': False}, 'binary-float32', 6e-8),
    ],
)
def test_write_then_read_returns_the_same_mesh(tmp_path, kwargs, label, bound):
    """`write` and `read` are inverses to the precision of the format asked for."""
    pyvista_frd = pytest.importorskip('pyvista_frd')
    mesh = pyvista_frd.read(FIXTURE_DIR / 'generated' / 'hex20.frd')

    target = tmp_path / f'{label}.frd'
    pyvista_frd.write(target, mesh, **kwargs)
    back = pyvista_frd.read(target)

    assert back.n_points == mesh.n_points
    assert back.n_cells == mesh.n_cells
    assert list(back.point_data) == list(mesh.point_data), 'array names, in order'

    worst = 0.0
    for name in mesh.point_data:
        expected = np.asarray(mesh.point_data[name])
        if expected.dtype.kind not in 'fiu':
            continue
        got = np.asarray(back.point_data[name]).astype(np.float64)
        expected = expected.astype(np.float64)
        scale = np.maximum(np.abs(expected), 1e-300)
        worst = max(worst, float((np.abs(got - expected) / scale).max()))
    assert worst <= bound, f'{label}: values moved by {worst:.3e}, more than {bound:.0e}'


def test_write_keeps_the_files_own_node_numbering(tmp_path):
    """Node ids are a numbering, not an array of stringified integers.

    A mesh this library read carries the file's numbering in
    `original_node_ids`, and the fixtures do not number from one -- tri3
    starts at 4 -- so a writer that ignored it would produce a file that
    described the same shape under different names.
    """
    pyvista_frd = pytest.importorskip('pyvista_frd')
    mesh = pyvista_frd.read(FIXTURE_DIR / 'generated' / 'tri3.frd')
    original = np.asarray(mesh.point_data['original_node_ids'])
    assert original[0] != '1', 'this fixture numbers from one, so it grades nothing'

    target = tmp_path / 'renumbered.frd'
    pyvista_frd.write(target, mesh)
    np.testing.assert_array_equal(
        np.asarray(pyvista_frd.read(target).point_data['original_node_ids']), original
    )


def test_write_refuses_an_array_frd_cannot_hold(tmp_path):
    """Refused, not skipped: a dropped array is a smaller file that looks fine."""
    pyvista_frd = pytest.importorskip('pyvista_frd')
    mesh = pyvista_frd.read(FIXTURE_DIR / 'generated' / 'tri3.frd')
    mesh.point_data['labels'] = np.array(['a'] * mesh.n_points)

    with pytest.raises(ValueError, match='which FRD cannot hold'):
        pyvista_frd.write(tmp_path / 'nope.frd', mesh)


def test_convert_with_no_target_format_reproduces_the_file(tmp_path):
    pyvista_frd = pytest.importorskip('pyvista_frd')
    source = FIXTURE_DIR / 'generated' / 'binary' / 'hex8_binary.frd'
    target = tmp_path / 'same.frd'
    pyvista_frd.convert(source, target)
    assert target.read_bytes() == source.read_bytes()


def test_convert_turns_binary_into_something_an_ascii_reader_can_open(tmp_path):
    """The point of the conversion, stated as the thing it makes possible.

    PyVista's reader parses FRD as text, so a binary file yields it a
    zero-node parse. After conversion it reads the mesh.
    """
    pyvista_frd = pytest.importorskip('pyvista_frd')
    pv = pytest.importorskip('pyvista')

    source = FIXTURE_DIR / 'generated' / 'binary' / 'hex8_binary.frd'
    target = tmp_path / 'converted.frd'
    pyvista_frd.convert(source, target, binary=False)

    with pytest.raises(Exception):  # noqa: B017, PT011 - the oracle's own refusal
        pv.get_reader(str(source)).read()

    mesh = pv.get_reader(str(target)).read()
    assert mesh.n_points == 8
    assert mesh.n_cells == 1


def _document_with_a_stray_line_in_the_middle() -> bytes:
    """A node block with a line the parser cannot read, halfway down it.

    A line that is not a record is not an error -- the reader steps over it,
    and the writer has to put it back where it was. An earlier version emitted
    unparsed lines with the block header, hoisting this one to the top: the
    file still read back as the same mesh, with its bytes rearranged.
    Canonical spelling elsewhere, so only the position can fail.
    """
    lines = ['1C stray line', '2C']
    lines += [f' -1{i:10d}{float(i):12.5E}{0.0:12.5E}{0.0:12.5E}' for i in (1, 2)]
    lines.append('this line is not a record and never was')
    lines += [f' -1{i:10d}{float(i):12.5E}{0.0:12.5E}{0.0:12.5E}' for i in (3, 4)]
    lines.append(' -3')

    # And again inside a result block, which reaches a different branch of the
    # parser: node and element blocks end at the first thing that is not a
    # record, while a result block has `-4` and `-5` metadata to step over
    # first, so the two paths handle a stray line separately.
    lines += [
        '  100CL    1 1.000000000           4                     0    1           1',
        ' -4  T              1    1',
        ' -5  T1             1    1    0    0',
    ]
    lines += [f' -1{i:10d}{float(i) * 10.0:12.5E}' for i in (1, 2)]
    lines.append('nor is this one, and it sits inside a result block')
    lines += [f' -1{i:10d}{float(i) * 10.0:12.5E}' for i in (3, 4)]
    lines += [' -3', ' 9999', '']
    return '\n'.join(lines).encode()


def test_an_unreadable_line_keeps_its_place_in_the_block():
    """The regression: it used to come back at the top of the block."""
    data = _document_with_a_stray_line_in_the_middle()
    rewritten = _capi.rewrite_bytes(data)

    for stray in (
        b'this line is not a record and never was',
        b'nor is this one, and it sits inside a result block',
    ):
        assert data.count(stray) == 1, 'the fixture lost its subject'
        assert rewritten.count(stray) == 1, f'{stray!r} was dropped or duplicated'

        before = data.split(b'\n').index(stray)
        after = rewritten.split(b'\n').index(stray)
        assert after == before, f'{stray!r} moved from line {before} to line {after}'

    assert rewritten == data


def test_a_nan_is_spelled_the_way_calculix_spells_it():
    """`NaN`, not `NAN` and not `nan`.

    CalculiX writes NaN coordinates for the nodes of a network deck and spells
    it `NaN`; glibc's printf produces `NAN` and Microsoft's `nan`, so the same
    document would be written three ways. The external corpus covers this with
    two files; in tree nothing does, because the fixture carrying NaN is
    hand-written and not held to byte identity.
    """
    lines = ['1C nan coordinates', '2C']
    lines.append(' -1' + f'{1:10d}' + '         NaN' * 3)
    lines.append(f' -1{2:10d}{1.0:12.5E}{0.0:12.5E}{0.0:12.5E}')
    lines += [' -3', ' 9999', '']
    data = '\n'.join(lines).encode()

    rewritten = _capi.rewrite_bytes(data)
    assert rewritten.count(b'         NaN') == 3, (
        f'expected three NaN fields, got {rewritten.count(b"         NaN")}: '
        f'{rewritten.splitlines()[2]!r}'
    )
    assert rewritten == data

    # And the value really did travel as a NaN rather than as text.
    reader = _capi.NativeFile.from_bytes(rewritten)
    try:
        assert np.isnan(np.asarray(reader.points, dtype=np.float64)[0]).all()
    finally:
        reader.close()
