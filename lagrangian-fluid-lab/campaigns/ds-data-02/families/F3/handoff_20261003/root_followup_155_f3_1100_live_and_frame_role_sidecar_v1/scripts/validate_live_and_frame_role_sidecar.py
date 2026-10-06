#!/usr/bin/env python3
"""Metadata-only validator for fresh155; never opens scientific payloads."""
from pathlib import Path
import hashlib, json
HERE=Path(__file__).resolve().parents[1]; SIDE=HERE/'metadata/live-and-frame-role-sidecar.json'
FORBIDDEN={'.h5','.bi4','.csv','.dat','.vtk','.xmf','.hdf5','.png','.gif','.pvsm'}
def sha(p):
    assert p.suffix.lower() not in FORBIDDEN, f'payload hash refused: {p}'
    return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    d=json.loads(SIDE.read_text()); assert d['schema']=='ds02.f3.fresh155.live-and-frame-role-sidecar.v1'
    p=d['policy']; assert all(p[k] is False for k in ('jobs_started','jobs_restarted','jobs_stopped','shared_index_or_ledger_modified','science_payload_opened_or_hashed','view_image_performed','source_requests_modified','receipts_modified'))
    assert d['summary']['frame_role_cases']==5 and d['summary']['request_expected_frames_distinct_values']==[801] and d['summary']['wrapper_expected_frames_distinct_values']==[836] and d['summary']['live_handle']=='1100'
    assert d['live_handle_1100']['receipt_status']=='running' and d['live_handle_1100']['visual_review_eligible'] is False and d['live_handle_1100']['view_image_performed'] is False and len(d['live_handle_1100']['process_chain'])==3
    assert {c['handle'] for c in d['frame_role_cases']}=={'987','1031','1033','1046','1047'}
    for c in d['frame_role_cases']:
        assert c['request_contract']['expected_frames']==801 and c['loaded_wrapper_contract']['expected_frames']==836 and c['request_contract']['command_passes_wrapper_json'] is True
        assert c['upstream_review_contract']['all836_geometry_and_velocity_N3_and_exact_actual_times'] is True and c['upstream_review_contract']['all836_native_UIDs_present'] is True
        assert c['visual_review_eligible'] is False and c['view_image_performed'] is False
        for r in d['source_metadata_refs']:
            if r['case_id']==c['case_id']:
                q=Path(r['path']); assert q.exists() and q.suffix.lower() not in FORBIDDEN and sha(q)==r['sha256'], f'metadata changed after capture: {q}'
    print('fresh155 metadata validator: PASS (1100 preserved live; 801 envelope vs 836 wrapper role recorded)')
if __name__=='__main__': main()
