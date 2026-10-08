from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v42.py"
BASE = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v41-full-chain-root-081/"
    "f2-s1-portable-executor-request-v41-root-081.json"
)
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
EXTERNAL = Path("/var/tmp/ds02-stage2")


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("portable_executor_v42_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V42 = _load(SCRIPT)


def test_v42_joins_runtime_and_source_roles_without_payload_hashing(tmp_path: Path) -> None:
    output = tmp_path / "v42-request.json"
    target = EXTERNAL / f"test-v42-target-{tmp_path.name}"
    products = EXTERNAL / f"test-v42-products-{tmp_path.name}"
    result = V42.build_forward(
        base_request=BASE,
        output=output,
        target_root=target,
        output_root=products,
        parent_attempt_id=f"f2-s1-v42-pytest-{tmp_path.name}",
        ledger_path=LEDGER,
        external_filesystem=EXTERNAL,
        deadline_utc="2026-10-14T07:23:48+00:00",
        home_min_free_bytes=536870912000,
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    runtime_roles = {item["role"] for item in value["runtime_sources"]}
    source_roles = {item["role"] for item in value["source_entries"]}
    assert {
        "executor_v41", "cold_producer_v40", "portable_loader_v5",
        "raw_worker_v2", "operator_v14", "operator_v15", "operator_v16",
    } <= runtime_roles
    assert {
        "runtime_v2", "runtime_v4", "stage2_dispatch_v4", "strict_dispatch_v4",
        "raw_auxiliary:PartInfo.ibi4", "raw_auxiliary:PartMotionRef.ibi4",
        "raw_auxiliary:Part_Head.ibi4",
    } <= source_roles
    forward = value["forward_v42"]
    assert set(forward["transitive_runtime_roles"]) == runtime_roles
    assert set(forward["transitive_source_roles"]) == source_roles
    assert set(forward["transitive_closure_roles"]) == runtime_roles | source_roles
    assert forward["frozen_raw_tree"] == {
        "file_count": 405,
        "frame_count": 401,
        "tree_sha256": "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd",
        "content_hash_phase": "PARENT_AFTER_RESERVATION",
    }
    assert value["execution"]["evaluator_stage"] == "DISABLED_UNTIL_NEW_V16_RESULT_AND_NEW_SEMANTIC_PROOF"
    assert value["execution"]["evaluator_proof_input"] is None
    assert result["raw_h5_sha_during_build"] is False
    assert result["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert value["sha256"] == V42.canonical_sha(value)


def test_v42_preserves_literal_venv_and_exact_current_identity() -> None:
    base = json.loads(BASE.read_text(encoding="utf-8"))
    python_rows = [item for item in base["runtime_sources"] if item.get("role") == "python_executable"]
    assert len(python_rows) == 1
    assert ".venv/bin/python" in python_rows[0]["path"]
    current_rows = [item for item in base["source_entries"] if item.get("role") == "v2:current_catalog"]
    assert len(current_rows) == 1
    assert current_rows[0]["sha256"] == "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"

