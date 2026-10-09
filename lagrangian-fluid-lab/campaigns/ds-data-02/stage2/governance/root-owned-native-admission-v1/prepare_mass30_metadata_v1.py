"""Prepare root runtime closure for thirty exact-or-null mass diagnostics."""
from pathlib import Path
import importlib.util
import json
import os

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[4]
S = LAB / 'campaigns/ds-data-02/stage2'


def main():
    os.chdir(LAB)
    spec = importlib.util.spec_from_file_location('root_mass30_guard', HERE / 'verify_actual_mass30_v1.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    forward = S / 'governance/root-owned-lifecycle-continuation-v1/root_forward_metadata.py'
    context = {'__file__': str(forward), '__name__': 'root_mass30_metadata_forward'}
    exec(forward.read_text(), context)
    context['sha'] = guard.sha
    extra = [Path(__file__), HERE / 'verify_actual_mass30_v1.py',
             S / 'checkpoints/ROOT322_326_MASS_V6_THIRTY_SOURCE_ROOT_READINESS_V1.json',
             S / 'governance/root-owned-lifecycle-continuation-v1/root_common_verification.py',
             S / 'governance/root-owned-lifecycle-continuation-v1/root_cpu_verification_footer.py',
             LAB / 'scripts/ds_data02_stage2_terminal_cpu_delta_reconciler_v6.py',
             LAB / 'scripts/ds_data02_stage2_verify_native_typed_mass_impact_v6.py']
    for num, count in guard.COUNTS.items():
        source = S / f'requests/native-typed-mass-impact-v6-root-forward-{num}-source-only-002.json'
        q = json.loads(source.read_text())
        assert not (set(q['input_files']) & set(q['deferred_input_files']))
        manifest = json.loads(Path(q['manifest_contract']['path']).read_text())
        assert len(manifest['cases']) == count
        q['root_canonical_binding'] = {'namespace': num, 'source_family_id': q['family_id'], 'selected_case_count': count, 'scientific_credit': 0}
        q['family_id'] = 'infra'
        q['max_memory_bytes'] = 4294967296
        q['root_admission_state'] = 'SOURCE_ONLY_NO_PARENT_LAUNCH_REQUIRES_FRESH_SERIAL_HANDOFF'
        context['write'](q, source, f'native-typed-mass-impact-v6-root-forward-{num}-002.json', extra=extra)


if __name__ == '__main__':
    main()
