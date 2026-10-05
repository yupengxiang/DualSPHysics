#!/usr/bin/env python3
"""Metadata/AST-only verifier for F5 fresh074.
It never opens BI4/H5/CSV arrays and never starts a process.
"""
import ast,hashlib,json,xml.etree.ElementTree as ET
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def check_req(name):
 d=json.loads((root/name).read_text()); assert d['launch_allowed'] is False and d['execution_allowed'] is False; assert d['root_inventory_policy_source_sha256']=='2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5'; assert not any('resource-ledger.json' in p for p in d['input_files']); assert d['actual_counts']['total_particles']==174896 and d['actual_counts']['fluid_particles']==40710; assert d['actual_generated_xml'].endswith('F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071.xml'); assert d['actual_gencase_receipt_sha256']=='52ce589ee3cb51136daf7188c0cedbc5a43999e28ee13557942d646d115c56dd'; return d
qa=check_req('initial-qa-request.json'); cov=check_req('central-fixed-bed-coverage-request.json'); down=json.loads((root/'downstream-disabled.json').read_text()); assert down['all_downstream_disabled'] and down['full801_authorized'] is False
actual=json.loads((root/'actual-gencase-binding.json').read_text()); assert actual['actual_counts']['total_particles']==174896; assert actual['files']['generated_xml']['path'].endswith('.xml') and not actual['files']['generated_xml']['path'].endswith('_Def.xml'); assert actual['root_inventory_policy_source_sha256']=='2649eedbcf4816f8d2fa7b2182828ea8b3ce107ef47f25c56780d29c5138def5'
for name in ('initial_qa_worker.py','central_fixed_bed_coverage_worker.py','reference_initial_fixed_bed_distribution_audit.py'):
 ast.parse((root/'workers'/name).read_text())
coverage=(root/'workers/reference_initial_fixed_bed_distribution_audit.py').read_text().lower(); wrapper=(root/'workers/central_fixed_bed_coverage_worker.py').read_text(); qa_text=(root/'workers/initial_qa_worker.py').read_text();
for key in ('surface_half_dp_mid_y_count','below_profile_count','below_profile_fraction','no_initial_fluid_below_profile','uid_and_finite','spatial_overlap','mixed_boundary_cohort_warning','bed_only_claim'):
 assert key in coverage, key
assert 'mother' not in coverage; assert 'no_mother_case_assumption' in wrapper; assert 'actual_fluid_count_source' in wrapper; assert 'no_expected_fluid_substitution' in wrapper; assert 'fixed_moving_fluid_spatial_no_overlap' in qa_text
for name in ('initial-qa-request.json','central-fixed-bed-coverage-request.json'):
 d=json.loads((root/name).read_text());
 for p,h in d['input_sha256'].items():
  if p.endswith('.bi4'): assert h=='04a06a16368948f3926c24645232cf38b2b129f55ca5c91fee082759b22ba846'; continue
  assert sha(p)==h,p
print(json.dumps({'status':'metadata_ast_pass','qa_inputs':len(qa['input_files']),'coverage_inputs':len(cov['input_files']),'arrays_opened':False,'jobs_started':False},sort_keys=True))
