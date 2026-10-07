from __future__ import annotations
import argparse, hashlib, json, re, shutil, stat
from pathlib import Path
CP = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/ROOT_LIVE_RESUMPTION_CHECKPOINT_320.json')
INDEX = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_source223_actualF2_RX061ROT090_original1119_full401QI_personal26PNG_open_rim_dispersion_one_UID_omission_truthful_visual_acceptance_1432/full336-current330-actual-final48-delivery-progress-index.json')
LEGACY = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_source174_F5_final48_current30accepted18pending_own801_bed_raw_roles_two_original_runtime_receipt_recoveries_four_publish_absences_1344/F5-FINAL48-CURRENT30ACCEPTED18PENDING-ACTUAL801-PRIMARY-BED-DELIVERY.json')
RECOVERY = Path('/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actualXMF506_and_bed508_short51_root023_render_511/actual-root-short51-render-preflight-review.json')
ROOT = Path('/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5')
META_SUFFIXES = {'.json', '.xml', '.xmf', '.py', '.md', '.txt', '.yaml', '.yml'}
PNG_RE = re.compile(r'(?:^|/)all_frames_(\d{3})\.png$')
FRAME_RE = re.compile(r'(?:^|/)frames/frame_(\d{4})\.png$')
KEYS = [0, 100, 200, 300, 400, 500, 600, 700, 800]
ABSENT = {
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_A080',
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_A120',
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_M085_T080',
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_M115_T100',
}
PENDING_LIVE = {
    'F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100': {
        'status': 'running', 'pid': 769309, 'start_ticks': '215244107',
        'source': 'fresh202 parent dispatch observation; no new probe',
    }
}
def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()
def load(path: Path):
    with path.open(encoding='utf-8') as f:
        return json.load(f)
def compact_ref(value, role='', allow_hash=True):
    """Make a path/ref metadata record; never reads scientific payloads or PNG bytes."""
    if value is None:
        return None
    if isinstance(value, str):
        value = {'path': value}
    if not isinstance(value, dict) or 'path' not in value:
        return {'value': value, 'role': role}
    path = Path(str(value['path']))
    out = {'path': str(path), 'role': role or value.get('role')}
    if value.get('sha256') is not None:
        out['declared_sha256'] = value['sha256']
    elif value.get('sha') is not None:
        out['declared_sha256'] = value['sha']
    elif value.get('declared_sha256') is not None:
        out['declared_sha256'] = value['declared_sha256']
    try:
        st = path.stat()
        out['exists'] = True
        out['bytes'] = st.st_size
        out['mode'] = stat.filemode(st.st_mode)
    except OSError as e:
        out['exists'] = False
        out['stat_error'] = type(e).__name__
        return out
    ext = path.suffix.lower()
    if ext == '.png':
        out['hash_policy'] = 'producer_declared_only; PNG not read or hashed by source agent'
    elif ext in {'.h5', '.bi4', '.csv', '.dat', '.vtk', '.vtu', '.hdf5'}:
        out['hash_policy'] = 'scientific_payload_not read or hashed by source agent'
    elif allow_hash and ext in META_SUFFIXES:
        try:
            actual = sha(path)
            out['metadata_sha256'] = actual
            if out.get('declared_sha256') is not None:
                out['declared_matches'] = actual == out['declared_sha256']
            if ext == '.json':
                meta = load(path)
                if isinstance(meta, dict): out.update({'json_'+k: meta[k] for k in ('status','returncode','return_code','schema','case_id','physical_case_id') if k in meta and isinstance(meta[k], (str,int,float,bool))})
        except OSError as e:
            out['hash_error'] = type(e).__name__
    else:
        out['hash_policy'] = 'stat only'
    return out
def ref(value, role=''):
    return compact_ref(value, role)
def pick(*vals):
    for v in vals:
        if isinstance(v, dict) and v.get('path'):
            return v
    return None
def nested(obj, *keys):
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur
def list_ref(values, role):
    if not isinstance(values, list):
        return []
    return [ref(x, role) for x in values if isinstance(x, dict) and x.get('path')]
def decision_info(cur, cp_decisions):
    dref = cur.get('accepted_decision')
    if not dref:
        return None
    p = Path(dref['path'])
    d = load(p) if p.exists() else {}
    bindings = d.get('bindings') if isinstance(d.get('bindings'), dict) else {}
    return {
        'path': ref(dref, 'accepted decision JSON'),
        'path_in_checkpoint320': dref['path'] in cp_decisions,
        'decision_status': d.get('status'),
        'decision_stage1_label': d.get('stage1_label'),
        'family_id': d.get('family_id'),
        'case_id': d.get('case_id'),
        'physical_case_id': d.get('physical_case_id'),
        'physical_condition_sha256': d.get('physical_condition_sha256'),
        'source_h5_physical_condition_sha256': d.get('source_h5_physical_condition_sha256'),
        'physical_condition_hash_semantics': d.get('physical_condition_hash_semantics'),
        'physical_window_s': d.get('physical_window_s'),
        'frames': d.get('frames'),
        'actual_last_time_s': d.get('actual_last_time_s'),
        'particle_count': d.get('particle_count'),
        'native_fluid_particles_initial': d.get('native_fluid_particles_initial'),
        'native_fluid_particles_final': d.get('native_fluid_particles_final'),
        'native_solver_excluded_particles': d.get('native_solver_excluded_particles'),
        'accepted_count_basis': d.get('count_basis'),
        'bindings': {
            k: ref(v, f'decision binding:{k}') if isinstance(v, dict) and v.get('path') else v
            for k, v in bindings.items() if k not in {'actual_completed_receipts'}
        },
        'actual_completed_receipts': list_ref(bindings.get('actual_completed_receipts'), 'decision completed receipt'),
        'numerical_precision_status': d.get('numerical_precision_status'),
        'Q_N_status': d.get('Q_N_status'),
        'Q_E_status': d.get('Q_E_status'),
        'scientific_payload_read_or_hash_by_main': d.get('scientific_payload_read_or_hash_by_main'),
        'independence_check': d.get('independence_check'),
    }
def find_sibling(parent, name):
    if not parent:
        return None
    hits = list(Path(parent).rglob(name))
    return hits[0] if len(hits) == 1 else (hits[0] if hits else None)
def publish_products(pub, report, fallback_contacts=None, fallback_keys=None, status_override=None, execution=None):
    if pub:
        p = Path(pub['path'])
        j = load(p) if p.exists() else {}
        root = j.get('published_output_root')
        files = j.get('files_excluding_receipt') if isinstance(j.get('files_excluding_receipt'), list) else []
        contacts, keys = [], []
        for f in files:
            rel = f.get('relative_path') if isinstance(f, dict) else None
            if not rel:
                continue
            m = PNG_RE.search(rel)
            if m:
                item = dict(f); item.update({'path': str(Path(root) / rel), 'role': 'published contact sheet'})
                item['stat_bytes'] = Path(item['path']).stat().st_size if Path(item['path']).exists() else None
                item['hash_policy'] = 'producer declared PNG SHA only; not read or rehashed'
                contacts.append(item)
            m = FRAME_RE.search(rel)
            if m and int(m.group(1)) in KEYS:
                item = dict(f); item.update({'path': str(Path(root) / rel), 'frame': int(m.group(1)), 'role': 'published navigation key'})
                item['stat_bytes'] = Path(item['path']).stat().st_size if Path(item['path']).exists() else None
                item['hash_policy'] = 'producer declared PNG SHA only; not read or rehashed'
                keys.append(item)
        contacts.sort(key=lambda x: x['path']); keys.sort(key=lambda x: x['frame'])
        return {
            'status': status_override or j.get('status', 'published'),
            'execution_receipt': ref(execution or pub, 'render execution receipt'),
            'publish_receipt': ref(pub, 'atomic render publish receipt'),
            'render_report': ref(report, 'full animation render report'),
            'published_output_root': root,
            'expected_contacts': 34, 'expected_navigation_keys': KEYS,
            'contacts': contacts, 'navigation_keys': keys,
            'producer_declared_contact_count': len(contacts),
            'producer_declared_key_count': len(keys),
            'source_h5_opened_or_hashed_by_wrapper': j.get('source_h5_opened_or_hashed_by_wrapper'),
        }
    contacts = []
    for x in fallback_contacts or []:
        y = dict(x); y['role'] = 'legacy contact reference; atomic publication receipt absent'
        y['stat_bytes'] = Path(y['path']).stat().st_size if Path(y.get('path','')).exists() else None
        y['hash_policy'] = 'producer-declared PNG SHA only; not read or rehashed'
        contacts.append(y)
    keys = []
    for x in fallback_keys or []:
        y = dict(x); y['role'] = 'legacy navigation reference; atomic publication receipt absent'
        y['stat_bytes'] = Path(y['path']).stat().st_size if Path(y.get('path','')).exists() else None
        y['hash_policy'] = 'producer-declared PNG SHA only; not read or rehashed'
        keys.append(y)
    return {
        'status': status_override or 'legacy_atomic_publish_receipt_absent',
        'execution_receipt': ref(execution, 'render execution receipt; atomic publish receipt absent'), 'publish_receipt': None, 'render_report': ref(report, 'render report; legacy receipt absent'),
        'published_output_root': None, 'expected_contacts': 34, 'expected_navigation_keys': KEYS,
        'contacts': contacts, 'navigation_keys': keys,
        'producer_declared_contact_count': len(contacts), 'producer_declared_key_count': len(keys),
        'source_h5_opened_or_hashed_by_wrapper': False,
    }
def qi_summary(qref):
    if not qref:
        return {'proof': None, 'metadata': None}
    p = Path(qref['path']); q = load(p) if p.exists() else {}
    ev = q.get('actual_completed_metadata_evidence') or {}
    refs = {k: ref(v, f'own full801 QI:{k}') for k, v in ev.items() if isinstance(v, dict) and v.get('path')}
    masks = q.get('actual_native_XMF_plan_field_namespaces')
    return {
        'proof': ref(qref, 'own full801 QI proof'),
        'metadata': {
            'full_frames': q.get('full_frames'), 'particles': q.get('particles'), 'fluid_initial_UIDs': q.get('fluid_initial_UIDs'),
            'all801_geometry_velocity_N3_times_UID_finite_verified': q.get('all801_geometry_velocity_N3_times_UID_finite_verified'),
            'all_native_UIDs_active_each_frame': q.get('all_native_UIDs_active_each_frame'),
            'all801_native_Part_BI4_filenames_stat_checked': q.get('all801_native_Part_BI4_filenames_stat_checked'),
            'all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked': q.get('all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked'),
            'depth_diagnostic_bins_not_numerical_thresholds': q.get('depth_diagnostic_bins_not_numerical_thresholds'),
            'subDP_positive_depth_not_quantified_by_zero_bins': q.get('subDP_positive_depth_not_quantified_by_zero_bins'),
            'actual_time_window_s': q.get('actual_time_window_s'),
            'actual_initial_QA_precision_negative': q.get('actual_initial_QA_precision_negative'),
            'historical_negative_flags': q.get('historical_negative_flags'),
            'native_XMF_plan_field_namespaces': masks,
            'native_source_plan_condition_sha256': q.get('actual_native_source_plan_condition_sha256'),
            'native_source_plan_condition_field_present': q.get('actual_native_source_plan_condition_field_present'),
            'native_source_plan_physical_condition_sha256': q.get('actual_native_source_plan_physical_condition_sha256'),
            'native_source_plan_physical_condition_field_present': q.get('actual_native_source_plan_physical_condition_field_present'),
            'XMF_source_plan_physical_condition_field_sha256': q.get('XMF_source_plan_physical_condition_field_sha256'),
            'XMF_source_plan_physical_condition_field_has_native_canonical_role': q.get('XMF_source_plan_physical_condition_field_has_native_canonical_role'),
            'XMF_source_plan_physical_condition_field_has_SourceDef_role': q.get('XMF_source_plan_physical_condition_field_has_SourceDef_role'),
            'actual_SourceDef': ref(q.get('actual_SourceDef'), 'registered SourceDef XML'),
            'actual_source_plan_JSON_file': ref(q.get('actual_source_plan_JSON_file'), 'source plan JSON'),
            'binding_source_definition_field_present': q.get('binding_source_definition_field_present'),
            'bed_declared_source_plan_field_sha256': q.get('bed_declared_source_plan_field_sha256'),
            'bed_declared_source_plan_field_has_SourceDef_role': q.get('bed_declared_source_plan_field_has_SourceDef_role'),
            'actual_native_request_condition_sha256': q.get('canonical_actual_native_request_condition_sha256'),
            'actual_converter_legacy_scope_sha256': q.get('actual_converter_legacy_scope_sha256'),
            'native_and_XMF_physical_plan_roles_separate': q.get('native_and_XMF_physical_plan_canonical_roles_and_separate_SourceDef_FILE_independently_verified'),
            'published_contacts': q.get('published_contacts'), 'visual_status': q.get('visual_status'),
            'new_case_credit': q.get('new_case_credit'), 'Q_N': q.get('q_n_granted'), 'Q_E': q.get('q_e_granted'),
            'main_scientific_payload_IO': q.get('main_scientific_payload_IO'), 'main_personally_viewed_PNGs': q.get('main_personally_viewed_PNGs'),
        },
        'actual_completed_metadata_evidence': refs,
    }
def completed_refs_from_decision(di):
    if not di: return {}
    vals = di.get('actual_completed_receipts') or []
    return {k: vals[i] for i,k in enumerate(['native_receipt','typed_receipt','xmf_receipt','render_receipt','raw_scatter_audit_receipt','bed_receipt','control_audit_receipt','gencase_receipt']) if i < len(vals)}
def normalized_old(cur, old, di, old_path, current_index_ref):
    b = {}
    dp = di.get('bindings', {}) if di else {}
    crefs = completed_refs_from_decision(di)
    b['native_receipt'] = ref(old.get('actual_native_receipt') or crefs.get('native_receipt'), 'native execution receipt')
    b['typed_report'] = ref(old.get('primary_typed_report') or dp.get('conversion_report'), 'typed conversion report')
    b['typed_receipt'] = ref(crefs.get('typed_receipt'), 'typed execution receipt')
    b['xmf_manifest'] = ref(old.get('primary_XMF_manifest') or dp.get('manifest'), 'XMF manifest')
    b['xmf_xml'] = ref(old.get('primary_XMF_XML') or dp.get('xdmf'), 'XMF XML')
    b['xmf_receipt'] = ref(crefs.get('xmf_receipt'), 'XMF execution receipt')
    b['render_receipt'] = ref(old.get('actual_render_execution_receipt') or crefs.get('render_receipt'), 'render execution receipt')
    render_report = old.get('actual_render_report') or dp.get('render_report')
    if not render_report and old.get('actual_render_execution_receipt'):
        hit = find_sibling(Path(old['actual_render_execution_receipt']['path']).parent, 'paraview-full-animation-report.json')
        render_report = {'path': str(hit)} if hit else None
    b['render_report'] = ref(render_report, 'full animation render report')
    b['bed_receipt'] = ref(old.get('actual_full801_bed_receipt') or crefs.get('bed_receipt'), 'bed execution receipt')
    b['bed_report'] = ref(old.get('actual_full801_bed_report'), 'bed audit report')
    b['gencase_receipt'] = ref(crefs.get('gencase_receipt'), 'GenCase receipt')
    b['initial_qa_receipt'] = ref(crefs.get('initial_qa_receipt'), 'initial QA receipt')
    b['raw_scatter_audit_receipt'] = ref(crefs.get('raw_scatter_audit_receipt'), 'raw keyframe scatter audit; not initial QA')
    b['initial_qa_report'] = None
    b['generated_xml'] = None
    b['source_definition_xml'] = None
    b['source_plan_json'] = None
    pub = None
    if cur['physical_case_id'] not in ABSENT:
        pub = old.get('actual_atomic_publish_receipt')
        if not pub and old.get('actual_render_execution_receipt'):
            hit = find_sibling(Path(old['actual_render_execution_receipt']['path']).parent, 'render-publish-receipt.json')
            pub = {'path': str(hit)} if hit else None
    b['render_publish_receipt'] = ref(pub, 'atomic render publish receipt')
    products = publish_products(pub, render_report, old.get('actual_source_contacts'), old.get('main_actual_published_navigation_keys') or old.get('actual_source_keys'), 'legacy_atomic_publish_receipt_absent' if cur['physical_case_id'] in ABSENT else None, old.get('actual_render_execution_receipt'))
    # For old accepted rows, preserve the raw role mask; it is the authority for the legacy source row.
    cert = {
        'source': 'Root1344 legacy primary-bed row plus accepted decision; no own QI file embedded',
        'full_frames': cur.get('expected_frames') or (di.get('frames') if di else None) or 801,
        'particles': di.get('particle_count') if di else 194427,
        'fluid_initial_UIDs': di.get('native_fluid_particles_initial') if di else 31658,
        'actual_last_time_s': di.get('actual_last_time_s') if di else None,
        'all801_geometry_velocity_N3_times_UID_finite_verified': old.get('all801_native_particle_geometry_velocity_N3_times_identity_render_bindings_verified'),
        'all801_full_bed_UID_footprint_one_DP_two_DP_bins_checked': True,
        'numerical_precision_status': di.get('numerical_precision_status') if di else 'not accepted',
        'precision_negative_not_reclassified': old.get('existing_bed_precision_negatives_retained_not_new_numerical_certification', True),
    }
    return {
        'physical_case_id': cur['physical_case_id'], 'case_id': cur.get('case_id'), 'family_id': 'F5',
        'acceptance': {'status': cur.get('status'), 'case_credit_already_in_checkpoint': cur.get('case_credit_already_in_authoritative_checkpoint'), 'accepted_decision': di},
        'current_index_record': {'path': str(INDEX), 'sha256': sha(INDEX), 'status': cur.get('status')},
        'legacy_delivery_source_row': {'path': str(old_path), 'sha256': sha(old_path), 'physical_case_id': old['physical_case_id'], 'legacy_row_roles_preserved': True},
        'primary': b,
        'source_scope_roles': old.get('actual_native_typed_XMF_bed_raw_role_masks'),
        'full801_certificate': cert,
        'render_products': products,
        'bed_delivery': {'receipt': b['bed_receipt'], 'report': b['bed_report'], 'raw_role_masks': old.get('actual_native_typed_XMF_bed_raw_role_masks'), 'source_definition_and_plan_json': 'not embedded in Root1344 legacy row; absence preserved'},
        'initial_and_negative_evidence': {'initial_qa_receipt': b['initial_qa_receipt'], 'precision_negative': di.get('numerical_precision_status') if di else None, 'source_decision_presence_is_not_raw_authority': old.get('source_decision_presence_matrix_is_not_raw_producer_field_authority')},
        'legacy_raw_fields': {'source_render_execution_receipt_field_absent': old.get('source_render_execution_receipt_field_absent'), 'actual_atomic_publish_receipt_field_present': old.get('actual_atomic_publish_receipt_field_present'), 'legacy_direct_render_publish_receipt_not_invented': old.get('legacy_direct_render_publish_receipt_not_invented'), 'actual_source_contacts_count': len(old.get('actual_source_contacts') or []), 'actual_source_keys_count': len(old.get('actual_source_keys') or []), 'main_actual_published_navigation_keys_count': len(old.get('main_actual_published_navigation_keys') or [])},
        'case_credit': 0, 'Q_N': False, 'Q_E': False, 'precision_status': cur.get('precision_status'),
        'new_personal_review': False, 'science_payload_IO': False,
    }
def normalized_delta(cur, di, qsum, current_index_ref):
    qmeta = qsum.get('metadata') or {}; ev = qsum.get('actual_completed_metadata_evidence') or {}
    primary = {k: ev.get(k) for k in ['native_receipt','typed_receipt','typed_report','xmf_receipt','xmf_manifest','xmf_xml','gencase_receipt','initial_qa_receipt','initial_qa_report','generated_xml','render_receipt','render_report','render_publish_receipt','bed_receipt','bed_report']}
    qi = qsum.get('proof')
    products = publish_products(ev.get('render_publish_receipt'), ev.get('render_report'), execution=ev.get('render_receipt'))
    return {
        'physical_case_id': cur['physical_case_id'], 'case_id': cur.get('case_id'), 'family_id': 'F5',
        'acceptance': {'status': cur.get('status'), 'case_credit_already_in_checkpoint': cur.get('case_credit_already_in_authoritative_checkpoint'), 'accepted_decision': di},
        'current_index_record': {'path': str(INDEX), 'sha256': sha(INDEX), 'status': cur.get('status'), 'native_request_scope': cur.get('native_request_scope'), 'latest_registered_render_request': cur.get('latest_registered_render_request')},
        'own_full801_QI': qsum,
        'primary': primary,
        'source_scope_roles': {'accepted_top_condition': cur.get('accepted_decision_top_condition_sha256'), 'accepted_top_hash_role': cur.get('accepted_decision_top_hash_role'), 'actual_native_request': qmeta.get('actual_native_request_condition_sha256'), 'actual_converter_legacy_scope': qmeta.get('actual_converter_legacy_scope_sha256'), 'native_XMF_plan_masks': qmeta.get('native_XMF_plan_field_namespaces'), 'native_condition': {'present': qmeta.get('native_source_plan_condition_field_present'), 'sha256': qmeta.get('native_source_plan_condition_sha256')}, 'native_physical_plan': {'present': qmeta.get('native_source_plan_physical_condition_field_present'), 'sha256': qmeta.get('native_source_plan_physical_condition_sha256')}, 'XMF_physical_plan': {'present': qmeta.get('XMF_source_plan_physical_condition_field_sha256') is not None, 'sha256': qmeta.get('XMF_source_plan_physical_condition_field_sha256'), 'has_native_canonical_role': qmeta.get('XMF_source_plan_physical_condition_field_has_native_canonical_role'), 'has_SourceDef_role': qmeta.get('XMF_source_plan_physical_condition_field_has_SourceDef_role')}, 'SourceDef': qmeta.get('actual_SourceDef'), 'source_plan_JSON': qmeta.get('actual_source_plan_JSON_file')},
        'full801_certificate': qmeta,
        'render_products': products,
        'bed_delivery': {'receipt': ev.get('bed_receipt'), 'report': ev.get('bed_report'), 'source_definition_xml': qmeta.get('actual_SourceDef'), 'source_plan_JSON': qmeta.get('actual_source_plan_JSON_file'), 'declared_source_plan_field': qmeta.get('bed_declared_source_plan_field_sha256'), 'binding_source_definition_field_present': qmeta.get('binding_source_definition_field_present')},
        'initial_and_negative_evidence': {'initial_qa_receipt': ev.get('initial_qa_receipt'), 'initial_qa_report': ev.get('initial_qa_report'), 'precision_negative': qmeta.get('actual_initial_QA_precision_negative'), 'historical_negative_flags': qmeta.get('historical_negative_flags')},
        'case_credit': 0, 'Q_N': False, 'Q_E': False, 'precision_status': cur.get('precision_status'), 'new_personal_review': False, 'science_payload_IO': False,
    }
def pending_row(cur, current_index_ref):
    pid = cur['physical_case_id']; live = PENDING_LIVE.get(pid)
    req = cur.get('latest_registered_render_request')
    return {
        'physical_case_id': pid, 'case_id': cur.get('case_id'), 'family_id': 'F5', 'status': cur.get('status'),
        'acceptance': {'accepted_decision': None, 'case_credit': 0, 'Q_N': False, 'Q_E': False},
        'current_index_record': {'path': str(INDEX), 'sha256': sha(INDEX), 'status': cur.get('status'), 'native_request_scope': cur.get('native_request_scope')},
        'registered_render_request': ref(req, 'pending registered render request'),
        'expected_frames': cur.get('expected_frames', 801), 'expected_particles': cur.get('expected_particles', 194427),
        'actual_primary_outputs': {'render_receipt': None, 'render_report': None, 'publish_receipt': None, 'contacts': [], 'navigation_keys': [], 'future_hashes': None},
        'pending_live_observation': live or {'status': 'not independently probed in fresh202; pending metadata only', 'source': 'current index historical observations are not promoted to live status'},
        'native_scope_roles': cur.get('native_request_scope'),
        'legacy_precision_and_source_limits': {'precision_status': cur.get('precision_status'), 'source_plan_and_aliases_not_filled': True},
        'science_payload_IO': False,
    }
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--checkpoint', type=Path, default=CP)
    ap.add_argument('--current-index', type=Path, default=INDEX)
    ap.add_argument('--legacy-catalog', type=Path, default=LEGACY)
    ap.add_argument('--output-dir', type=Path, required=True)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'refusing non-empty output directory: {out}')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'metadata').mkdir()
    cp = load(args.checkpoint); idx = load(args.current_index); legacy = load(args.legacy_catalog)
    currows = {r['physical_case_id']: r for r in idx['cases'] if r.get('family_id') == 'F5'}
    oldrows = {r['physical_case_id']: r for r in legacy['main_current_accepted30_actual_primary_rows']}
    cp_decisions = set(cp.get('accepted_decisions', []))
    old_ids = set(oldrows); accepted = [r for r in currows.values() if r.get('accepted_decision')]
    pending = [r for r in currows.values() if not r.get('accepted_decision')]
    if len(accepted) != 44 or len(pending) != 4:
        raise SystemExit(f'expected F5 44 accepted + 4 pending, got {len(accepted)} + {len(pending)}')
    accepted.sort(key=lambda r: r['physical_case_id']); pending.sort(key=lambda r: r['physical_case_id'])
    products = []
    for cur in accepted:
        di = decision_info(cur, cp_decisions)
        if cur['physical_case_id'] in oldrows:
            products.append(normalized_old(cur, oldrows[cur['physical_case_id']], di, args.legacy_catalog, {'path': str(args.current_index), 'sha256': sha(args.current_index)}))
        else:
            qref = cur.get('actual_full801_QI')
            qsum = qi_summary(qref)
            products.append(normalized_delta(cur, di, qsum, {'path': str(args.current_index), 'sha256': sha(args.current_index)}))
    products.sort(key=lambda r: r['physical_case_id'])
    # Membership comes verbatim from Root1344; accepted count does not redefine first24.
    membership = legacy['membership']
    absences = []
    for pid in sorted(ABSENT):
        row = oldrows[pid]
        absences.append({'physical_case_id': pid, 'legacy_atomic_publish_receipt': None, 'legacy_source_render_receipt_field_absent': row.get('source_render_execution_receipt_field_absent'), 'legacy_publish_not_invented': row.get('legacy_direct_render_publish_receipt_not_invented'), 'legacy_source_contacts_and_keys_preserved': True})
    recovery = ref({'path': str(RECOVERY), 'sha256': sha(RECOVERY)}, 'A080/A120 XMF506+bed508 recovery preflight')
    payload = {
        'schema': 'ds02.f5.fresh202.final48.current44.primary-bed-delivery.v1',
        'created_by': 'root/f6_endpoint_initial_qa', 'created_at_utc': '2026-10-07', 'case_credit': 0, 'Q_N': False, 'Q_E': False,
        'scientific_payload_IO': False, 'PNG_policy': 'stat and producer-declared SHA only; no PNG read or rehash by source agent',
        'authoritative_inputs': {
            'checkpoint320': {'path': str(args.checkpoint), 'sha256': sha(args.checkpoint), 'accepted_decisions_count': len(cp.get('accepted_decisions', [])), 'accepted_F5': cp.get('accepted_per_family', {}).get('F5')},
            'current_index_Root1432': {'path': str(args.current_index), 'sha256': sha(args.current_index), 'F5_rows': len(currows), 'accepted_F5': len(accepted), 'pending_F5': len(pending)},
            'legacy_Root1344': {'path': str(args.legacy_catalog), 'sha256': sha(args.legacy_catalog), 'main_current_accepted30_rows': len(oldrows)},
        },
        'membership': {'source': {'path': str(args.legacy_catalog), 'sha256': sha(args.legacy_catalog), 'role': 'Root1293 explicit arrays carried by Root1344'}, 'arrays': membership},
        'counts': {'registered_final48': 48, 'accepted_current': 44, 'pending_current': 4, 'delta_from_Root1344_accepted30': 14, 'old_rows_within_current': len(old_ids & {r['physical_case_id'] for r in accepted}), 'case_credit': 0},
        'legacy_atomic_publish_absences': absences,
        'A080_A120_recovery_preflight': {'evidence': recovery, 'actual_XMF506_completed_zero_count': 2, 'render_publish_receipt': None, 'does_not_upgrade_legacy_absence_to_published': True},
        'accepted_products': products,
        'pending_products': [pending_row(r, {'path': str(args.current_index), 'sha256': sha(args.current_index)}) for r in pending],
        'post_assembly_runtime_observations': [
            {'physical_case_id': 'F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090', 'original_render_number': 1184, 'observed_status': 'admitted_worker_running', 'worker_pid': 784356, 'worker_start_ticks': '215400672', 'receipt_path': None, 'publish_sha256': None, 'accepted_in_cp320': False, 'role': 'post-cp320 dispatch observation; pending product remains unaccepted'},
            {'physical_case_id': 'F5_COMPACT_RUNUP_RECOVERY_C082S1_M104_T085', 'original_render_number': 1175, 'observed_status': 'admitted_worker_running', 'worker_pid': 785291, 'worker_start_ticks': '215410128', 'receipt_path': None, 'publish_sha256': None, 'accepted_in_cp320': False, 'role': 'post-cp320 dispatch observation; pending product remains unaccepted'},
            {'physical_case_id': 'F5_COMPACT_RUNUP_RECOVERY_C082S1_M106_T085', 'original_render_number': 1149, 'observed_status': 'controller_queued_or_waiting', 'worker_pid': None, 'worker_start_ticks': None, 'receipt_path': None, 'publish_sha256': None, 'accepted_in_cp320': False, 'role': 'post-cp320 dispatch observation; not a terminal result'},
            {'physical_case_id': 'F5_COMPACT_RUNUP_RECOVERY_C082S1_M110_T100', 'original_render_number': 1189, 'observed_status': 'completed_zero_atomic_published_pending_visual_acceptance', 'worker_pid': None, 'worker_start_ticks': None, 'receipt_path': None, 'publish_sha256': None, 'accepted_in_cp320': False, 'visual_review_owner': 'production_recovery_fresh192', 'role': 'post-cp320 dispatch observation; no receipt or publish hash promoted into this stable cp320 package'},
        ],
        'limits_and_roles': {'precision_status': '视觉检查通过、数值精度未验收', 'strict_containment': False, 'subDP_precision': False, 'H5_launch_after_attestation_missing_fields_preserved': True, 'native_canonical_typed_legacy_XMF_physical_plan_roles_separate': True, 'bed_declared_plan_is_SourceDef_XML_not_plan_JSON_hash': True, 'future_pending_receipt_manifest_publish_sha256_null': True, 'historical_negative_evidence_preserved': True},
    }
    mp = out/'metadata/f5-final48-primary-bed-delivery.json'
    mp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)+'\n')
    readme = f'''# F5 fresh202 final48 primary/bed delivery metadata\n\nThis source-only package records the F5 roster at cp320: 44 accepted physical cases and four still-registered pending cases. It combines the 30 accepted Root1344 primary/bed rows with the 14 accepted rows added by the Root1432 index. The explicit Root1293 membership arrays are carried verbatim through Root1344; frozen8, actual24, and registered48 are independent of the current accepted count.\n\nThe four legacy atomic publish receipt absences (A080, A120, M085/T080, M115/T100) remain null. A080/A120 have a separate XMF506/bed508 execution-zero preflight reference; it does not manufacture a render publish receipt. Pending future render, termination, and publish hashes remain null; only M110/T100 has the parent dispatch live-worker observation (PID 769309, start_ticks 215244107), and that observation is not a terminal result.\n\nThe product JSON preserves native canonical, typed legacy, XMF physical-plan, SourceDef XML, source-plan JSON, genuine GenCase, initial-QA, full801 UID/N3/time/finite, bed diagnostic, render receipt/report, and PNG role metadata separately. PNGs are only stat'ed and producer-declared hashes are retained; no PNG or scientific payload was read or hashed. Precision, strict-containment, and sub-DP claims remain unaccepted. Post-cp320 observations are separate and never promote a pending case or invent a terminal/publish hash.\n\nRun the read-only validator from this package:\n\n```sh\npython3 scripts/validate_fresh202.py --package .\n```\n\nThe assembly utility accepts `--checkpoint`, `--current-index`, `--legacy-catalog`, and an empty `--output-dir`; it refuses to overwrite a non-empty output directory.\n'''
    (out/'README.md').write_text(readme)
    manifest = {'schema':'ds02.f5.fresh202.package-manifest.v1','package':'fresh202','metadata':'metadata/f5-final48-primary-bed-delivery.json','builder':'scripts/build_fresh202.py','validator':'scripts/validate_fresh202.py','generated_files':['README.md','metadata/f5-final48-primary-bed-delivery.json'],'source_only':True,'case_credit':0,'scientific_payload_IO':False}
    (out/'package-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(out)
if __name__ == '__main__': main()
