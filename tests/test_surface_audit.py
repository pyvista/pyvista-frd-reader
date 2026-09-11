"""Prove the public-corpus audit detects missing geometry and altered results."""

import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from tests.conftest import FIXTURE_DIR
from tools import sweep_surfaces

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from fetch_surface_corpus import replay


@pytest.mark.parametrize('kind', ['NODE', 'ELEMENT'])
@pytest.mark.parametrize('defect', ['empty', 'result'])
def test_audit_rejects_bad_extraction(tmp_path, monkeypatch, kind, defect):
    inp = tmp_path / 'model.inp'
    members = '1\n3\n' if kind == 'NODE' else '1,S1\n1,S2\n'
    inp.write_text(f'*SURFACE,NAME=A,TYPE={kind}\n{members}')
    frd = FIXTURE_DIR / 'mock.frd'
    valid = sweep_surfaces.audit_pair(frd, inp)
    assert valid['surfaces'][0]['status'] == 'checked'
    assert valid['surfaces'][0]['steps'] == 3
    extract = sweep_surfaces.extract_surface

    def broken(*args, **kwargs):
        result = extract(*args, **kwargs)
        if defect == 'empty':
            return result.extract_cells(np.empty(0, dtype=np.int64))
        result.point_data['STRESS'][0, 0] += 123
        return result

    monkeypatch.setattr(sweep_surfaces, 'extract_surface', broken)
    row = sweep_surfaces.audit_pair(frd, inp)['surfaces'][0]
    assert row['status'] == 'failed'
    assert 'AssertionError' in row['error']
    assert row['steps'] == 0


def test_manifest_replay_verifies_existing_bytes(tmp_path):
    data = b'*SURFACE,NAME=A\n1,S1\n'
    blob = hashlib.sha1(f'blob {len(data)}\0'.encode() + data, usedforsecurity=False).hexdigest()
    cache = tmp_path / '.blobs' / blob
    cache.parent.mkdir()
    cache.write_bytes(data)
    manifest = tmp_path / 'input.json.gz'
    manifest.write_bytes(
        gzip.compress(
            json.dumps(
                [
                    {
                        'url': 'https://raw.githubusercontent.com/example/model/'
                        + 'a' * 40
                        + '/mesh.inp',
                        'blob': blob,
                    }
                ]
            ).encode()
        )
    )
    assert replay(tmp_path, manifest) == 0
    target = tmp_path / 'example__model' / 'mesh.inp'
    assert target.read_bytes() == data
    target.write_bytes(b'corrupt')
    assert replay(tmp_path, manifest) == 1
    assert 'do not match' in json.loads((tmp_path / 'manifest.json').read_text())[0]['error']
