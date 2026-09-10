"""Keep immutable full evidence locally and compact tracked F3 summaries."""
import hashlib
import json
from scripts.l1r_continuation_evidence import LAB,OUT


def compact(path,keys):
    raw=path.read_bytes();value=json.loads(raw)
    if 'full_report' in value:return
    removed=[k for k in keys if k in value]
    if not removed:return
    digest=hashlib.sha256(raw).hexdigest()
    archive=LAB/'campaigns/l1-resume/data/f3-evidence'/(digest+'.json')
    archive.parent.mkdir(parents=True,exist_ok=True)
    if archive.exists():
        assert archive.read_bytes()==raw
    else:archive.write_bytes(raw)
    for k in removed:value.pop(k)
    value['full_report']={'path':str(archive.relative_to(LAB)),'sha256':digest,'archived_fields':removed,
                          'semantics':'complete original bytes retained; scalar findings and failure decisions unchanged'}
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print(path.name,len(raw),'->',path.stat().st_size,flush=True)


def main():
    for path in OUT.glob('F3_CELL3*-AUDIT.json'):
        compact(path,['mass_distribution_samples','mass_distribution_series','center_of_mass_series'])
    for path in OUT.glob('F3_CELL3*--*-DIAGNOSTIC.json'):compact(path,['rows'])
    path=LAB/'diagnostics/f3-audit/long-nominal-exclusions.json'
    if path.exists():compact(path,['rows','by_particle_id'])


if __name__=='__main__':main()
