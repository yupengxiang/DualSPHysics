"""Compare saved contact brackets against the unchanged registered budget."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(contract, output):
    if output.exists():
        raise FileExistsError(output)
    spec = json.loads(contract.read_text())
    frozen = json.loads(Path(spec['frozen']).read_text())
    sources = {str(contract): digest(contract), spec['frozen']: digest(spec['frozen'])}
    comparisons = {}
    for mechanism, pair in spec['pairs'].items():
        reports = []
        for item in pair:
            path = Path(item['report'])
            receipt_path = path.parent / 'execution-receipt.json'
            receipt = json.loads(receipt_path.read_text())
            assert receipt['status'] == 'completed' and receipt['returncode'] == 0
            assert digest(path) == item['sha256']
            sources[str(path)] = digest(path)
            sources[str(receipt_path)] = digest(receipt_path)
            reports.append(json.loads(path.read_text()))
        a, b = reports
        assert a['physical_binding_sha256'] == b['physical_binding_sha256']
        assert a['registered_protocol'] == b['registered_protocol']
        assert a['registered_protocol'] == frozen['budgets'][mechanism]['current_operator_protocol']['physical_support']
        for r in reports:
            assert len(r['time_s']) == 1201 and r['time_s'][0] == 0 and r['time_s'][-1] >= 1.2
            assert r['first_contact']['status'] == 'observed'
        x, y = a['first_contact']['bracket_s'], b['first_contact']['bracket_s']
        assert x[0] <= x[1] and y[0] <= y[1]
        minimum = max(0.0, x[0] - y[1], y[0] - x[1])
        maximum = max(abs(x[0] - y[1]), abs(x[1] - y[0]))
        budget = frozen['budgets'][mechanism]['original_scale_contract']['event_time_error_budget_s']
        comparisons[mechanism] = {
            'pair': [item['resolution'] for item in pair],
            'first_contact': [r['first_contact'] for r in reports],
            'minimum_interval_separation_s': minimum,
            'maximum_interval_separation_s': maximum,
            'original_whole_event_budget_s': budget,
            'minimum_error_over_budget': minimum / budget,
            'status': 'fail_even_allowing_saved_brackets' if minimum > budget else 'not_resolved_by_interval_lower_bound',
            'physical_binding_sha256': a['physical_binding_sha256'],
            'final_unknown_native_exclusion_mass_kg': [r['unknown_native_exclusion_mass_kg'][-1] for r in reports],
            'scope': 'coarse-medium diagnostic; a fine-based production recipe requires separate registered evidence',
        }
    assert all(digest(path) == value for path, value in sources.items())
    result = {'schema': 'ds02.f4.contact-bracket-comparison.v1', 'source_sha256': sources,
              'comparisons': comparisons, 'qualification_claim': 'none', 'production_approval': 'none',
              'limitations': ['Saved-time brackets bound discretely observed support onset; no unsaved contact reconstruction claim.',
                              'No threshold, physical denominator or time window is altered.']}
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(comparisons), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    compare(args.contract, args.output)
