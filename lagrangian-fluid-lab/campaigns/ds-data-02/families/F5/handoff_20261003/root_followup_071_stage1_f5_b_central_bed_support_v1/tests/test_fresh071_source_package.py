from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def sha(path: Path) -> str:
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def load_worker():
    p=ROOT/'scripts/initial_fixed_bed_distribution_audit.py'
    spec=importlib.util.spec_from_file_location('fresh071_audit',p); assert spec and spec.loader
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def test_worker_synthetic_check():
    load_worker()._check()

def test_b_source_contract_and_no_erase_selector():
    source=(ROOT/'candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B_Def.xml').read_text(encoding='utf-8')
    assert sha(ROOT/'candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B_Def.xml') == 'e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72'
    assert 'autofill="true"' in source and '<setdrawmode mode="solid"' in source and '<setdrawmode mode="full"' in source
    assert 'erase' not in source.lower() and 'eraseall' not in source.lower()
    root=ET.parse(ROOT/'candidate_source/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B_Def.xml').getroot()
    nodes=list(root.findall('.//mainlist/*'))
    tags=[n.tag for n in nodes]
    assert tags.index('drawfilestl') > tags.index('drawtriangles')
    assert tags.index('setmkfluid') > tags.index('drawfilestl')

def test_all_execution_requests_disabled_and_no_baseline_total():
    for name in ('gencase-request.json','initial-qa-request.json','initial-fixed-bed-distribution-audit-request.json'):
        d=json.loads((ROOT/name).read_text(encoding='utf-8'))
        assert d['launch_allowed'] is False
        assert d['independent_case_count_increment']==0
        assert d.get('full16_authorized',False) is False
    req=json.loads((ROOT/'gencase-request.json').read_text(encoding='utf-8'))
    assert req['binding_requirements']['do_not_hardcode_214515'] is True
    assert '214515' not in (ROOT/'initial-qa-manifest.json').read_text(encoding='utf-8')
