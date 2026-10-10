"""Add final findings and create a compact review package from the frozen V1 ZIP."""
from pathlib import Path
import hashlib
import json
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[5]
EXPORT=Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/review-bundles')
BASE=EXPORT/'DS_DATA_02_STAGE2_REVIEW_20261010_V1.zip'

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    names=['FINAL_REPORT_ZH.md','REFERENCE_HASH_AUDIT_ZH.md','REFERENCE_HASH_AUDIT.json',
        'verify_bundle_final.py','build_final_packages.py','FINAL_PACKAGE_START_ZH.md',
        'RESUME_AFTER_REVIEW_ZH.md','CLAIMS_MATRIX.json','REVIEW_HOLD_STATUS.json']
    added={name:(HERE/name).read_bytes() for name in names}
    added['START_HERE_ZH.md']=(HERE/'FINAL_PACKAGE_START_ZH.md').read_bytes()
    add_index={'schema':'ds02.stage2.additive-review-package-members.v1',
        'files':[{'member':n,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in added.items()]}
    outputs=[]
    with zipfile.ZipFile(BASE) as source:
        index=json.loads(source.read('EVIDENCE_INDEX.json'))
        by_path={v['original_path']:v for v in index['files']}
        keep={v['original_path'] for v in index['key_evidence']}
        keep.update(p for p in by_path if '/review-handoff/20261010-closeout-v1/' in p)
        cp='/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/'
        census=json.loads(source.read(by_path[cp+'ROOT434_ACTUAL_H5_CLOSED_CENSUS_V2.json']['member']))
        keep.update(v['actual_proof']['path'] for v in census['base_actual_rows']+census['additional_actual_rows'])
        keep.update(p for p in by_path if any(f'ROOT{n}_' in p or f'VERIFICATION_{n}.json' in p for n in range(711,718)))
        primary=set(keep)
        # Include primary actual bindings, then runtime/source closure of those requests.
        for _ in range(2):
            newly=set()
            for path in list(primary):
                row=by_path.get(path)
                if not row or not path.endswith('.json'):continue
                v=json.loads(source.read(row['member']))
                if not isinstance(v,dict):continue
                for k in ['report','receipt','request','manifest','static_manifest','systemd_evidence',
                        'terminal_cpu_reconciliation','independent_verification','output_manifest','output_evidence_manifest']:
                    item=v.get(k)
                    target=item.get('path') if isinstance(item,dict) else item
                    if isinstance(target,str) and target in by_path:newly.add(target)
                for target in v.get('input_files',[]):
                    if target in by_path and target.endswith(('.py','.json','.xml','.cpp','.h')):newly.add(target)
            keep.update(newly);primary=newly
        for compact,filename in [(True,'DS_DATA_02_STAGE2_REVIEW_20261010_COMPACT.zip'),
                (False,'DS_DATA_02_STAGE2_REVIEW_20261010_V2.zip')]:
            out=EXPORT/filename;assert not out.exists(),out
            view=dict(index)
            if compact:
                view['files']=[v for v in index['files'] if v['original_path'] in keep]
                view['not_in_compact']=[{'path':v['original_path'],'member_in_full_package':v['member'],'reason':'AVAILABLE_IN_FULL_METADATA_PACKAGE'} for v in index['files'] if v['original_path'] not in keep]
                view['coverage_limit']='Compact key evidence and actual bindings only; deep historical context is in V2 full package; scientific arrays excluded in both.'
                view['historical_context_reference_hash_mismatches']=[v for v in index['historical_context_reference_hash_mismatches'] if v['referrer'] in keep]
            view['package_variant']='COMPACT' if compact else 'FULL_V2'
            with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as dest:
                dest.writestr('EVIDENCE_INDEX.json',json.dumps(view,indent=2,ensure_ascii=False)+'\n')
                for record in view['files']:
                    body=source.read(record['member'])
                    assert hashlib.sha256(body).hexdigest()==record['sha256']
                    dest.writestr(record['member'],body)
                dest.writestr('REVIEW_REQUEST_ZH.md',source.read('REVIEW_REQUEST_ZH.md'))
                dest.writestr('SUMMARY_REPORT_ZH.md',source.read('SUMMARY_REPORT_ZH.md'))
                for name,body in added.items():dest.writestr(name,body)
                dest.writestr('ADDITIONAL_FILES.json',json.dumps(add_index,indent=2,ensure_ascii=False)+'\n')
            subprocess.run(['python3','-B',str(HERE/'verify_bundle_final.py'),str(out)],check=True)
            result={'path':str(out),'bytes':out.stat().st_size,'sha256':digest(out),
                'evidence_file_count':len(view['files']),'additional_file_count':len(added),
                'variant':view['package_variant'],'crc_and_sha_verified':True,
                'source_commit_at_export':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
            outputs.append(result);print(json.dumps(result),flush=True)
    result={'schema':'ds02.stage2.final-review-exports.v1','cloud_review_performed':False,
        'scientific_arrays_included':False,'preserved_initial_package_sha256':digest(BASE),'exports':outputs}
    (HERE/'FINAL_EXPORTS.json').write_text(json.dumps(result,indent=2)+'\n')

if __name__=='__main__':main()
