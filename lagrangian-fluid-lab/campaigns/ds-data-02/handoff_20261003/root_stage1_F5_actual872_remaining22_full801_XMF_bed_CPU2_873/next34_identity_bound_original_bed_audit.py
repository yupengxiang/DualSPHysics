from pathlib import Path
import importlib.util,json,sys
R=Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics');L=R/'lagrangian-fluid-lab';H=L/'campaigns/ds-data-02/handoff_20261003'
original=L/'campaigns/ds-data-02/families/F5/handoff_20261003/root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1/workers/bed_audit_full801_fresh138.py'
plan=json.loads(next(H.glob('root*823/source-plan.json')).read_text());bp=Path(sys.argv[sys.argv.index('--binding')+1]);b=json.loads(bp.read_text());matches=[c for c in plan['candidates'] if c['case_id']==b['case_id']];assert len(matches)==1;c=matches[0];assert b['physical_case_id']==c['physical_case_id'] and b['physical_condition_sha256']==c['physical_condition_sha256'] and b['source_plan_physical_condition_sha256']==c['source_xml_sha256']
spec=importlib.util.spec_from_file_location('original_fresh138_full801_bed_audit',original);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.CASE_ID=c['case_id'];raise SystemExit(m.main())
