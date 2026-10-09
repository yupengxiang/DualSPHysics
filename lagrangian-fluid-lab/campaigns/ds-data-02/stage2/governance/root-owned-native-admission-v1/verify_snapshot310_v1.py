#!/usr/bin/env python3
"""Independently verify small ROOT310 snapshot metadata and full parent CPU."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / 'root-owned-lifecycle-continuation-v1/root_common_verification.py'
exec(COMMON.read_text(), globals())


def sha(path):
    path = Path(path)
    assert path.suffix.lower() not in {'.bi4', '.obi4', '.ibi4', '.h5', '.hdf5', '.vtk', '.jsonl'}
    assert path.stat().st_size <= 10485760
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    global num, name, qp, q, b, r, p
    num = '310'
    name = 'native-selected-source-snapshot'
    qp = S / 'requests/native-selected-source-snapshot-root-forward-310-001.json'
    q, b, r, p = common(qp)
    report_path = b / 'native_selected_source_snapshot_v2.json'
    report = load(report_path)
    assert report['schema'] == 'ds02.stage2.native-source-snapshot.v2'
    assert report['status'] == 'PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE'
    scope = report['worker_scope']
    assert scope['selected_request_count'] == 2 and scope['selected_file_count'] == 10
    assert scope['pre_post_stat_consistency'] is True
    assert not scope['bi4_decode'] and not scope['hdf5_read'] and not scope['solver_launch']
    assert scope['full_raw_tree_scan'] == 'FORBIDDEN'
    actual_records = []
    expected_templates = {
        q['source_binding']['same_template']['path']: q['source_binding']['same_template'],
        q['source_binding']['half_template']['path']: q['source_binding']['half_template'],
    }
    assert {entry['observer_request']['path'] for entry in report['requests']} == set(expected_templates)
    for entry in report['requests']:
        template_path = entry['observer_request']['path']
        template = load(template_path)
        assert sha(template_path) == entry['observer_request']['sha256'] == expected_templates[template_path]['sha256']
        assert entry['case_id'] == template['case_id']
        assert entry['family_id'] == template['family_id'] == 'F1'
        assert entry['physical_case_id'] == template['physical_case_id']
        assert entry['selected_native_frame_ids'] == template['selected_native_frame_ids'] == [0, 49, 50, 99, 100]
        assert entry['raw_root'] == template['source_binding']['raw_root']
        selected = entry['selected_native_files']
        assert len(selected) == 5 and [item['frame'] for item in selected] == entry['selected_native_frame_ids']
        for item in selected:
            path = Path(item['path'])
            assert path.parent == Path(entry['raw_root'])
            assert path.name == f"Part_{item['frame']:04d}.bi4"
            assert item['path'] in q['deferred_input_files'] and item['path'] not in q['input_files']
            assert item['stat_before'] == item['stat_after']
            assert item['stat_consistency'] == 'PASS_PRE_POST_IDENTICAL'
            st = path.stat()
            current_stat = {'bytes': st.st_size, 'mtime_ns': st.st_mtime_ns,
                            'ctime_ns': st.st_ctime_ns, 'st_dev': st.st_dev, 'st_ino': st.st_ino}
            assert current_stat == item['stat_after']
            assert item['bytes'] == st.st_size and item['mtime_ns'] == st.st_mtime_ns
            assert len(item['sha256']) == 64
        entry_list = [{k: item[k] for k in ['frame', 'path', 'bytes', 'sha256']} for item in selected]
        digest = hashlib.sha256(json.dumps(entry_list, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        assert digest == entry['selected_source_sha256']
        assert sum(item['bytes'] for item in selected) == entry['selected_native_bytes']
        actual_records.extend(entry_list)
    assert len(actual_records) == len({item['path'] for item in actual_records}) == 10
    assert report['immutable_source_sha_list'] == actual_records
    total = sum(item['bytes'] for item in actual_records)
    assert total == report['selected_native_total_bytes'] == q['estimated_native_read_bytes'] == 57358780
    digest = hashlib.sha256(json.dumps(actual_records, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert digest == report['source_sha_list_digest']
    assert all(report['scientific_qualification'][k] == 'UNKNOWN' for k in ['QI', 'QN', 'QE'])
    p.update(status='VERIFIED_ACTUAL_F1_S2_TEN_SELECTED_NATIVE_SOURCE_SINGLE_STREAM_SHA_STAT_ONLY_NO_Q',
             report=str(report_path), report_sha256=sha(report_path), selected_native_total_bytes=total,
             selected_file_count=10, source_sha_list_digest=digest, selected_source_stat_recheck=True,
             root_payload_content_read=False, qualification_credit='selected source provenance only',
             worker_native_content_scope='one stream SHA per selected file with stable pre/post stat; no decode',
             native_field_audit=False, old_products_unchanged=True)
    footer = (HERE.parent / 'root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py').read_text()
    footer = footer.replace('F7_S1_SOURCE_SUPPORT_ACTUAL_SCOPE_ROOT_VERIFICATION_137.json',
                            'F1_S2_TEN_SELECTED_SOURCE_SNAPSHOT_ACTUAL_ROOT_VERIFICATION_310.json')
    exec(footer, globals())


if __name__ == '__main__':
    main()
