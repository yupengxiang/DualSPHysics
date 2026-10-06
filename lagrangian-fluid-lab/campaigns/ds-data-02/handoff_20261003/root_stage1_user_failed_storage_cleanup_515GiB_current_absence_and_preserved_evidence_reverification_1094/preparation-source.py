import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

R = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics')
H = R / 'lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003'
D = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra')
O = H / 'root_stage1_user_failed_storage_cleanup_515GiB_current_absence_and_preserved_evidence_reverification_1094'

def sha(p):
    p = Path(p)
    assert p.suffix in {'.json', '.jsonl', '.log', '.py'}
    return hashlib.sha256(p.read_bytes()).hexdigest()

def ref(p):
    return {'path': str(p), 'sha256': sha(p)}

rows = []
total_files = total_allocated = 0
for attempt in [D / 'failed-native-cleanup/root-stage1-user-authorized-failed-native-cleanup-root965', D / 'failed-partial-cleanup/root-stage1-user-authorized-failed-unpublished-partial-cleanup-root1054']:
    result_path = attempt / 'cleanup/cleanup-result.json'
    result = json.loads(result_path.read_text())
    receipt_path = attempt / 'execution-receipt.json'
    receipt = json.loads(receipt_path.read_text())
    assert result['status'] == 'completed'
    assert receipt['status'] == 'completed' and receipt['returncode'] == 0
    plan_path = Path(result['plan'])
    assert sha(plan_path) == result['plan_sha256']
    journal_path = attempt / 'cleanup/deleted-files.jsonl'
    journal = [json.loads(line) for line in journal_path.read_text().splitlines()]
    assert len(journal) == result['deleted_files']
    assert sum(x['blocks_bytes'] for x in journal) == result['deleted_allocated_bytes']
    assert all(not os.path.lexists(x['path']) for x in journal)
    preserved = []
    for item in result['attempt_results']:
        if 'original_receipt' in item:
            original = {'path': item['original_receipt'], 'sha256': item['original_receipt_sha256']}
            assert all(Path(p).is_file() for p in item['preserved_frames'])
            assert item['headers_metadata_logs_retained']
        else:
            original = item['original_failed_receipt']
            assert item['failure_metadata_and_logs_retained'] and item['native_raw_untouched']
        assert sha(original['path']) == original['sha256']
        preserved.append({'attempt_id': item['attempt_id'], 'original_failure_receipt': original, 'original_failure_receipt_hash_unchanged': True, 'preserved_native_frames_stat_only': item.get('preserved_frames', [])})
    rows.append({'actual_registered_receipt': ref(receipt_path), 'actual_completed_result': ref(result_path), 'original_plan': ref(plan_path), 'deletion_journal': ref(journal_path), 'deleted_files_still_absent': len(journal), 'allocated_bytes_reclaimed_by_original_execution': result['deleted_allocated_bytes'], 'original_failure_evidence_preserved': preserved})
    total_files += len(journal)
    total_allocated += result['deleted_allocated_bytes']

assert total_files == 15997
st = os.statvfs('/home/jade')
free = st.f_bavail * st.f_frsize
assert free >= 500 * 1024**3
cp_path = H / 'ROOT_LIVE_RESUMPTION_CHECKPOINT_166.json'
cp = json.loads(cp_path.read_text())
assert cp['stage1_visual_accepted_complete_independent_cases'] == 256
report = {'schema': 'ds02.failed-storage-cleanup-current-independent-reverification.v1', 'at_utc': datetime.now(timezone.utc).isoformat(), 'user_authorization': '清理无用且不合格的模拟中间结果，保留有效、待验收、正在运行的结果及失败证据。', 'status': 'original_completed_cleanup_reverified', 'original_cleanup_executions': rows, 'cumulative_deleted_files': total_files, 'cumulative_freed_allocated_bytes': total_allocated, 'cumulative_freed_allocated_GiB': total_allocated / 1024**3, 'Home_free_GiB_current': free / 1024**3, 'Home_required_min_free_GiB': 500, 'Home_floor_pass': True, 'Home_free_changes_with_concurrent_writes': True, 'new_files_deleted_by_this_reverification': 0, 'scientific_payload_contents_read_or_hashed': False, 'accepted_pending_live_and_referenced_outputs_untouched': True, 'Q_N_negative_alone_is_not_a_deletion_reason': True, 'current_completed_case_checkpoint': ref(cp_path), 'current_stage1_visual_accepted_cases': 256, 'precision_status': cp['precision_status'], 'case_credit_from_cleanup': 0, 'resource_counters_not_reset': True, 'next_cleanup_action': 'Bounded delegated fresh151 metadata-only audit of new failed unpublished outputs; any new deletions require exact-file failure, dependency and live-use closure through the existing registered worker.'}
O.mkdir(exist_ok=False)
(O / 'current-cleanup-reverification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
(O / 'preparation-source.py').write_text(Path(__file__).read_text())
print(json.dumps({'report': str(O / 'current-cleanup-reverification.json'), 'freed_GiB': total_allocated / 1024**3, 'absent_files': total_files, 'Home_free_GiB': free / 1024**3}, ensure_ascii=False))
