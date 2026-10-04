#!/usr/bin/env python3
"""Build F6 fresh073 by path/hash rebinding of the unchanged fresh071 chain."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

F6WT = Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics')
INTEGRATION = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02')
SOURCE071 = F6WT / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_071_stage1_omega_full241_xmf_native023_render_v1'
ROOT073 = INTEGRATION / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_two_omega_endpoints_actual_gencase_073'
FINAL = F6WT / 'lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_073_stage1_omega_full241_xmf_native023_render_v1'
PARTVTK = Path('/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64')
PVPYTHON = Path('/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython')
PYTHON = F6WT / 'lagrangian-fluid-lab/.venv/bin/python'
STRICT = INTEGRATION / 'lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py'
RUNTIME = INTEGRATION / 'lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py'
GOAL = INTEGRATION / 'lagrangian-fluid-lab/campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md'
CASES = ['F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025']


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + '\n', encoding='utf-8')


def replace_value(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [replace_value(v, replacements) for v in value]
    if isinstance(value, dict):
        # Input-hash maps use absolute paths as dictionary keys. Rebind keys
        # as well as values, otherwise a request can execute the local worker
        # while still authenticating the stale /tmp worker path.
        return {
            replace_value(k, replacements): replace_value(v, replacements)
            for k, v in value.items()
        }
    return value


def xml_bounds(case_id: str, generated_xml: Path, source_xml: Path, generated_hash: str, source_hash: str) -> dict[str, Any]:
    root = ET.parse(generated_xml).getroot()
    pointmin = root.find('.//geometry//pointmin')
    pointmax = root.find('.//geometry//pointmax')
    definition = root.find('.//geometry//definition')
    def vec(node: ET.Element | None) -> list[float]:
        if node is None:
            raise RuntimeError(f'missing XML bounds node for {case_id}')
        return [float(node.get(axis)) for axis in 'xyz']
    if definition is None or abs(float(definition.get('dp')) - 0.025) > 1e-12:
        raise RuntimeError(f'XML dp mismatch for {case_id}')
    return {
        'case_id': case_id,
        'source_definition': str(source_xml),
        'source_definition_sha256': source_hash,
        'generated_xml': str(generated_xml),
        'generated_xml_sha256': generated_hash,
        'pointmin_m': vec(pointmin),
        'pointmax_m': vec(pointmax),
        'dp_m': float(definition.get('dp')),
        'role': 'provenance_only',
        'used_for_camera': False,
        'camera_policy': 'Native023 scans valid native positions through every actual XDMF time; XML bounds are recorded for provenance only and are never placed in the XMF manifest or used as a fixed camera bound.',
    }


def test_text() -> str:
    return r'''#!/usr/bin/env python3
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL = Path('/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/root_followup_073_stage1_omega_full241_xmf_native023_render_v1')
CASES = ['F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025', 'F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025']

def j(path: Path):
    return json.loads(path.read_text())

def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_fresh073_rebind_and_disabled():
    aggregate = j(ROOT / 'strict/aggregate-binding.json')
    assert aggregate['scope_id'].startswith('root_followup_073_')
    assert aggregate['launch'] is False and aggregate['launch_allowed'] is False
    assert len(aggregate['cases']) == 2
    for case in aggregate['cases']:
        cid = case['case_id']
        assert cid in CASES
        owner = Path(case['canonical_owner'])
        assert owner == FINAL / 'owners' / f'{cid}.canonical-owner.json'
        assert owner.is_file() and digest(owner) == case['canonical_owner_sha256']
        xmf_binding = j(ROOT / Path(case['xmf_binding']).relative_to(FINAL))
        render_binding = j(ROOT / Path(case['render_binding']).relative_to(FINAL))
        xmf_request = j(ROOT / Path(case['xmf_request']).relative_to(FINAL))
        render_request = j(ROOT / Path(case['render_request']).relative_to(FINAL))
        for d in [xmf_binding, render_binding, xmf_request, render_request]:
            assert d['launch'] is False and d['launch_allowed'] is False
            assert d['canonical_owner'] == str(owner)
        assert xmf_binding['expected_frames'] == 241
        assert render_binding['expected_frames'] == 241
        assert render_request['output_contract']['all_frames_rendered'] is True
        assert render_request['output_contract']['frame_count'] == 241
        assert render_request['output_contract']['camera_fixed_bounds_forbidden'] is True
        assert render_request['camera_bounds_policy'].startswith('omit fixed camera_bounds/domain_bounds')
        assert 'diagnostic-frames' not in render_request['command']
        assert all(v is None for v in case['xmf_output_hashes'].values())
        assert all(v is None for v in case['render_output_hashes'].values())
        assert xmf_request['output_contract']['xdmf_sha256'] is None
        assert xmf_request['output_contract']['manifest_sha256'] is None
        assert render_request['output_contract']['report_sha256'] is None
        assert render_request['output_contract']['execution_receipt_sha256'] is None
        for request in [xmf_request, render_request]:
            text = json.dumps(request)
            assert '/tmp/f6fresh071' not in text
            assert 'root_followup_071_stage1_omega_full241_xmf_native023_render_v1' not in text
            assert str(FINAL / 'workers') in text
    provenance = j(ROOT / 'provenance/xml-bounds-provenance.json')
    assert all(item['role'] == 'provenance_only' and item['used_for_camera'] is False for item in provenance['cases'])
    assert provenance['camera_policy']['fixed_bounds_in_manifest'] is False

if __name__ == '__main__':
    test_fresh073_rebind_and_disabled()
    print('fresh073 contract: PASS')
'''


def build(out: Path) -> None:
    if out.exists():
        raise RuntimeError(f'output exists: {out}')
    shutil.copytree(SOURCE071, out)
    owner_dir = out / 'owners'
    owner_dir.mkdir(parents=True, exist_ok=True)
    owner_origins: dict[str, dict[str, Any]] = {}
    for case in CASES:
        source_owner = ROOT073 / case / 'canonical-owner.json'
        destination = owner_dir / f'{case}.canonical-owner.json'
        shutil.copy2(source_owner, destination)
        observed = sha(destination)
        expected = sha(source_owner)
        if observed != expected:
            raise RuntimeError(f'canonical owner copy drift: {case}')
        owner_origins[case] = {'path': str(destination), 'sha256': observed, 'byte_equivalent_to_root073_owner': True}
    old_pkg = str(SOURCE071)
    new_pkg = str(FINAL)
    old_tmp = '/tmp/f6fresh071_stage1_omega_full241_xmf_native023_render_v1'
    replacements: list[tuple[str, str]] = [
        (old_pkg, new_pkg),
        (old_tmp, new_pkg),
        ('root_followup_071_stage1_omega_full241_xmf_native023_render_v1', 'root_followup_073_stage1_omega_full241_xmf_native023_render_v1'),
    ]
    for case in CASES:
        old_owner = str(ROOT073 / case / 'canonical-owner.json')
        new_owner = str(FINAL / 'owners' / f'{case}.canonical-owner.json')
        replacements.append((old_owner, new_owner))
    # Update all existing JSON source metadata, including input_sha256 map keys.
    for path in sorted(out.rglob('*.json')):
        write_json(path, replace_value(load(path), replacements))
    # Make the file-list explicit about the local owner copies and fresh073 test.
    old_test = out / 'tests/test_fresh071_contract.py'
    if old_test.exists():
        old_test.unlink()
    new_test = out / 'tests/test_fresh073_contract.py'
    new_test.write_text(test_text(), encoding='utf-8')
    generated = {}
    for case in CASES:
        owner = out / 'owners' / f'{case}.canonical-owner.json'
        # Generated XML comes from the actual DATA GenCase073 direct root.
        attempt = 'root-stage1-f6-0p25-genuine-gencase-073' if case.endswith('S025_DP025') else 'root-stage1-f6-2p0-genuine-gencase-073'
        generated_xml = DATA / 'families/F6' / case / attempt / f'{case}.xml'
        # Use the actual fresh063 source definition bound by the copied owner.
        owner_obj = load(owner)
        source_xml = Path(owner_obj['source_definition'])
        generated[case] = xml_bounds(case, generated_xml, source_xml, sha(generated_xml), sha(source_xml))
    write_json(out / 'provenance/xml-bounds-provenance.json', {
        'schema': 'ds02.f6.stage1.omega.full241.xml-bounds-provenance.v1',
        'scope_id': 'root_followup_073_stage1_omega_full241_xmf_native023_render_v1',
        'family_id': 'F6',
        'cases': [generated[c] for c in CASES],
        'camera_policy': {
            'fixed_bounds_in_manifest': False,
            'xml_bounds_role': 'provenance_only',
            'native_bounds_source': 'Native023 valid positions scanned through every actual XDMF time',
            'xml_bounds_used_for_camera': False,
        },
        'read_policy': 'Generated XML and bounded metadata only; no H5/BI4/CSV/particle arrays read.',
    })
    write_json(out / 'provenance/canonical-owner-provenance.json', {
        'schema': 'ds02.f6.stage1.omega.full241.canonical-owner-local-copy.v1',
        'scope_id': 'root_followup_073_stage1_omega_full241_xmf_native023_render_v1',
        'family_id': 'F6',
        'owners': owner_origins,
        'policy': 'The two Root073 canonical owner JSON files are copied byte-equivalently into the F6 WT so all executable request references resolve locally; physical hashes and source-plan hashes are unchanged.',
    })
    # Keep the builder in the source package so Root can reproduce the exact
    # rebinding and review its path/hash policy. It is source-only and never
    # launches a solver, converter, renderer, or array reader.
    builder = out / 'builders/build_f6_fresh073.py'
    builder.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__), builder)
    # Refresh file list after adding local owners/provenance/test.
    file_list = load(out / 'provenance/file-list.json')
    files = []
    for path in sorted(out.rglob('*')):
        if path.is_file() and path.name != 'file-list.json':
            files.append(str(path.relative_to(out)))
    files.append('provenance/file-list.json')
    file_list['scope_id'] = 'root_followup_073_stage1_omega_full241_xmf_native023_render_v1'
    file_list['files'] = sorted(files)
    file_list['file_count'] = len(files)
    file_list['generated_products_included'] = False
    write_json(out / 'provenance/file-list.json', file_list)
    # README is source-package prose; update scope and describe local copies.
    readme = (out / 'README.md').read_text()
    readme = readme.replace('fresh071', 'fresh073').replace('root_followup_071_stage1_omega_full241_xmf_native023_render_v1', 'root_followup_073_stage1_omega_full241_xmf_native023_render_v1')
    readme += '\nFresh073 path/hash correction: executable worker, binding, request, and canonical-owner references resolve inside the F6 WT. The copied Root073 owners are byte-equivalent. The existing DATA attempt IDs retain the 071 suffix because no XMF or render job has launched. XML point bounds are recorded only in provenance/xml-bounds-provenance.json; Native023 derives camera bounds from valid native positions at every actual XDMF time.\n'
    (out / 'README.md').write_text(readme, encoding='utf-8')
    # Build a concrete source/hash manifest. It excludes itself from package hashes.
    package_files = []
    for path in sorted(out.rglob('*')):
        if path.is_file() and path.name != 'input-hash-binding.json':
            package_files.append({'path': str(FINAL / path.relative_to(out)), 'sha256': sha(path)})
    external = []
    for path in [PYTHON, PARTVTK, PVPYTHON, STRICT, RUNTIME, GOAL]:
        external.append({'path': str(path), 'sha256': sha(path)})
    for case in CASES:
        owner = out / 'owners' / f'{case}.canonical-owner.json'
        external.append({'path': str(FINAL / 'owners' / owner.name), 'sha256': sha(owner)})
        owner_obj = load(owner)
        external.append({'path': owner_obj['source_definition'], 'sha256': owner_obj['source_definition_sha256']})
    # The existing fresh071 binders already contain exact opaque hashes for all actual DATA inputs.
    for rel in ['workers/export_xmf.py', 'workers/render_native023.py', 'workers/bind_actual_render_receipts.py']:
        path = out / rel
        external.append({'path': str(FINAL / rel), 'sha256': sha(path)})
    write_json(out / 'provenance/input-hash-binding.json', {
        'schema': 'ds02.f6.stage1.omega.full241.xmf.native023.input-hash-binding.v1',
        'scope_id': 'root_followup_073_stage1_omega_full241_xmf_native023_render_v1',
        'status': 'source_only_disabled',
        'package_file_count': len(package_files),
        'package_files': package_files,
        'external_inputs': external,
        'future_output_hash_policy': 'XMF, manifest, render, frame, GIF, PVSM and execution-receipt hashes remain null until Root runs the disabled requests.',
        'read_policy': 'JSON/XML and opaque existing receipt/H5 hashes only; no arrays read and no job launched.',
    })
    # Ensure all package-internal paths point at final F6 WT and no temp worker path survives.
    for path in out.rglob('*'):
        if path.is_file() and path.suffix in {'.json', '.md', '.py'}:
            # The reproducibility builder necessarily contains the source and
            # staging path constants used for replacement; it is not an
            # executable request or binding.
            if path == builder:
                continue
            text = path.read_text(encoding='utf-8')
            if old_tmp in text or old_pkg in text:
                raise RuntimeError(f'stale package path remains: {path}')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
    print(args.output)

if __name__ == '__main__':
    main()
