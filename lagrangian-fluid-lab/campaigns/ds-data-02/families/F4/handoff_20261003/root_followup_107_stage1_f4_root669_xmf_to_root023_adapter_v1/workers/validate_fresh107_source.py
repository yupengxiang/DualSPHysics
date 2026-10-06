#!/usr/bin/env python3
"""Static fresh107 package validator; no job or scientific payload access."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
RAW={'.bi4','.h5','.hdf5','.vtk','.vtu','.vtp','.csv','.dat'}
def load(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--package',type=Path,required=True); p=ap.parse_args().package.resolve()
    m=load(p/'manifest.json'); idx=load(p/'requests/index.json'); assert m['case_count']==24 and m['request_count']==24 and m['typed_request_count']==0 and idx['all_disabled'] and len(idx['requests'])==24
    sys.path.insert(0,str(p/'workers')); from verify_root669_xmf_render_binding import preflight_render_binding,preflight_root669_xmf_binding
    cases=set()
    for row in idx['requests']:
        assert row['kind']=='render' and row['disabled'] is True
        q=load(Path(row['path'])); cases.add(q['case_id']); assert q['disabled'] and not q['execution_allowed'] and not q['launch'] and not q['launch_allowed']
        assert q['source_only'] and not q['jobs_started_by_source'] and q['shared_registry_write_by_source'] is False
        assert q['case_xmf'] is None and q['manifest'] is None and '{root669_manifest}' in q['deferred_input_files']
        assert all(v is None for v in q['future_hashes'].values()) and all(v is None for v in q['deferred_input_sha256'].values())
        assert q['cpu_threads']==24 and q['queue_barrier']['global_render_cap']==2 and q['queue_barrier']['root638_global_render_drain_required']
        for x in q['input_files']: assert Path(x).suffix.lower() not in RAW
        for x in q['command']: assert 'fresh105' not in str(x).lower() and 'fresh106' not in str(x).lower()
    assert len(cases)==24
    xb_cases=set(); rb_cases=set()
    for bp in sorted((p/'bindings').glob('*.root669-xmf-binding.json')):
        b=load(bp); xb_cases.add(b['case_id']); assert preflight_root669_xmf_binding(b)['status'].startswith('WAIT')
        assert all(v is None for v in b['future_hashes'].values())
    for bp in sorted((p/'bindings').glob('*.root669-render-binding.json')):
        b=load(bp); rb_cases.add(b['case_id']); assert preflight_render_binding(b)['status'].startswith('WAIT')
        assert all(v is None for v in b['future_hashes'].values())
    assert xb_cases==rb_cases==cases
    assert not list((p/'requests').glob('*typed*'))
    assert 'subprocess' not in (p/'workers/verify_root669_xmf_render_binding.py').read_text()
    print('fresh107 source contract: PASS (24 registered Root669 plans, 24 WAIT XMF bindings, 24 disabled Root023 successors, render-drain barrier)')
if __name__=='__main__': main()
