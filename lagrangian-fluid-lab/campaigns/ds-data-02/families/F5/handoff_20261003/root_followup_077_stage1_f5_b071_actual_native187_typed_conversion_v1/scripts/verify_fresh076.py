#!/usr/bin/env python3
from __future__ import annotations
import ast, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071')
GEN = DATA/'root-stage1-f5-b071-genuine-gencase-163'
QA = DATA/'root-stage1-f5-b071-initial-qa-output-root-binding-repair-175'
COV = DATA/'root-stage1-f5-b071-native-bed-marker-mapping-repair-185'
PKG = '/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_076_stage1_f5_b071_short_native_qualification_typed_xmf_render_v1'
SHORT_ID = 'root-stage1-f5-b071-short-native-qualification-076'
TYPED_ID = 'root-stage1-f5-b071-short-native-typed-nvme-076'
GEN_RECEIPT = GEN/'execution-receipt.json'
XML = GEN/'prepared/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071.xml'
PREP_REPORT = GEN/'prepared/prepared-input-report.json'
QA_RECEIPT = QA/'execution-receipt.json'
QA_PROV = QA/'initial-qa/b071-initial-qa-provenance.json'
QA_NATIVE = QA/'initial-qa/native-initial-qa.json'
COV_RECEIPT = COV/'execution-receipt.json'
COV_REPORT = COV/'initial-bed-coverage/b071-direct-native-initial-fixed-bed-coverage.json'
EXPECTED = {
    'gen_receipt':'52ce589ee3cb51136daf7188c0cedbc5a43999e28ee13557942d646d115c56dd',
    'xml':'9abb26c6a364618f588038410c748606ec481aaf61ea2f9a9cd235143ca8af90',
    'prepared_report':'2feda3e5c52f6c26781cafe9cc1ea70ba637b85ff5709a177eed6d1d846b8287',
    'qa_receipt':'d5ff39fe430b0dc2047cd6489dd8e1d2384fd1330c7527ad4f7a3ee50eb0e268',
    'qa_provenance':'ff00983f227e745616d2a1d28f81a2c3a038e27a9ace7c1baca85d7c212cc555',
    'qa_native':'c132ce3182bcde70467046733130d20d35adab61863effc0c460e2f49401e433',
    'cov_receipt':'74cfb6c7e690c8572c0387e2e5c343d9a3a61018b5efc4224d3cf729b1fad818',
    'cov_report':'d6f99d4830accac0b97315d4707cc7009434e8fc6084b1af0c59dc08731c575d',
}

def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()

def load(p: Path):
    with p.open(encoding='utf-8') as f:
        return json.load(f)

def require(cond, msg):
    if not cond:
        raise AssertionError(msg)

def receipt_case_id(receipt):
    req = receipt.get('request') if isinstance(receipt.get('request'), dict) else {}
    return receipt.get('case_id') or req.get('case_id')

def check_receipt(path, expected_sha, case_id):
    require(path.is_file(), f'missing receipt {path}')
    require(sha(path) == expected_sha, f'receipt hash mismatch {path}')
    x = load(path)
    require(x.get('schema') == 'ds02.execution-receipt.v1', f'receipt schema {path}')
    require(x.get('status') == 'completed' and x.get('returncode') == 0, f'receipt not completed {path}')
    require(receipt_case_id(x) == case_id, f'receipt identity {path}')
    return x

binding = load(ROOT/'binding.json')
gate = load(ROOT/'root185-coverage-binding.json')
short = load(ROOT/'short-native-qualification-request.json')
typed = load(ROOT/'typed-conversion-request-template.json')
xmf_binding = load(ROOT/'xmf-binding-template.json')
xmf_req = load(ROOT/'xmf-request-template.json')
bed_binding = load(ROOT/'short-bed-audit-binding-template.json')
bed_req = load(ROOT/'short-bed-audit-request.json')
render_req = load(ROOT/'render-request-template.json')
downstream = load(ROOT/'downstream-disabled.json')
chain = load(ROOT/'source-chain.json')
manifest = load(ROOT/'manifest.json')
case_id = 'F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071'
require(binding['case_id'] == case_id and binding['physical_condition_sha256'] if 'physical_condition_sha256' in binding else True, 'binding identity')
require(binding['source_plan']['source_definition_sha256'] == 'e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72', 'source plan hash')
require(binding['source_plan']['canonical_physical_condition_sha256'] == 'd791355fcb5d8562a45ecdbee1772b1039f2fe8e6534760734509b51511c5d3f', 'canonical hash')
require(binding['source_plan']['source_definition_sha256'] != binding['source_plan']['canonical_physical_condition_sha256'], 'source/canonical hashes collapsed')
require(binding['source_geometry_contract']['source_mkbound_bed_marker'] == 40, 'source marker')
require(binding['source_geometry_contract']['native_emitted_bed_marker'] == 50, 'native marker')
require(binding['actual_counts'] == {'fixed_particles':130392,'moving_particles':3794,'fluid_particles':40710,'floating_particles':0,'total_particles':174896,'solver_dimension':3}, 'actual counts')

# Actual metadata identity: only small JSON/XML is opened. BI4/CSV/H5 are deliberately opaque here.
gen = check_receipt(GEN_RECEIPT, EXPECTED['gen_receipt'], case_id)
qa = check_receipt(QA_RECEIPT, EXPECTED['qa_receipt'], case_id)
cov = check_receipt(COV_RECEIPT, EXPECTED['cov_receipt'], case_id)
require(sha(XML) == EXPECTED['xml'], 'generated XML hash')
require(sha(PREP_REPORT) == EXPECTED['prepared_report'], 'prepared report hash')
require(sha(QA_PROV) == EXPECTED['qa_provenance'], 'QA provenance hash')
require(sha(QA_NATIVE) == EXPECTED['qa_native'], 'QA native report hash')
require(sha(COV_REPORT) == EXPECTED['cov_report'], 'Root185 report hash')
qa_prov = load(QA_PROV)
require(qa_prov.get('schema') == 'ds02.f5.b071.actual-initial-qa.v1', 'QA provenance schema')
require(qa_prov.get('status') == 'actual_native_qa' and qa_prov.get('all_actual_checks_pass') is True, 'QA actual status')
require(qa_prov.get('full_solver_authorized') is False, 'QA promoted solver')
expected_counts = {key: binding['actual_counts'][key] for key in ('fixed_particles','moving_particles','fluid_particles','total_particles','solver_dimension')}
require(all(qa_prov.get('actual_counts', {}).get(key) == value for key, value in expected_counts.items()), 'QA counts')
require(gen.get('total_particles') == 174896 and gen.get('fluid_particles') == 40710 and gen.get('solver_dimension_from_gencase') == 3, 'GenCase actual counts')
require(qa.get('request', {}).get('actual_counts', {}).get('total_particles') == 174896, 'QA receipt actual count')
require(all(value is True for value in qa_prov.get('checks', {}).values()), 'QA checks')
coverage = load(COV_REPORT)
require(coverage.get('schema') == 'ds02.f5.b071.root175-csv-initial-fixed-bed-coverage.v2', 'Root185 report schema')
require(coverage.get('status') == 'completed_root175_csv_frame0_diagnostic', 'Root185 report status')
require(coverage.get('audit_contract', {}).get('bed_marker_mk') == 50, 'coverage native marker')
require(coverage.get('audit_contract', {}).get('actual_type0_mk50_filter') is True, 'coverage filter')
segments = coverage.get('central_fixed_bed_support', {}).get('segments', [])
require(len(segments) == 6, 'six coverage segments')
counts = [s['surface_bands']['surface_half_dp']['central_abs_y_le_0p01_count'] for s in segments]
require(counts == [10,13,18,15,20,20], f'coverage counts {counts}')
require(all(n > 0 for n in counts), 'positive central support')
require(coverage['central_fixed_bed_support']['actual_type0_mk50_support_count'] == 11724, 'Mk50 support')
require(coverage['fluid_initial_profile_separation']['below_profile_count'] == 0, 'initial fluid below profile')
require(coverage['frame_zero']['row_count'] == 174896 and coverage['frame_zero']['solver_dimension'] == 3, 'frame zero metadata')
require(coverage['interpretation_boundary']['full801_remains_disabled'] is True, 'coverage full801 gate')
require(coverage['interpretation_boundary']['dynamic_solver_cause_unassigned'] is True, 'coverage causal boundary')

# Generated XML semantic mapping is checked as text, without opening BI4.
xml_text = XML.read_text(encoding='utf-8')
require('<fixed mkbound="30" mk="40" begin="7728" count="102944" />' in xml_text, 'native Mk40 sidewall mapping')
require('<fixed mkbound="40" mk="50" begin="110672" count="19720" />' in xml_text, 'native Mk50 bed mapping')
require('<drawfilestl file="assets/f5_compact_continuous_bed_profile.stl" autofill="true" />' in xml_text, 'B STL autofill source')

# Every future request is disabled and free of live ledger dependencies.
for name, req in [('short', short), ('typed', typed), ('xmf', xmf_req), ('bed', bed_req), ('render', render_req)]:
    require(req.get('launch_allowed') is False and req.get('execution_allowed') is False, f'{name} request enabled')
    require(req.get('full16_authorized') is False and req.get('full801_authorized') is False, f'{name} full gate')
    require(not any('resource-ledger.json' in str(item) for item in req.get('input_files', [])), f'{name} live ledger')
    require(req.get('independent_case_count_increment') == 0, f'{name} case count')
    require(req.get('root_review_required') is True, f'{name} root review')
for stage, item in downstream['stages'].items():
    require(item.get('launch_allowed') is False and item.get('execution_allowed') is False, f'downstream enabled {stage}')
require(downstream['stages']['full801_native']['full801_authorized'] is False, 'downstream full801')
require(short['cwd'] == str(GEN/'prepared'), 'solver cwd must be GenCase prepared dir')
require(short['command'][-2:] == ['-tmax:1.0','-tout:0.02'], 'short solver time bounds')
require(short['native_bed_mapping_required'] == {'source_mkbound':40,'native_mk':50,'filter_type':0,'do_not_filter_native_mk40':True}, 'short marker gate')
require(len(short['all_saved_frames_contract']['frame_indices']) == 51, 'short frame contract')
require(short['all_saved_frames_contract']['uniform_time_spacing_assumption'] is False, 'time assumption')
for req in (typed, xmf_req, bed_req, render_req):
    require(not any(str(item).lower().endswith(('.csv','.h5','.bi4','.xmf','.xdmf')) for item in req.get('input_files', [])), 'future array input registered as source input')
require(short['generated_bi4_hash_is_producer_declared'] is True, 'BI4 provenance')
require(short['array_policy']['source_agent_opened_bi4'] is False and short['array_policy']['source_agent_opened_csv'] is False and short['array_policy']['source_agent_opened_h5'] is False, 'source array policy')

# Binding templates keep actual and future receipt roles distinct.
require(xmf_binding['gencase_receipt'] == str(GEN_RECEIPT), 'XMF GenCase role')
require(xmf_binding['native_receipt'].endswith(SHORT_ID+'/execution-receipt.json'), 'XMF native role')
require(xmf_binding['typed_receipt'].endswith(TYPED_ID+'/execution-receipt.json') if 'TYPED_ID' in globals() else True, 'XMF typed role')
require(xmf_binding['native_receipt_sha256'] is None and xmf_binding['typed_receipt_sha256'] is None, 'future receipt hashes')
require(bed_binding['native_bed_marker_mk'] == 50 and bed_binding['source_bed_marker_mkbound'] == 40, 'bed binding markers')
for future in ('short_solver_receipt_sha256','native_conversion_report_sha256','trajectory_h5_sha256','xdmf_sha256'):
    require(bed_binding.get(future) is None, f'future bed hash {future}')
require(render_req['renderer']['all_frame_indices'] == list(range(51)), 'render frames')
require(render_req['renderer']['software_rendering'] is True, 'render mode')

# AST checks catch malformed workers and the known bad hash sentinel pattern.
for rel in ('workers/bed_audit.py','workers/export_xmf.py','workers/render_full_saved_animation.py','scripts/verify_fresh076.py'):
    source = (ROOT/rel).read_text(encoding='utf-8')
    ast.parse(source, filename=rel)
    require('hashlib' in source and 'read(' in source, f'hash helper absent {rel}')
    if rel != 'scripts/verify_fresh076.py':
        require('UnboundLocalError' not in source, f'known hash sentinel bug {rel}')
require('for b in iter(lambda:f.read(1024*1024),b)' not in (ROOT/'workers/bed_audit.py').read_text(), 'known hash sentinel bug')
require('subprocess.run' not in (ROOT/'workers/bed_audit.py').read_text(), 'bed worker launches subprocess')

# Package file manifest is local-only; actual array products never enter it.
for rel, expected in manifest['files'].items():
    p = ROOT/rel
    require(p.is_file(), f'manifest file missing {rel}')
    require(sha(p) == expected, f'manifest hash mismatch {rel}')
require('manifest.json' not in manifest['files'], 'manifest self-cycle')
print(json.dumps({'status':'metadata_ast_pass','actual_gen_case':'completed0','actual_root175_qa':'completed0_all_checks','actual_root185_coverage':'completed0_native_mk50','root185_surface_half_dp_counts':counts,'root185_initial_fluid_below_profile':0,'short_request_disabled':True,'typed_xmf_bed_render_disabled':True,'full801_authorized':False,'arrays_opened_by_source_prep':False,'jobs_started':False},sort_keys=True))
