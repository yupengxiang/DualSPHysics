"""Small metadata-only tests for the V47 terminal sealer.

The fixture contains tiny stand-ins for product paths.  The builder only
stats and trusts producer-attested SHA values for those paths; it must never
open their contents.  The V47 executor/parent/root records are copied from
the real root-bound metadata and relocated in the temporary fixture, so the
test exercises the same metadata entry point without reading a real H5/BI4 or
62 MB result.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import stat

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_v47_terminal_sealer_v1.py"
V47_SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_v47_fresh_product_interface_v1.py"
SOURCE_Q = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics"
    "/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction"
    "/raw-to-label-v47-parent-closure-root-082"
)
EXECUTOR_SOURCE = SOURCE_Q / "f2-s1-portable-executor-request-v47-root-082.json"
PARENT_SOURCE = SOURCE_Q / "f2-s1-portable-parent-request-v47-root-082.json"
VERIFICATION_SOURCE = SOURCE_Q / "root-metadata-verification.json"
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
RAW_TREE_SHA = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
OLD_VIEW_SHA = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"


def load_module():
    spec = importlib.util.spec_from_file_location("sealer_v1_test_module", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = load_module()


def canonical(value):
    return S.canonical_sha(value)


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def physical_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relocate_v47(tmp_path: Path):
    """Make a small relocated copy of the actual root-bound V47 metadata."""
    qroot = tmp_path / "v47"
    target = qroot / "bundle-target"
    output = qroot / "products"
    target.mkdir(parents=True)
    output.mkdir(parents=True)
    executor = json.loads(EXECUTOR_SOURCE.read_text(encoding="utf-8"))
    executor["fresh_roots"] = {"target_root": str(target), "output_root": str(output)}
    executor_path = qroot / "executor.json"
    executor["sha256"] = canonical(executor)
    write_json(executor_path, executor)

    parent = json.loads(PARENT_SOURCE.read_text(encoding="utf-8"))
    parent["executor_request"] = {
        "immutable": True, "path": str(executor_path),
        "schema": executor["schema"], "sha256": physical_sha(executor_path),
    }
    parent_path = qroot / "parent.json"
    parent["sha256"] = canonical(parent)
    write_json(parent_path, parent)

    verification = json.loads(VERIFICATION_SOURCE.read_text(encoding="utf-8"))
    verification.update({
        "request": str(parent_path),
        "request_file_sha256": physical_sha(parent_path),
        "canonical_sha256": parent["sha256"],
        "executor": str(executor_path),
        "executor_file_sha256": physical_sha(executor_path),
        "fresh_namespace": str(qroot),
    })
    verification_path = qroot / "verification.json"
    write_json(verification_path, verification)
    return executor_path, parent_path, verification_path, target, output


def contract_fixture(tmp_path: Path, output: Path, relocated_sha: str) -> dict:
    expected = {
        "case_identity": {"family": "F2", "case_scope": "F2-S1 source-bound development"},
        "source_binding": {
            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND",
            "current_catalog_sha256": relocated_sha,
            "trajectory_h5_producer_sha256": "1" * 64,
            "source_files": {"current_catalog": relocated_sha, "trajectory_h5": "1" * 64},
        },
        "cohort": {"selected_count": 21114, "identity_key": "(Zone,Idp)", "identity_sha256": IDENTITY_SHA},
        "initial_mass_denominator": {
            "denominator_kg": 21.114001002861187,
            "initial_missing_mass_kg": 0.0,
            "later_missing_mass_kg": 0.003000000142492354,
            "initially_absent_count": 0,
            "later_missing_unique_count": 3,
            "derivation": "frozen initial source cohort; later missing is not augmented by later missing",
        },
        "time": {"frame_count": 401, "first_s": 0.0, "last_s": 4.000018446461944, "tolerance_s": 1e-9},
        "observer_fields": ["mass_weighted_com", "velocity", "kinetic_energy", "mass_quantile_front", "mass_distribution", "event_status"],
        "events": {
            "status_vocabulary": ["observed", "right_censored", "failed_before_observation", "initially_inside", "ambiguous_multiple_crossing"],
            "require_unknown_recross": True,
            "require_total_net_interval": True,
            "require_receiver_labels": True,
            "semantics_source": {"later_missing": "frozen", "saved_bracket": "retained", "recross": "unknown when hidden", "receiver_volume": "3D", "aperture": "finite"},
        },
    }
    contract = {
        "schema": "ds02.stage2.f2-v47-fresh-v16-source-contract.v1",
        "role": "DEVELOPMENT", "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "expected": expected,
        "current_catalog_provenance": {
            "actual_current_catalog": {"sha256": CURRENT_SHA, "scope": "exact CURRENT336 source identity"},
            "relocated_runtime_view": {"sha256": relocated_sha, "scope": "new V47 runtime view"},
        },
        "original_roots": ["/home/jade/old-source/F2-S1"],
        "limitations": ["manufactured contract for metadata-only test", "qualification remains UNKNOWN"],
    }
    contract["sha256"] = canonical(contract)
    path = output / "source-contract.json"
    write_json(path, contract)
    return contract


def artifact_row(path: Path, role: str, verified_by: str = "V47 parent producer") -> dict:
    info = path.stat()
    return {
        "role": role, "path": str(path), "sha256": physical_sha(path),
        "bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
        "mode_bits": stat.S_IMODE(info.st_mode), "content_sha_verified": True,
        "verification_phase": "AFTER_PARENT_RESERVATION_AND_PRODUCER_TERMINAL",
        "verified_by": verified_by,
    }


def terminal_fixture(tmp_path: Path, executor: Path, parent: Path, verification: Path,
                     output: Path, contract: dict) -> tuple[Path, dict, str]:
    relocated = "c" * 64
    artifacts = {}
    names = {
        "worker_report": "worker-report.json", "raw_converter_report": "raw-converter-report.json",
        "typed_hdf5": "typed-reconstructed.h5", "v15_result": "v15-result.json", "v16_result": "v16-result.json",
        "current_runtime_view": "CURRENT336-relocated.json", "relocated_v15_request": "replay-v15-relocated.json",
        "engine_report": "engine-report.json",
    }
    for role, name in names.items():
        path = output / name
        path.write_bytes((role + "\n").encode("utf-8"))
        artifacts[role] = artifact_row(path, role)
    contract_path = output / "source-contract.json"
    artifacts["source_contract"] = artifact_row(contract_path, "source_contract")
    manifest = {
        "schema": "ds02.stage2.f2-v47-producer-terminal-manifest.v1",
        "status": "COMPLETE_V47_PRODUCER_DEVELOPMENT_UNKNOWN",
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "request_bindings": {
            "executor": {"path": str(executor), "physical_sha256": physical_sha(executor)},
            "parent": {"path": str(parent), "physical_sha256": physical_sha(parent)},
            "root_metadata_verification": {"path": str(verification), "physical_sha256": physical_sha(verification)},
        },
        "terminal": {
            "parent_guard_completed": True, "reservation_closed": True,
            "charge_closed": True, "ledger_mutated": True,
            "payload_read_after_reservation": True, "model_invoked": False, "cfd_invoked": False,
        },
        "source_identity": {
            "actual_current_catalog_sha256": CURRENT_SHA,
            "relocated_runtime_view_sha256": relocated,
            "raw_tree_sha256": RAW_TREE_SHA, "raw_tree_file_count": 405, "raw_tree_frame_count": 401,
        },
        "source_contract": {"path": str(contract_path), "sha256": physical_sha(contract_path)},
        "artifacts": artifacts,
        "parent_attempt_id": "test-v47-attempt", "charge_id": "test-v47-charge",
    }
    manifest["sha256"] = canonical(manifest)
    manifest_path = tmp_path / "terminal-manifest.json"
    write_json(manifest_path, manifest)
    return manifest_path, manifest, relocated


def test_seal_terminal_uses_real_v47_metadata_and_defers_payload(tmp_path):
    executor, parent, verification, target, output = relocate_v47(tmp_path)
    relocated = "c" * 64
    contract = contract_fixture(tmp_path, output, relocated)
    manifest_path, _, _ = terminal_fixture(tmp_path, executor, parent, verification, output, contract)
    adapter = output / "producer-adapter.json"
    request = output / "fresh-v10-request.json"
    seal = output / "terminal-seal.json"

    result = S.seal_terminal(
        v47_executor_request=executor, v47_parent_request=parent,
        metadata_verification=verification, terminal_manifest=manifest_path,
        source_contract=output / "source-contract.json", adapter_output=adapter,
        v10_request_output=request, seal_output=seal,
    )
    assert result["status"] == "READY_FOR_PARENT_V10_SEMANTIC_GUARD"
    v10 = json.loads(request.read_text(encoding="utf-8"))
    assert v10["schema"] == "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
    assert v10["expected"]["source_binding"]["current_catalog_sha256"] == relocated
    assert v10["source_contract"]["current_catalog_identity_sha256"] == CURRENT_SHA
    assert v10["result"]["content_sha_verified"] is False
    assert v10["fresh_result_binding"]["content_sha_verified_by_producer"] is True
    assert v10["quality"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    # Exercise the real relocated V11→V10→V9→V8 metadata entrypoint.  The
    # fake V16 file is intentionally not JSON; preflight must not open it.
    v11_path = ROOT / "scripts" / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v11.py"
    spec = importlib.util.spec_from_file_location("v11_metadata_entrypoint", v11_path)
    assert spec and spec.loader
    v11 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v11)
    preflight = v11.preflight(request)
    assert preflight["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert preflight["hdf5_or_bi4_content_read"] is False
    # The request may state the policy name, but no actionable path or SHA
    # may point at the historical product.
    assert "root060" not in json.dumps(v10["result"]).lower()
    assert OLD_VIEW_SHA not in json.dumps(v10)


def test_seal_rejects_original_or_historical_runtime_view(tmp_path):
    executor, parent, verification, target, output = relocate_v47(tmp_path)
    contract = contract_fixture(tmp_path, output, CURRENT_SHA)
    manifest_path, manifest, _ = terminal_fixture(tmp_path, executor, parent, verification, output, contract)
    with pytest.raises(S.SealerError, match="relocated view"):
        S.seal_terminal(
            v47_executor_request=executor, v47_parent_request=parent,
            metadata_verification=verification, terminal_manifest=manifest_path,
            source_contract=output / "source-contract.json", adapter_output=output / "a.json",
            v10_request_output=output / "r.json", seal_output=output / "s.json",
        )


def test_evaluator_builder_requires_new_v10_proof_and_keeps_source_split(tmp_path):
    executor, parent, verification, target, output = relocate_v47(tmp_path)
    contract_fixture(tmp_path, output, "c" * 64)
    manifest_path, _, _ = terminal_fixture(tmp_path, executor, parent, verification, output, json.loads((output / "source-contract.json").read_text()))
    adapter, request, seal = output / "adapter.json", output / "v10.json", output / "seal.json"
    S.seal_terminal(
        v47_executor_request=executor, v47_parent_request=parent,
        metadata_verification=verification, terminal_manifest=manifest_path,
        source_contract=output / "source-contract.json", adapter_output=adapter,
        v10_request_output=request, seal_output=seal,
    )
    v10 = json.loads(request.read_text())
    proof = {
        "schema": "ds02.stage2.f2-fresh-v16-proof.v8",
        "status": "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN",
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_result": {"path": v10["result"]["path"], "sha256": v10["result"]["sha256"], "bytes": v10["result"]["bytes"], "content_sha_verified": True},
        "source_binding": {"original_current_catalog_sha256": CURRENT_SHA, "current_catalog_sha256": "c" * 64},
        "parent_guard": {"supplied": True, "ancestry_status": "RECORDED_BY_PARENT_GUARD"},
    }
    proof["sha256"] = canonical(proof)
    proof_path = output / "fresh-proof.json"
    write_json(proof_path, proof)
    evaluator_path = output / "fresh-evaluator.json"
    result = S.build_evaluator_request(seal_path=seal, v10_request_path=request, fresh_proof_path=proof_path, output=evaluator_path)
    assert result["status"] == "READY_FOR_PARENT_EVALUATOR_GUARD"
    evaluator = json.loads(evaluator_path.read_text())
    assert evaluator["source_identity"]["actual_current_catalog_sha256"] == CURRENT_SHA
    assert evaluator["source_identity"]["relocated_runtime_view_sha256"] == "c" * 64
    assert evaluator["execution"]["old_root060_result_or_proof_reuse"] == "FORBIDDEN"
    assert evaluator["model_invoked"] is False


def test_evaluator_rejects_proof_bound_to_old_result(tmp_path):
    executor, parent, verification, target, output = relocate_v47(tmp_path)
    contract_fixture(tmp_path, output, "c" * 64)
    manifest_path, _, _ = terminal_fixture(tmp_path, executor, parent, verification, output, json.loads((output / "source-contract.json").read_text()))
    adapter, request, seal = output / "adapter.json", output / "v10.json", output / "seal.json"
    S.seal_terminal(
        v47_executor_request=executor, v47_parent_request=parent,
        metadata_verification=verification, terminal_manifest=manifest_path,
        source_contract=output / "source-contract.json", adapter_output=adapter,
        v10_request_output=request, seal_output=seal,
    )
    v10 = json.loads(request.read_text())
    proof = {
        "schema": "ds02.stage2.f2-fresh-v16-proof.v8",
        "status": "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN",
        "quality": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "source_result": {"path": v10["result"]["path"], "sha256": "d" * 64, "bytes": v10["result"]["bytes"], "content_sha_verified": True},
        "source_binding": {"original_current_catalog_sha256": CURRENT_SHA, "current_catalog_sha256": "c" * 64},
        "parent_guard": {"supplied": True, "ancestry_status": "RECORDED_BY_PARENT_GUARD"},
    }
    proof["sha256"] = canonical(proof)
    proof_path = output / "bad-proof.json"
    write_json(proof_path, proof)
    with pytest.raises(S.SealerError, match="different V16 result"):
        S.build_evaluator_request(seal_path=seal, v10_request_path=request, fresh_proof_path=proof_path, output=output / "bad-evaluator.json")
