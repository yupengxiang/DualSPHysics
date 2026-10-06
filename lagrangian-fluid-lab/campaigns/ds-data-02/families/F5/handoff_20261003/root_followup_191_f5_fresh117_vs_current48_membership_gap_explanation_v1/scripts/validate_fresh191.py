#!/usr/bin/env python3
from __future__ import annotations
import json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(rel): return json.loads((ROOT/rel).read_text())
def main(write=False):
 d=load('metadata/membership-gap-audit.json'); rows=d['rows'];
 checks={}
 checks['source_only_flags']=d['source_only'] and not d['science_payload_read_or_hashed_by_source_agent'] and not d['jobs_started'] and not d['shared_state_modified'] and d['case_credit']==0 and not d['q_n_granted']
 checks['exact_unmatched_count']=len(rows)==10 and len({(x['physical_case_id'],x['physical_condition_sha256']) for x in rows})==10
 checks['six_fresh110']=sum(x['source_roster']=='fresh110_parent_retained_for_fresh117' for x in rows)==6
 checks['four_t120']=sum(x['source_roster']=='fresh117_new_candidate_T120' for x in rows)==4
 checks['all_absent_from_current48']=all(not x['current48_membership_present'] for x in rows)
 checks['all_disabled_prospective']=all(not x['actual_producer_evidence'] and not x['actual_visual_acceptance_evidence'] and not x['accepted_membership_gap_evidence'] for x in rows)
 checks['fresh169_t120_exclusion']=set(d['fresh169_exclusion_declaration']['mother_T120'])=={'M085_T120','M095_T120','M105_T120','M115_T120'}
 checks['fresh169_fresh110_declaration_preserved']=d['fresh169_exclusion_declaration']['fresh110']==[]
 checks['classification']=d['classification_conclusion']['historical_prospective_roster'] and not d['classification_conclusion']['resolution_or_control_replicas'] and not d['classification_conclusion']['rejected_or_failed'] and d['classification_conclusion']['never_visual_accepted'] and not d['classification_conclusion']['genuinely_promised_current48_membership_gap']
 checks['no_science_payload_files']=not any(p.suffix.lower() in ('.bi4','.h5','.csv','.dat','.vtk','.png') for p in ROOT.rglob('*') if p.is_file())
 checks['all_checks']=all(checks.values())
 out={'schema':'ds02.f5.fresh191.validator-report.v1','checks':checks,'all_checks_pass':checks['all_checks'],'source_only':True,'payload_policy':'No scientific payload IO or hashing by source preparation.'}
 if write: (ROOT/'metadata/fresh191-validator-report.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
 print(json.dumps(out,sort_keys=True)); return 0 if checks['all_checks'] else 1
if __name__=='__main__': sys.exit(main('--write-report' in sys.argv[1:]))
