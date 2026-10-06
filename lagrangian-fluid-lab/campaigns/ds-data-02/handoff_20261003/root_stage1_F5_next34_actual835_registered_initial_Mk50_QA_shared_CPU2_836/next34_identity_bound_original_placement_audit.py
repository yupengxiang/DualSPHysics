from pathlib import Path
import sys,json,hashlib,importlib.util
SOURCE=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_103_stage1_f5_c082s1_typed_xmf_bed_binding_disabled_v1/workers/initial_placement_mk50_audit.py')
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()=='105ce558f345fda553f5e659e3d1af3ae7addd5a960f25f8f9622abbb8e7503d'
spec=importlib.util.spec_from_file_location('f5_original_placement_audit',SOURCE);audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
if '--check' not in sys.argv:
 assert '--binding' in sys.argv
 b=json.loads(Path(sys.argv[sys.argv.index('--binding')+1]).read_text())
 plan=json.loads(Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F5_next34_distinct_inside_visual_range_source_preparation_823/source-plan.json').read_text())
 cases={c['case_id']:c for c in plan['candidates']};assert len(cases)==34 and b['case_id'] in cases
 c=cases[b['case_id']];assert b['physical_case_id']==c['physical_case_id'] and b['physical_condition_sha256']==c['physical_condition_sha256']
 audit.CASE=b['case_id']
raise SystemExit(audit.main())
