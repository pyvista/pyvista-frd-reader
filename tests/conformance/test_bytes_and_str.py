"""Grade the divergence class the corpus cannot see.

Every fixture under ``tests/fixtures/`` is pure ASCII, which is the right
thing for a corpus of an ASCII format -- and it means the conformance sweep is
structurally blind to every difference that arises from PyVista parsing a
decoded ``str`` where this library parses bytes. Three of the entries in
doc/divergences.md come from exactly that, and none of them was graded against
the reference by anything. They were pinned by unit tests asserting *our*
behaviour, which is a different claim from agreeing or disagreeing with
PyVista in the way documented.

This file builds documents in memory and puts them through both readers.
Nothing here becomes a fixture: these are not files CalculiX writes, and a
corpus that contained them would be asserting fidelity on input neither reader
should ever see. They are here to say where the two agree and where they
cannot.

The finding that motivated it: four of the differences needed no non-ASCII
byte at all. 0x1C to 0x1F are whitespace to ``str.split()`` and are ASCII, so
a file entirely within the format's own character set could be read by PyVista
and dropped here. That is now fixed, and these tests are what would notice it
coming back.
"""

from __future__ import annotations

import numpy as np
import pytest

from pyvista_frd import _capi

from .ref_frd import _FRDParser

# Two nodes and one step, so the smallest thing with a result block in it.
_HEADER = (
    '    1C\n'
    '    2C                    2                     1\n'
    ' -1         1 0.00000E+00 0.00000E+00 0.00000E+00\n'
    ' -1         2 1.00000E+00 0.00000E+00 0.00000E+00\n'
    ' -3\n'
)
_FOOTER = ' -3\n'

# ASCII bytes Python's str.split() treats as whitespace. The first four are
# the ones this library used to disagree about.
ASCII_SPACE_BYTES = {
    'FILE SEPARATOR 0x1C': '\x1c',
    'GROUP SEPARATOR 0x1D': '\x1d',
    'RECORD SEPARATOR 0x1E': '\x1e',
    'UNIT SEPARATOR 0x1F': '\x1f',
    'TAB 0x09': '\t',
    'VERTICAL TAB 0x0B': '\v',
    'FORM FEED 0x0C': '\f',
    'SPACE 0x20': ' ',
}

# Whitespace outside ASCII. PyVista's answer for these depends on the machine,
# so they are asserted as "no fixed target", not as agreement. Written as
# escapes rather than literals: a bare NBSP in source is invisible to a
# reader and indistinguishable from the space beside it.
NON_ASCII_SPACE = {
    'NBSP U+00A0': '\u00a0',
    'EM SPACE U+2003': '\u2003',
    'IDEOGRAPHIC SPACE U+3000': '\u3000',
    'NEXT LINE U+0085': '\u0085',
}


def _document(separator: str) -> bytes:
    """A one-step file whose STRESS rows use `separator` between components."""
    row = (
        ' -1{node:10d} 1.00000E+00{sep}2.00000E+00 3.00000E+00'
        ' 4.00000E+00 5.00000E+00 6.00000E+00\n'
    )
    body = (
        '  100CL  1 1.000000000  1                     2    1\n'
        ' -4  STRESS      6    1\n'
        + row.format(node=1, sep=separator)
        + row.format(node=2, sep=separator)
    )
    return (_HEADER + body + _FOOTER).encode('utf-8')


def _reference_stress(raw: bytes, tmp_path) -> dict[int, list[float]]:
    path = tmp_path / 'ref.frd'
    path.write_bytes(raw)
    data = _FRDParser(str(path)).parse()
    steps = list(data.results_by_step.values())
    if not steps:
        return {}
    return {int(k): list(v) for k, v in steps[0].get('STRESS', {}).items()}


def _native_stress(raw: bytes) -> dict[int, list[float]]:
    with _capi.NativeFile.from_bytes(raw) as native:
        if native.n_steps == 0:
            return {}
        index = native.find_array(0, 'STRESS')
        if index < 0:
            return {}
        values = np.asarray(native.array(0, index), dtype=np.float64)
        ids = native.node_ids.tolist()
        return {int(node): list(values[i]) for i, node in enumerate(ids)}


@pytest.mark.parametrize('separator', ASCII_SPACE_BYTES.values(), ids=ASCII_SPACE_BYTES.keys())
def test_ascii_whitespace_is_read_the_same_way_by_both(separator, tmp_path):
    """Inside ASCII there is one right answer, and both readers must give it.

    No locale can change how these bytes decode -- every encoding PyVista
    could plausibly pick is an ASCII superset -- so unlike the non-ASCII cases
    below, this is a difference that can simply be wrong.
    """
    raw = _document(separator)
    reference = _reference_stress(raw, tmp_path)
    native = _native_stress(raw)

    assert reference, 'the reference read nothing; the fixture is wrong, not the reader'
    assert native.keys() == reference.keys(), (
        f'node sets differ: reference {sorted(reference)}, native {sorted(native)}'
    )
    for node, expected in reference.items():
        assert native[node] == pytest.approx(expected, rel=0, abs=0), f'node {node}'


@pytest.mark.parametrize('separator', NON_ASCII_SPACE.values(), ids=NON_ASCII_SPACE.keys())
def test_non_ascii_whitespace_has_no_fixed_answer_to_agree_with(separator):
    """PyVista's reading of these is a property of the machine, not the file.

    ``ref_frd`` opens the file with ``Path.open(errors='replace')`` and no
    encoding, so the bytes are decoded with whatever
    ``locale.getpreferredencoding(False)`` returns. U+2003 encoded as UTF-8 is
    one whitespace character on a UTF-8 machine and three non-space characters
    on a cp1252 one, and cp1252 is a default Windows still ships. The same
    file therefore yields a different field count on different machines.

    So there is no single behaviour here to be compatible with, and this test
    asserts that rather than pretending otherwise. What it does check is that
    *this* library is not the source of the variation: its answer is a
    function of the bytes alone.
    """
    raw = _document(separator)

    decodings = {
        encoding: raw.decode(encoding, errors='replace').split()
        for encoding in ('utf-8', 'cp1252', 'latin-1')
    }
    assert len({tuple(v) for v in decodings.values()}) > 1, (
        f'{separator!r} decodes identically everywhere, so it belongs in the ASCII test above, '
        f'where agreement can be required: {decodings}'
    )

    first = _native_stress(raw)
    second = _native_stress(raw)
    assert first == second, 'the native reader must be a function of the bytes'


def test_the_corpus_really_is_all_ascii():
    """The premise of this file.

    If a non-ASCII fixture ever lands in the corpus, the conformance sweep
    starts grading the locale-dependent behaviour above by accident, on
    whatever machine happens to run it -- green on the developer's laptop and
    red on a Windows runner, for a reason nobody would look for here.
    """
    from tests.conftest import beyond_oracle
    from tests.conftest import corpus

    offenders = []
    for path in corpus():
        # Binary FRD fixtures are exempt, and the exemption is narrow on
        # purpose. The hazard this test exists for is locale-dependent
        # *decoding*: PyVista opens FRD as text with no encoding, so a
        # non-ASCII byte in a file it reads means the sweep grades a different
        # document on a UTF-8 machine than on a cp1252 one. A binary fixture is
        # never decoded by anyone -- the oracle cannot read it and this library
        # reads its records as bytes by construction -- so there is no
        # encoding for a locale to disagree about.
        if beyond_oracle(path):
            continue
        raw = path.read_bytes()
        if any(byte > 0x7F for byte in raw):
            offenders.append(path.name)
    assert not offenders, (
        f'non-ASCII bytes in the corpus: {offenders}. See the docstring: these files would be '
        f'read differently depending on the machine running the sweep.'
    )
