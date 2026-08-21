"""Binary FRD, graded against the ASCII file CalculiX wrote from the same deck.

Binary is half of the FRD format and this library did not implement it, so
every file CalculiX produces from ``*REFINE MESH`` -- which writes binary
unconditionally -- read as an empty mesh with no complaint. The header would
declare 2195 nodes and the reader would hand back none.

These fixtures cannot be graded the way the rest of the corpus is. PyVista's
reader parses FRD as text, so a binary file yields it a silent zero-node parse
rather than an error, and comparing against that would compare our answer with
nothing at all.

What they are graded against is better than the oracle. For each binary
fixture there is an ASCII fixture that CalculiX wrote **from the same input
deck in the same run of the generator** -- the only difference is the DOUBLE
keyword. Two encodings of one computation, neither of them produced by this
project, must yield the same mesh and the same values. A reader that decoded
binary records at the wrong offset could not accidentally reproduce the ASCII
file's numbers.

The one thing that must *not* be asserted is bit-equality. ASCII records are
written with ``%12.5E``, five significant digits, so the ASCII twin is the
lossy one. The band below is that rounding and nothing else, and it is
expressed relatively for the same reason the eigenvalue band is in
doc/divergences.md: an absolute tolerance on a strain of order 1e-9 and a
stress of order 1e+8 cannot both be right.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pyvista_frd import _capi
from tests.conftest import FIXTURE_DIR

# Half of the last digit %12.5E can express. Anything above this is not the
# ASCII writer rounding, it is a decode landing on the wrong bytes.
ASCII_HALF_ULP = 5e-6

# Mises and the principal values are not in the file. This library computes
# them from the six tensor components (cpp/src/derived.cpp), so both twins run
# identical code and the only thing that differs is the rounding of the inputs.
# That makes the band a propagation bound, which is derivable rather than
# fitted -- and the distinction matters, because a band chosen to make the run
# green would grade nothing.
#
# Write u for the per-component relative rounding above and s for the tensor.
# A perturbation with |ds_ij| <= u|s_ij| has ||ds||_F <= u||s||_F, so:
#
#   principals  Weyl's inequality: |dlambda| <= ||ds||_2 <= ||ds||_F.  Factor 1.
#   von Mises   sigma_v = sqrt(3/2)||dev s||_F, whose gradient has Frobenius
#               norm sqrt(3/2) exactly.  Factor sqrt(1.5) ~ 1.2247.
#
# Measured across the fixtures: principals 4.231e-06, Mises 4.036e-06. Both sit
# under their own bound, and neither bound was moved to put them there.
DERIVED_BOUND = {
    'principal': 1.0 * ASCII_HALF_ULP,
    'mises': math.sqrt(1.5) * ASCII_HALF_ULP,
}


def _frobenius(tensor: np.ndarray) -> np.ndarray:
    """Frobenius norm of the 3x3 the six stored components stand for.

    FRD stores xx, yy, zz, xy, yz, zx. The off-diagonals each appear twice in
    the matrix, so ``np.linalg.norm`` over the six-vector is not this norm --
    it under-counts, which inflates every ratio measured against it.
    """
    xx, yy, zz, xy, yz, zx = (tensor[:, i] for i in range(6))
    return np.sqrt(xx**2 + yy**2 + zz**2 + 2.0 * (xy**2 + yz**2 + zx**2))


BINARY_DIR = FIXTURE_DIR / 'generated' / 'binary'


def _pairs() -> list[tuple[str, object, object]]:
    out = []
    for binary in sorted(BINARY_DIR.glob('*.frd')):
        ascii_twin = FIXTURE_DIR / 'generated' / binary.name.replace('_binary.frd', '.frd')
        if ascii_twin.exists():
            out.append((binary.stem, binary, ascii_twin))
    return out


PAIRS = _pairs()
IDS = [name for name, _, _ in PAIRS]


def test_there_are_binary_fixtures_to_grade():
    """The premise. An empty parametrisation passes every test below."""
    assert len(PAIRS) >= 12, (
        f'only {len(PAIRS)} binary/ASCII fixture pairs found; regenerate with '
        f'tools/generate_fixtures.py'
    )


@pytest.mark.parametrize(('name', 'binary', 'ascii_twin'), PAIRS, ids=IDS)
def test_the_fixture_really_is_binary(name, binary, ascii_twin):  # noqa: ARG001
    """Otherwise every test here could pass by comparing two ASCII files."""
    raw = binary.read_bytes()
    assert any(b > 0x7F for b in raw), f'{name} has no binary payload'
    header = next(line for line in raw.split(b'\n') if line.lstrip().startswith(b'2C'))
    assert header.split()[-1] in (b'2', b'3'), (
        f'{name} declares node format {header.split()[-1]!r}, which is an ASCII code'
    )


@pytest.mark.parametrize(('name', 'binary', 'ascii_twin'), PAIRS, ids=IDS)
def test_binary_and_ascii_twins_have_the_same_mesh(name, binary, ascii_twin):  # noqa: ARG001
    """Coordinates are exact here: both encodings hold the same node positions.

    Not quite -- ASCII coordinates also pass through %12.5E -- so the same
    relative band applies. What must match exactly is the *structure*: node
    count, cell count, connectivity and cell types are integers in both.
    """
    with _capi.NativeFile(str(binary)) as b, _capi.NativeFile(str(ascii_twin)) as a:
        assert b.n_points == a.n_points, 'node count'
        assert b.n_cells == a.n_cells, 'cell count'
        np.testing.assert_array_equal(b.node_ids, a.node_ids)
        np.testing.assert_array_equal(b.cell_types, a.cell_types)
        np.testing.assert_array_equal(b.cell_connectivity, a.cell_connectivity)
        np.testing.assert_array_equal(b.cell_offsets, a.cell_offsets)

        pa = np.asarray(a.points, dtype=np.float64)
        pb = np.asarray(b.points, dtype=np.float64)
        scale = np.maximum(np.abs(pa), np.abs(pb))
        rel = np.where(scale > 0, np.abs(pa - pb) / np.maximum(scale, 1e-300), 0.0)
        assert float(rel.max()) <= ASCII_HALF_ULP, 'coordinates differ by more than %12.5E rounding'


@pytest.mark.parametrize(('name', 'binary', 'ascii_twin'), PAIRS, ids=IDS)
def test_binary_and_ascii_twins_have_the_same_results(name, binary, ascii_twin):
    """Step times, array names, shapes, and values within the ASCII rounding."""
    with _capi.NativeFile(str(binary)) as b, _capi.NativeFile(str(ascii_twin)) as a:
        assert b.step_times == a.step_times, 'step times'
        assert b.n_steps > 0, f'{name} has no steps, so this test grades nothing'

        for step in range(a.n_steps):
            ia, ib = a.array_infos(step), b.array_infos(step)
            assert [n for n, _, _ in ib] == [n for n, _, _ in ia], f'step {step}: array names'

            by_name = {n: i for i, (n, _, _) in enumerate(ia)}

            for index, (array_name, n_components, _kind) in enumerate(ia):
                va = np.asarray(a.array(step, index), dtype=np.float64)
                vb = np.asarray(b.array(step, index), dtype=np.float64)
                assert vb.shape == va.shape, f'{array_name}: shape {vb.shape} vs {va.shape}'
                assert ib[index][1] == n_components, f'{array_name}: component count'
                if not va.size:
                    continue

                error = np.abs(va - vb)

                if array_name.endswith(('_PS1', '_PS2', '_PS3')):
                    kind = 'principal'
                elif array_name.endswith(('_Mises', '_sgMises')):
                    kind = 'mises'
                else:
                    kind = None

                if kind is None:
                    # A stored value: its own magnitude is the right scale.
                    bound = ASCII_HALF_ULP
                    scale = np.maximum(np.abs(va), np.abs(vb))
                else:
                    # A derived value. Dividing by the derived value itself is
                    # the measurement doc/divergences.md exists to warn about:
                    # both of these lose relative accuracy where they approach
                    # zero -- an eigenvalue by conditioning, Mises by the
                    # cancellation in the component differences -- so that ratio
                    # reports the conditioning of the formula rather than the
                    # accuracy of the read. Measured that way the principals come
                    # out at 5.8e-05 and look ten times worse than the inputs
                    # they were computed from, which is not possible, and is the
                    # tell that the denominator is wrong.
                    #
                    # The source tensor is the honest scale, against the
                    # propagation bound derived for each formula above.
                    base_name = array_name.rsplit('_', 1)[0]
                    assert base_name in by_name, (
                        f'{array_name} at step {step}: derived from {base_name}, which is '
                        f'not in this step, so it cannot be graded against its own tensor'
                    )
                    base = np.asarray(a.array(step, by_name[base_name]), dtype=np.float64)
                    assert base.ndim == 2, f'{base_name} is {base.shape}, not a tensor'
                    assert base.shape[1] == 6, f'{base_name} has {base.shape[1]} components, not 6'
                    bound = DERIVED_BOUND[kind]
                    scale = _frobenius(base)

                measured = np.where(scale > 0, error / np.maximum(scale, 1e-300), error)
                worst = float(measured.max())
                assert worst <= bound, (
                    f'{array_name} at step {step}: difference {worst:.3e} exceeds the '
                    f'{bound:.3e} that %12.5E rounding of the inputs can explain'
                )
