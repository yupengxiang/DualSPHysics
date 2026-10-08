from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
EVALUATOR = ROOT / "scripts" / "ds_data02_stage2_f2_typed_only_evaluator_v2.py"
PARENT = ROOT / "scripts" / "ds_data02_stage2_f2_typed_only_evaluator_parent_v2.py"
V10_REQUEST = ROOT / "campaigns" / "ds-data-02" / "stage2" / "native-reconstruction" / "typed-only-fresh-proof-root-055" / "f2-s1-fresh-v16-proof-request-v10-root-060.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v2 = _load(EVALUATOR, "typed_evaluator_v2_under_test")
parent_v2 = _load(PARENT, "typed_parent_v2_under_test")


def test_v10_request_is_fresh_proof_binding_without_payload_read(tmp_path: Path):
    value = json.loads(V10_REQUEST.read_text(encoding="utf-8"))
    root = "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics"
    agent = "/home/jade/.codex/worktrees/ds-data-02-stage2-consumers/DualSPHysics"

    def replace(item):
        if isinstance(item, str):
            return item.replace(root, agent)
        if isinstance(item, list):
            return [replace(x) for x in item]
        if isinstance(item, dict):
            return {k: replace(v) for k, v in item.items()}
        return item

    value = replace(value)
    value["sha256"] = v2.V8.canonical_sha(value)
    path = tmp_path / "v10-request.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bound_path, bound, scope = v2._validate_v10_proof_request(path)
    assert bound_path == path.resolve()
    assert scope["accepted_result_missing_scope"] == v2.V10.ACCEPTED_MISSING_SCOPE
    assert bound["expected"]["initial_mass_denominator"]["later_missing_unique_count"] == 3


def test_parent_v2_rebinds_v1_resource_owner_without_second_ledger():
    assert parent_v2.SCHEMA.endswith("parent-request.v2")
    assert parent_v2.P1.TE_SCHEMA == "ds02.stage2.f2-typed-only-evaluator-request.v2"
    assert parent_v2.P1.TE_SCRIPT.name == "ds_data02_stage2_f2_typed_only_evaluator_v2.py"
    assert parent_v2.P1.SCHEMA == parent_v2.SCHEMA
    assert parent_v2.P1.REPORT_SCHEMA.endswith("parent-report.v2")
