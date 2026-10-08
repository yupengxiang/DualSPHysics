from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v41.py"
V38_REQUEST = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain-root-059/f2-s1-portable-executor-request-v38-root-059.json"
V39_CONTRACT = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain/f2-s1-fresh-v16-source-contract-v3-001.json"
V38_OVERLAY = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain-root-059/f2-s1-native-raw-portable-overlay-v38-root-059.json"
PARENT_SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_parent_v3.py"
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("portable_executor_v41_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V41 = _load(SCRIPT)


def test_v41_builds_fresh_relocated_engine_request_without_payload_reads(tmp_path: Path) -> None:
    output = tmp_path / "v41-request.json"
    result = V41.build_forward(
        v38_request=V38_REQUEST, v39_contract=V39_CONTRACT, output=output,
        target_root=Path("/var/tmp/ds02-stage2") / "test-v41-target-pytest",
        output_root=Path("/var/tmp/ds02-stage2") / "test-v41-output-pytest")
    value = json.loads(output.read_text(encoding="utf-8"))
    roles = {item["role"]: item for item in value["runtime_sources"]}
    assert {"v39_source_contract", "cold_producer_v40", "executor_v41"} <= set(roles)
    assert value["status"] == "READY_FOR_PARENT_STAGE2_GUARD"
    assert value["v41_status"] == "READY_FOR_PARENT_V41_RELOCATED_COLD_GUARD"
    assert value["forward_v41"]["old_f208_sha_reuse"] == "FORBIDDEN"
    assert value["forward_v41"]["frozen_raw_tree"] == {
        "file_count": 405, "frame_count": 401,
        "tree_sha256": "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"}
    assert value["sha256"] == V41.canonical_sha(value)
    assert result["payload_read"] is False
    assert result["hdf5_or_bi4_read"] is False


def test_v41_preflight_is_parent_guard_ready_and_does_not_hash_payload(tmp_path: Path) -> None:
    request = tmp_path / "v41-request.json"
    V41.build_forward(
        v38_request=V38_REQUEST, v39_contract=V39_CONTRACT, output=request,
        target_root=Path("/var/tmp/ds02-stage2") / "test-v41-target-pytest-preflight",
        output_root=Path("/var/tmp/ds02-stage2") / "test-v41-output-pytest-preflight")
    output = tmp_path / "preflight.json"
    result = V41.preflight(request, output)
    assert result["status"] == "READY_FOR_PARENT_STAGE2_GUARD"
    assert result["content_hash_read"] is False
    assert result["hdf5_or_bi4_read"] is False
    assert result["raw_tree_read"] is False


def test_v41_parent_builder_keeps_same_ledger_and_v40_source_role(tmp_path: Path) -> None:
    request = tmp_path / "v41-request.json"
    V41.build_forward(
        v38_request=V38_REQUEST, v39_contract=V39_CONTRACT, output=request,
        target_root=Path("/var/tmp/ds02-stage2") / "test-v41-target-pytest-parent",
        output_root=Path("/var/tmp/ds02-stage2") / "test-v41-output-pytest-parent")
    parent_path = tmp_path / "v41-parent.json"
    result = V41.build_parent(
        executor_request=request, output=parent_path,
        external_filesystem=Path("/var/tmp/ds02-stage2"), ledger_path=LEDGER,
        parent_attempt_id="f2-s1-v41-parent-pytest", max_wall_seconds=6000.0,
        home_receipt_path=tmp_path / "home-receipt.json",
        supervisor_output_root=Path("/var/tmp/ds02-stage2") / "test-v41-parent-output-pytest",
        home_min_free_bytes=536870912000, external_bytes=22000000000,
        allow_missing_parent=True)
    value = json.loads(parent_path.read_text(encoding="utf-8"))
    roles = {item["role"] for item in value["static_bindings"]}
    assert "v39_source_contract" in roles
    assert "cold_producer_v40" in roles
    assert value["executor_script"]["path"] == str(SCRIPT)
    assert value["parent_resource_binding"]["same_parent_ledger"] is True
    assert value["parent_resource_binding"]["ledger_reset"] is False
    assert result["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_v41_uses_new_view_contract_and_never_claims_old_typed_sha() -> None:
    pipeline = V41.build_forward.__doc__ or ""
    assert "H5/BI4/raw/typed payload" in pipeline
    assert V41.FORWARD_SCHEMA.endswith("v1")


def test_v40_relocation_is_consumed_by_actual_v41_label_boundary_without_h5_read(tmp_path: Path) -> None:
    """Exercise the post-copy V40 calls with JSON plus an empty H5-path fixture."""
    overlay_template = json.loads(V38_OVERLAY.read_text(encoding="utf-8"))
    entries = {item["role"]: item for item in overlay_template["entries"]}
    current = Path(entries["v2:current_catalog"]["original_path"])
    v15_source = Path(entries["v2:v15_replay_request"]["original_path"])
    base_source = Path(entries["immutable_base_v2_request"]["original_path"])
    target_root = tmp_path / "bundle-target"
    output_root = tmp_path / "products"
    runtime_contract = target_root / "runtime/runtime/producer/f2-s1-source-contract-v39.json"
    runtime_contract.parent.mkdir(parents=True)
    runtime_contract.write_bytes(V39_CONTRACT.read_bytes())
    reference = target_root / "sources/trajectory.h5"
    reference.parent.mkdir(parents=True)
    reference.write_bytes(b"metadata-only trajectory path fixture\n")
    output = output_root / "native-raw-to-label-v34"
    output.mkdir(parents=True)
    sealed = {
        "content_hash_verified": True, "target_root": str(target_root),
        "entries": [
            {"role": "v2:current_catalog", "target_path": str(current)},
            {"role": "reference_typed_hdf5", "target_path": str(reference)},
        ],
    }
    output_root.mkdir(exist_ok=True)
    (output_root / "sealed-overlay-v34.json").write_text(
        json.dumps(sealed), encoding="utf-8")
    old_v15 = json.loads(v15_source.read_text(encoding="utf-8"))
    old_base = json.loads(base_source.read_text(encoding="utf-8"))
    alias_sha = "a" * 64
    old_v15.setdefault("current_binding", {}).update({"path": str(current), "sha256": alias_sha})
    for item in old_v15.get("source_files", []):
        if isinstance(item, dict) and item.get("role") == "current_catalog":
            item.update({"path": str(current), "sha256": alias_sha})
    old_v15.setdefault("observer_profile", {}).setdefault("source_file_sha256", {})["current_catalog"] = alias_sha
    old_v15_path = output_root / "relocated-runtime/f2-s1-replay-request-v15-relocated.json"
    old_v15_path.parent.mkdir(parents=True)
    old_v15_path.write_text(json.dumps(old_v15), encoding="utf-8")
    old_base["v15_request"] = old_v15
    old_base_path = output_root / "relocated-runtime/f2-s1-native-raw-to-typed-label-request-v2-relocated.json"
    old_base_path.write_text(json.dumps(old_base), encoding="utf-8")
    request = json.loads(V38_REQUEST.read_text(encoding="utf-8"))
    # The helper only needs the copied runtime role declaration; its runtime
    # target is the fixture contract above.
    for item in request["runtime_sources"]:
        if item.get("role") == "v39_source_contract":
            break
    else:
        request["runtime_sources"].append({
            "role": "v39_source_contract", "target_relative_path": "runtime/producer/f2-s1-source-contract-v39.json",
            "path": str(V39_CONTRACT), "sha256": V41.sha256_file(V39_CONTRACT),
        })
    state = V41._make_v40_engine_inputs(request, output, old_base_path)
    assert state["integration"]["status"] == "PASS_V40_RELOCATED_CONTRACT_CONSUMED_BEFORE_LABEL"
    assert state["integration"]["original_current_identity_sha256"] == V41.V40.ACTUAL_CURRENT_SHA
    assert state["integration"]["relocated_current_view"]["sha256"] not in {
        V41.V40.ACTUAL_CURRENT_SHA, V41.V40.HISTORICAL_OVERLAY_SHA}
    rebound = json.loads(state["v15"].read_text(encoding="utf-8"))
    assert rebound["current_binding"]["sha256"] == state["integration"]["relocated_current_view"]["sha256"]
    # The V40 contract carries its canonical-object SHA in the JSON field;
    # that intentionally differs from the byte SHA of the pretty-printed
    # contract file.  The consumer binding is to the canonical contract
    # identity, while the enclosing request separately seals file bytes.
    contract_value = json.loads(state["contract"].read_text(encoding="utf-8"))
    assert json.loads(state["base"].read_text(encoding="utf-8"))["v40_source_contract_binding"]["sha256"] == contract_value["sha256"]
