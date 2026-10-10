"""Retain V11 copy/guard checks and independently bind the exact V13 slot."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

HERE=Path(__file__).resolve().parent;S=HERE.parents[1];LAB=S.parents[2]
OLD=S/'governance/root-owned-portable-admission-v1'
sys.path.insert(0,str(OLD))
from external_storage_v1 import small

def main():
    qp=Path(sys.argv[1]).absolute();q,qsha=small(qp)
    root=Path(q['storage_scope']['external_filesystem'])
    v14path=root/'reports/root242-v14-recursive-executor-report.json'
    v14,v14sha=small(v14path)
    assert v14['schema']=='ds02.stage2.f2-root242-portable-typed-executor-report.v14'
    assert v14['status']=='COMPLETE_ROOT242_V14_RECURSIVE_SOURCE_CLOSURE'
    assert v14['request']=={'path':str(qp),'file_sha256':qsha}
    canonical14=dict(v14);canonical14.pop('sha256')
    assert hashlib.sha256(json.dumps(canonical14,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()==v14['sha256']
    assert v14['role_count']==491 and v14['recursive_preflight']['role_count']==489
    assert v14['recursive_preflight']['file_sha256']==q['root242_v14_preflight_binding']['file_sha256']
    assert v14['recursive_preflight']['path']==q['root242_v14_preflight_binding']['path']
    assert v14['recursive_preflight']['document_count']==8 and v14['recursive_preflight']['nested_rewrite_documents']==8
    assert v14['execution']['original_path_fallback']=='REJECT' and v14['portable_cold_replay_credit']=='NOT_CLAIMED'
    slotpath=root/'reports/root242-v13-output-slot-report.json';slot,slotsha=small(slotpath)
    assert slot['schema']=='ds02.stage2.f2-root242-portable-typed-executor-report.v13'
    assert v14['base_v13']['report_path']==str(slotpath) and v14['base_v13']['report_file_sha256']==slotsha and v14['base_v13']['status']==slot['status']
    assert slot['status']=='COMPLETE_ROOT242_V13_OUTPUT_SLOT_REBOUND'
    assert slot['request']=={'path':str(qp),'file_sha256':qsha}
    canonical=dict(slot);canonical.pop('sha256')
    assert hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()==slot['sha256']
    bound=q['root242_v13_output_slot'];a=slot['output_slot']
    for k in ['replacement_pointer','old_source_path','target_relative_path']:assert a[k]==bound[k]
    assert a['replacement_pointer']=='/v12_forward/output_root_rebind_v14/path' and a['target_relative_path']=='products'
    assert a['old_path_role']=='HISTORICAL_PROVENANCE_ONLY' and a['output_root']==str(root)
    assert a['launcher_source_path']==q['root242_v13_source_binding']['path']
    assert a['launcher_source_sha256']==q['root242_v13_source_binding']['sha256']
    assert slot['execution']['original_path_fallback']=='REJECT' and slot['portable_cold_replay_credit']=='NOT_CLAIMED'
    basepath=root/slot['base_v11_report']['target_relative_path'];base,bsha=small(basepath)
    assert bsha==slot['base_v11_report']['sha256'] and base['status']==slot['base_v11_report']['status']
    c,_=small(q['root213_metadata_contract']['path']);assert len(c['root242_source_binding']['roles'])==491
    source=OLD/'verify_actual_v1.py';raw=source.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='06247c1d05fc1c2b2248c04efcda2df54e1257ceda827fbb2d3d1867306c6de9'
    text=raw.decode()
    replacements={"and len(roles) == report['role_count'] == 49":"and len(roles) == report['role_count'] == 491",'selected_role_count=49':'selected_role_count=491','root242-external-storage-evidence-v1.json':'root242-v14-recursive-source-external-storage-evidence-v1.json','PORTABLE_TYPED_V11_ACTUAL_ROOT_VERIFICATION_242.json':'PORTABLE_TYPED_V14_ACTUAL_ROOT_VERIFICATION_242.json',"name='portable-typed-v11'":"name='portable-typed-v14'","status='VERIFIED_ACTUAL_ROOT242_PORTABLE_V11_METADATA_RUNTIME_GUARD_NO_COLD_REPLAY_Q'":"status='VERIFIED_ACTUAL_ROOT242_PORTABLE_V14_RECURSIVE_SOURCE_RUNTIME_GUARD_NO_COLD_REPLAY_Q'"}
    for old,new in replacements.items():assert text.count(old)==1,old;text=text.replace(old,new)
    marker="context.update(q=q,b=base,r=receipt,p=proof,qp=qp,num='242'"
    assert text.count(marker)==1
    inject="proof.update(v13_output_slot_report="+repr(str(slotpath))+", v13_output_slot_report_sha256="+repr(slotsha)+", exact_output_slot_rebound=True, failed_v11_partial_copies_preserved=True); "
    inject=inject.replace('); ', ', v14_recursive_report='+repr(str(v14path))+', v14_recursive_report_sha256='+repr(v14sha)+', actual_executor_version=14, complete_recursive_role_count=491, failed_v13_partial_copy_preserved=True); ')
    text=text.replace(marker,inject+marker)
    exec(compile(text,str(source),'exec'),{'__name__':'__main__','__file__':str(source)})

if __name__=='__main__':main()
