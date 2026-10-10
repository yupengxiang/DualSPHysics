from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_canonical_replay_guard_v1.py"
SPEC = importlib.util.spec_from_file_location("f2_canonical_prime_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    namespace = tmp_path / "attempt" / "bundle"
    namespace.mkdir(parents=True)
    modules: dict[str, dict[str, str]] = {}
    module_text = {
        "raw_converter": "def convert(): return None\n",
        "v14_operator": (
            "EXPECTED = 'F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090'\n"
            "if case_index != 78: raise ValueError('legacy')\n"),
        "v15_operator": "import ds_data02_stage2_f2_replay_v14 as v14\n",
        "v16_operator": "def label(): return None\n",
        "worker": "def run(): return None\n",
    }
    for role, body in module_text.items():
        path = namespace / f"{role}.py"
        path.write_text(body, encoding="utf-8")
        modules[role] = {"path": str(path), "sha256": _sha(path)}
    pipeline = []
    pipeline_text = {
        "canonical_adapter": "def adapt(): return {'case_index': 65}\n",
        "raw_converter": "def convert(): return None\n",
        "reader": "def read(): return None\n",
        "restorer": "def restore(): return None\n",
        "label_producer": "def label(): return None\n",
        "worker": "def run(): return None\n",
        "portable_scorer": "def score(): return None\n",
    }
    for role, body in pipeline_text.items():
        path = namespace / f"pipeline-{role}.py"
        path.write_text(body, encoding="utf-8")
        pipeline.append({"role": role, "path": str(path), "sha256": _sha(path)})
    pipeline_path = tmp_path / "pipeline.json"
    pipeline_path.write_text(json.dumps({
        "schema": "ds02.stage2.f2-canonical-pipeline-binding.v1", "roles": pipeline,
    }), encoding="utf-8")
    rebound = {
        "schema": MODULE.REBOUND_SCHEMA,
        "case_identity": {
            "current_case_index": 65, "family_id": "F2",
            "physical_case_id": MODULE.CANONICAL_ID,
            "manifest_physical_case_id": MODULE.CANONICAL_ID,
        },
        "current_binding": {"case_index": 65, "sha256": MODULE.CURRENT_SHA},
        "modules": modules,
        "raw_binding": {"expected_raw_tree_sha256": MODULE.PENDING},
        "source_hashes_preverified_by_parent": False,
        "v15_request": {"source_fallback": "REJECT", "input_files": []},
        "execution": {"bound_namespace_root": str(namespace)},
    }
    rebound_path = tmp_path / "rebound.json"
    rebound_path.write_text(json.dumps(rebound), encoding="utf-8")
    return rebound_path, pipeline_path, namespace


def test_prime_hashes_complete_copied_pipeline_and_rejects_legacy_semantics(tmp_path: Path) -> None:
    rebound, pipeline, _namespace = _fixture(tmp_path)
    report = MODULE.build_prime(rebound_path=rebound, pipeline_path=pipeline,
                                output_dir=tmp_path / "out")
    assert report["status"] == "PENDING_PARENT_GUARD_AND_CANONICAL_SEMANTICS"
    assert report["raw_payload_read_by_builder"] is False
    assert report["pipeline_roles"] == list(MODULE.PIPELINE_ROLES)
    audit = report["legacy_operator_audit"]["modules"]
    assert next(item for item in audit if item["role"] == "v14_operator")["row78_gate_literal"] is True
    assert report["legacy_operator_audit"]["canonical_adapter_required"] is True
    request = json.loads((tmp_path / "out/f2-s1-canonical-replay-prime-request-v1.json").read_text())
    assert request["case_identity"]["current_case_index"] == 65
    assert request["scientific_contract"]["raw_tree_sha256"] == MODULE.PENDING
    assert request["scientific_contract"]["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    validated = MODULE.validate_prime(tmp_path / "out/f2-s1-canonical-replay-prime-request-v1.json")
    assert validated["status"] == "PRIME_VALIDATED_SOURCE_ONLY_PARENT_GUARD_REQUIRED"
    assert validated["raw_payload_read_by_validator"] is False


def test_prime_validator_rejects_source_mutation_after_build(tmp_path: Path) -> None:
    rebound, pipeline, namespace = _fixture(tmp_path)
    MODULE.build_prime(rebound_path=rebound, pipeline_path=pipeline, output_dir=tmp_path / "out")
    (namespace / "v14_operator.py").write_text("# changed legacy operator\n", encoding="utf-8")
    with pytest.raises(MODULE.PrimeError, match="module source changed"):
        MODULE.validate_prime(tmp_path / "out/f2-s1-canonical-replay-prime-request-v1.json")


def test_prime_rejects_historical_alias_even_with_a_complete_pipeline(tmp_path: Path) -> None:
    rebound, pipeline, _namespace = _fixture(tmp_path)
    value = json.loads(rebound.read_text())
    value["case_identity"]["physical_case_id"] = MODULE.HISTORICAL_ALIAS_ID
    broken = tmp_path / "alias.json"
    broken.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MODULE.PrimeError, match="not canonical CURRENT row 65"):
        MODULE.build_prime(rebound_path=broken, pipeline_path=pipeline,
                           output_dir=tmp_path / "alias-out")


def test_prime_rejects_a_pipeline_source_outside_the_new_namespace(tmp_path: Path) -> None:
    rebound, pipeline, namespace = _fixture(tmp_path)
    value = json.loads(pipeline.read_text())
    outside = tmp_path / "outside.py"
    outside.write_text("def score(): return None\n", encoding="utf-8")
    value["roles"][-1]["path"] = str(outside)
    value["roles"][-1]["sha256"] = _sha(outside)
    broken = tmp_path / "outside-pipeline.json"
    broken.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MODULE.PrimeError, match="escapes the copied namespace"):
        MODULE.build_prime(rebound_path=rebound, pipeline_path=broken,
                           output_dir=tmp_path / "outside-out")
