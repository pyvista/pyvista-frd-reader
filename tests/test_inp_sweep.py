"""The external corpus audit must distinguish checks from rejected inputs."""

import json
import sys

from tests.conftest import FIXTURE_DIR
from tools.sweep_external import main as sweep_frd
from tools.sweep_inp import audit
from tools.sweep_inp import main as sweep_inp


def test_shipped_frd_reference_files_are_discovered(tmp_path, monkeypatch):
    reference = tmp_path / 'mesh.frd.ref'
    reference.write_bytes((FIXTURE_DIR / 'mock.frd').read_bytes())
    report = tmp_path / 'report.json'
    monkeypatch.setattr(sys, 'argv', ['sweep_external', str(tmp_path), '--json', str(report)])
    assert sweep_frd() == 0
    rows = json.loads(report.read_text())
    assert len(rows) == 1
    assert rows[0]['verdict'] == 'agree'


def test_inp_audit_checks_all_steps_and_reports_missing_includes(tmp_path, monkeypatch):
    inp = tmp_path / 'model.inp'
    inp.write_text('*NSET,NSET=A\n1,3\n*ELSET,ELSET=A\n1\n')
    inp.with_suffix('.frd.ref').write_bytes((FIXTURE_DIR / 'mock.frd').read_bytes())
    row = audit(inp)
    assert row['status'] == 'parsed'
    assert row['pairs'][0]['status'] == 'checked'
    assert row['pairs'][0]['steps'] == 3
    report = tmp_path / 'report.json'
    monkeypatch.setattr(sys, 'argv', ['sweep_inp', str(tmp_path), '--json', str(report)])
    assert sweep_inp() == 0
    inp.write_text('*INCLUDE,INPUT=missing.inc\n')
    assert sweep_inp() == 1
    rows = json.loads(report.read_text())
    assert rows[0]['status'] == 'rejected'
    assert 'FileNotFoundError' in rows[0]['error']


def test_inp_audit_reports_a_failed_companion(tmp_path):
    inp = tmp_path / 'model.inp'
    inp.write_text('*NSET,NSET=A\n1\n')
    inp.with_suffix('.frd').write_bytes(b'not an FRD mesh')
    row = audit(inp)
    assert row['status'] == 'parsed'
    assert row['pairs'][0]['status'] == 'failed'
    assert 'No nodes found' in row['pairs'][0]['error']
