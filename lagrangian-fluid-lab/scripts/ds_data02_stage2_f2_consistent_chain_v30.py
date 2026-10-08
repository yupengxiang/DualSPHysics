#!/usr/bin/env python3
"""Build the source-bound v25 outer request and v29 portable bundle contract.

This is a forward metadata builder.  It keeps the consumed V25/V26 requests,
overlay, storage plan, and v29 graph byte-for-byte immutable, then creates a
new V15 adapter and V24 outer request in a new request directory.  The bundle
contract is deliberately explicit about the two storage scopes: the V24
supervisor reserves only its own small reports, while the nested V25 copy and
raw-to-label worker owns the 8.644 GB overlay reservation.  A parent guard must
reserve and charge both scopes under the same existing ledger lease.

The builder performs JSON/stat checks only.  It never copies or opens HDF5,
BI4, PartOut, or RunPARTs.  The resulting request stays DEVELOPMENT with
QI/QN/QE UNKNOWN and requires the shared parent guard, a fresh output
namespace, post-copy SHA sealing, a fresh Python subprocess, and OS-level
open auditing before any native read.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping


SCRIPT = Path(__file__).resolve()
LAB = SCRIPT.parents[0].parent
BASE = LAB / "campaigns/ds-data-02/stage2/native-reconstruction"
V25_DIR = BASE / "raw-to-label-v25-consistent"
V26_DIR = BASE / "raw-to-label-v26-supervised-chain"
V30_DIR = BASE / "raw-to-label-v30-full-chain"
V25_V13 = V25_DIR / "f2-s1-parent-supervised-launch-request-v13-012.json"
V26_V14 = V26_DIR / "f2-s1-parent-supervised-launch-request-v14-013.json"
V25_V7 = V25_DIR / "f2-s1-portable-orchestration-request-v7-012.json"
V25_OVERLAY = V25_DIR / "f2-s1-native-raw-portable-overlay-v7-012.json"
V25_PLAN = V25_DIR / "f2-s1-portable-storage-plan-v7-012.json"
EVALUATOR_V3 = BASE / "raw-to-label-v26/f2-s1-no-model-evaluator-v3-actual-request-002.json"
V15_PATH = SCRIPT.with_name("ds_data02_stage2_f2_parent_launcher_v15.py")
V24_PATH = SCRIPT.with_name("ds_data02_stage2_f2_external_supervisor_v24.py")
V25_PATH = SCRIPT.with_name("ds_data02_stage2_f2_external_supervisor_v25.py")
V21_PATH = SCRIPT.with_name("ds_data02_stage2_f2_external_supervisor_v21.py")
V22_PATH = SCRIPT.with_name("ds_data02_stage2_f2_external_supervisor_v22.py")
V20_PATH = SCRIPT.with_name("ds_data02_stage2_f2_parent_supplemental_charge_v20.py")
V30_V15 = V30_DIR / "f2-s1-parent-supervised-launch-request-v15-adapter-031.json"
V30_V25 = V30_DIR / "f2-s1-external-supervisor-request-v25-031.json"
# Keep the internal argument name used by the preceding v30 draft so callers
# cannot accidentally select the consumed v24 request; its default is now the
# additive v25 request.
V30_V24 = V30_V25
V30_CONTRACT = V30_DIR / "f2-s1-portable-v29-bundle-contract-v30-031.json"
EXTERNAL = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5")
V30_ROOT = EXTERNAL / "f2-s1-v30-full-chain-001"
V30_BUNDLE_ROOT = V30_ROOT / "bundle-target-v30"
V30_PRODUCTS = V30_ROOT / "reference-products-v30"
V30_INDEX = EXTERNAL / "portable-output-index-v30.json"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
OVERLAY_BYTES = 8_644_512_838
OVERLAY_ENTRIES = 443
V25_STORAGE_ESTIMATE = 252_544_077_005


class V30Error(RuntimeError):
    pass


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise V30Error(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V15 = _load("ds02_parent_launcher_v15_for_v30", V15_PATH)
V24 = _load("ds02_external_supervisor_v24_for_v30", V24_PATH)
V25 = _load("ds02_external_supervisor_v25_for_v30", V25_PATH)


def file_sha(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V30Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise V30Error(f"JSON object required: {target}")
    return value


def canonical(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise V30Error(f"refusing existing v30 output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def _require_file(path: Path | str, role: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise V30Error(f"{role} is missing: {target}")
    return target


def _same_path(value: Any, expected: Path, role: str) -> None:
    if not isinstance(value, str) or Path(value).expanduser().resolve() != expected.resolve():
        raise V30Error(f"{role} path differs from the explicitly supplied consumer path")


def _ref_path(item: Mapping[str, Any], key: str, parent: Path) -> Path:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise V30Error(f"{parent}: nested {key} path is missing")
    path = _require_file(value, f"nested {key}")
    nested = load(path)
    expected = item.get("sha256")
    if expected not in {nested.get("sha256"), canonical(nested), file_sha(path)}:
        raise V30Error(f"{parent}: nested {key} SHA differs")
    return path


def _v25_graph(v25_path: Path) -> dict[str, dict[str, str]]:
    v13 = load(v25_path)
    if v13.get("schema") != "ds02.stage2.f2-parent-supervised-launch.v13":
        raise V30Error("V25 source is not the frozen v13 request")
    v12_path = _ref_path(v13.get("v12_launch", {}), "path", v25_path)
    v12 = load(v12_path)
    v11_path = _ref_path(v13.get("v11_launch", {}), "path", v25_path)
    v11 = load(v11_path)
    v10_path = _ref_path(v11.get("bridge_request", {}), "path", v11_path)
    v10 = load(v10_path)
    v7_path = _ref_path(v10.get("v7_request", {}), "path", v10_path)
    v7 = load(v7_path)
    command = v7.get("execution", {}).get("command", [])
    if not isinstance(command, list) or len(command) < 3:
        raise V30Error("frozen V25 v7 command does not bind an engine")
    engine = _require_file(command[2], "frozen V25 v7 engine")
    binding = next((x for x in v7.get("source_bindings", [])
                    if isinstance(x, Mapping) and x.get("role") == "portable_orchestrator_v7"), None)
    if not isinstance(binding, Mapping) or Path(str(binding.get("path", ""))).expanduser().resolve() != engine:
        raise V30Error("frozen V25 v7 command/source binding mismatch")
    v10_binding = next((x for x in v10.get("source_bindings", [])
                        if isinstance(x, Mapping) and x.get("role") == "v7_request"), None)
    if not isinstance(v10_binding, Mapping) or Path(str(v10_binding.get("path", ""))).expanduser().resolve() != v7_path:
        raise V30Error("frozen V25 bridge does not load its bound v7 request")
    if Path(str(v12.get("v11_launch", {}).get("path", ""))).expanduser().resolve() != v11_path:
        raise V30Error("frozen V25 v12/v11 edge is not continuous")
    nodes = {"v7_request": v7_path, "v10_bridge_request": v10_path,
             "v11_request": v11_path, "v12_request": v12_path,
             "v13_request": v25_path, "v7_engine": engine}
    return {role: {"path": str(path), "file_sha256": file_sha(path),
                   "canonical_sha256": load(path).get("sha256") if path.suffix == ".json" else None}
            for role, path in nodes.items()}


def _validate_frozen_inputs(v25_v13: Path, v26_v14: Path, v25_v7: Path,
                            overlay: Path, plan: Path, evaluator: Path) -> dict[str, Any]:
    graph = _v25_graph(v25_v13)
    v25 = load(v25_v13)
    v26 = load(v26_v14)
    v7 = load(v25_v7)
    overlay_value = load(overlay)
    plan_value = load(plan)
    eval_value = load(evaluator)
    if v26.get("schema") != "ds02.stage2.f2-parent-supervised-launch.v14":
        raise V30Error("V26 source is not the frozen v14 request")
    forward = v26.get("forward_of")
    if not isinstance(forward, Mapping):
        raise V30Error("V26 immutable forward edge is missing")
    _same_path(forward.get("path"), v25_v13, "V26.forward_of")
    if forward.get("sha256") != v25.get("sha256"):
        raise V30Error("V26.forward_of SHA is not the frozen V25 canonical SHA")
    if v7.get("schema") != "ds02.stage2.f2-portable-orchestration-request.v7":
        raise V30Error("V25 v7 schema differs")
    overlay_ref = v7.get("v5_inputs", {}).get("overlay", {})
    plan_ref = v7.get("storage_plan", {})
    _same_path(overlay_ref.get("path"), overlay, "V25 v7 overlay")
    _same_path(plan_ref.get("path"), plan, "V25 v7 storage plan")
    if overlay_ref.get("sha256") != file_sha(overlay) or plan_ref.get("sha256") != file_sha(plan):
        raise V30Error("V25 v7 input SHA differs from frozen overlay/plan bytes")
    input_hashes = v7.get("input_hashes", {})
    if input_hashes.get(str(overlay)) != file_sha(overlay) or input_hashes.get(str(plan)) != file_sha(plan):
        raise V30Error("V25 v7 input_hashes do not bind the exact overlay and plan")
    if overlay_value.get("schema") != "ds02.stage2.f2-native-raw-portable-overlay.v5":
        raise V30Error("overlay schema differs")
    if overlay_value.get("sha256") != canonical(overlay_value):
        raise V30Error("overlay canonical SHA differs")
    entries = overlay_value.get("entries")
    if not isinstance(entries, list) or len(entries) != OVERLAY_ENTRIES:
        raise V30Error(f"overlay entry count must be {OVERLAY_ENTRIES}")
    source_bytes = sum(int(item.get("expected_bytes", -1)) for item in entries if isinstance(item, Mapping))
    if source_bytes != OVERLAY_BYTES:
        raise V30Error("overlay source byte total differs from frozen 8.644 GB contract")
    if overlay_value.get("original_path_fallback") != "FORBIDDEN" or overlay_value.get("target_paths_are_new") is not True:
        raise V30Error("overlay does not fail closed on original-path fallback")
    if plan_value.get("schema") != "ds02.stage2.f2-portable-storage-plan.v5" or plan_value.get("sha256") != canonical(plan_value):
        raise V30Error("storage plan canonical schema/hash differs")
    budget = plan_value.get("storage_budget", {})
    if int(budget.get("required_new_storage_bytes", 0)) != V25_STORAGE_ESTIMATE:
        raise V30Error("V25 storage plan estimate differs; refusing to invent a smaller budget")
    if eval_value.get("schema") != "ds02.stage2.f2-no-model-evaluator-request.v3":
        raise V30Error("evaluator v3 request schema differs")
    if eval_value.get("sha256") != canonical(eval_value):
        raise V30Error("evaluator v3 request canonical SHA differs")
    if eval_value.get("model_invoked") is not False or eval_value.get("qualification") != UNKNOWN:
        raise V30Error("evaluator must remain model-free DEVELOPMENT/UNKNOWN")
    return {"v25": v25, "v26": v26, "v7": v7, "overlay": overlay_value,
            "plan": plan_value, "evaluator": eval_value, "graph": graph,
            "source_bytes": source_bytes, "entry_count": len(entries),
            "v25_file_sha256": file_sha(v25_v13), "v26_file_sha256": file_sha(v26_v14),
            "v7_file_sha256": file_sha(v25_v7), "overlay_file_sha256": file_sha(overlay),
            "plan_file_sha256": file_sha(plan), "evaluator_file_sha256": file_sha(evaluator)}


def _binding(path: Path, role: str) -> dict[str, Any]:
    target = _require_file(path, role)
    stat = target.stat()
    return {"role": role, "path": str(target), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": file_sha(target),
            "source_kind": "static", "content_scope": "content_sha256"}


def _contract(frozen: Mapping[str, Any], *, v25_v13: Path, v26_v14: Path,
              v25_v7: Path, overlay: Path, plan: Path, evaluator: Path,
              v15_output: Path, v24_output: Path, supervisor_root: Path,
              bundle_root: Path, products: Path, index_path: Path) -> dict[str, Any]:
    overlay_value = frozen["overlay"]
    plan_value = frozen["plan"]
    frozen_sources = {
        "v25_v13": {"path": str(v25_v13), "file_sha256": frozen["v25_file_sha256"],
                     "canonical_sha256": frozen["v25"]["sha256"], "immutable": True},
        "v26_v14": {"path": str(v26_v14), "file_sha256": frozen["v26_file_sha256"],
                     "canonical_sha256": frozen["v26"]["sha256"], "immutable": True,
                     "forward_of_v25_path_unchanged": True},
        "v25_v7": {"path": str(v25_v7), "file_sha256": frozen["v7_file_sha256"],
                    "canonical_sha256": frozen["v7"]["sha256"], "immutable": True},
        "overlay": {"path": str(overlay), "file_sha256": frozen["overlay_file_sha256"],
                     "canonical_sha256": overlay_value["sha256"], "immutable": True},
        "storage_plan": {"path": str(plan), "file_sha256": frozen["plan_file_sha256"],
                          "canonical_sha256": plan_value["sha256"], "immutable": True},
        "evaluator_v3_adapter": {"path": str(evaluator), "file_sha256": frozen["evaluator_file_sha256"],
                                  "canonical_sha256": frozen["evaluator"]["sha256"], "immutable": True},
    }
    return {
        "schema": "ds02.stage2.f2-portable-v29-bundle-contract.v1",
        "revision": "v30-v25-outer-v29-bundle-forward",
        "status": "READY_FOR_PARENT_GUARD_DEVELOPMENT_UNKNOWN",
        "role": "DEVELOPMENT",
        "qualification": dict(UNKNOWN),
        "frozen_provenance": frozen_sources,
        "v29_bundle": {
            "overlay_entry_count": int(frozen["entry_count"]),
            "source_bytes_from_overlay": int(frozen["source_bytes"]),
            "source_bytes_decimal": "8.644512838 GB",
            "original_path_fallback": "FORBIDDEN",
            "source_paths_are_provenance_only_after_seal": True,
            "current_catalog_alias_required": True,
            "sealed_copy_before_native_open": True,
            "path_map": {
                "frozen_target_root": str(Path(str(overlay_value["target_root"])).expanduser().resolve()),
                "fresh_target_root": str(bundle_root),
                "frozen_v25_output_root": str(Path(str(frozen["v7"]["execution"]["output_dir"])).expanduser().resolve()),
                "fresh_output_root": str(products),
                "all_actionable_paths_rebound": True,
                "provenance_uris_preserved": True,
                "old_target_or_original_open": "REJECT",
            },
            "immutable_v25_v26_forward_edges": True,
            "raw_bi4_hdf5_copy_and_read": "parent-approved slot only",
        },
        "outer_v25": {
            "request_path": str(v24_output),
            "request_file_sha256_deferred_until_request_seal": True,
            "entrypoint": str(V25_PATH),
            "entrypoint_sha256": file_sha(V25_PATH),
            "max_wall_seconds": 6000.0,
            "entry_timer_before_validation": True,
            "same_parent_reservation_before_content_validation": True,
            "helper_cleanup_grace_seconds": 25.0,
            "inner_v21_v22_accounting_owner": "existing DS-DATA-02 parent ledger",
            "parent_pid_and_own_process_groups": True,
            "finalization_scope": "local report/ledger cleanup is separately reported; no false hard-wall claim",
        },
        "request_chain": {
            "v15_adapter_request": str(v15_output),
            "v15_adapter_request_created_new": True,
            "v15_forward_of_v26_path_unchanged": True,
            "v25_request_created_new": True,
            "v25_v26_bytes_modified": False,
            "v29_graph": copy.deepcopy(frozen["graph"]),
            "no_latest_fallback": True,
        },
        "stages": [
            {"name": "parent_ledger_recheck_and_v25_outer_reservation", "io": "metadata_then_parent_guard"},
            {"name": "copy_all_overlay_entries", "entry_count": int(frozen["entry_count"]),
             "bytes": int(frozen["source_bytes"]), "destination_root": str(bundle_root),
             "overwrite": "REJECT", "original_fallback": "FORBIDDEN"},
            {"name": "post_copy_sha_seal_and_os_open_audit", "python_audit": "complementary",
             "c_open_audit": "parent strace/openat required"},
            {"name": "raw_to_typed_to_labels", "source": "fresh sealed relocated overlay",
             "reference_typed_hdf5": "comparison/provenance input only; never substitute for reconstruction"},
            {"name": "private_sdk", "fresh_subprocess": True, "bytecode": "-B",
             "clear_inherited_pythonpath": True, "module_file_closure": "fail on original worktree/data path"},
            {"name": "no_model_evaluator_v3", "request_source": str(evaluator),
             "model_invoked": False, "qualification": dict(UNKNOWN),
             "fresh_result_binding": "must be generated from this run; frozen v16 result cannot be used as a substitute"},
            {"name": "receipt_and_two_filesystem_charge", "same_parent_ledger": True,
             "home_floor_bytes": int(plan_value["parent_resource_binding"]["limits"]["home_min_free_bytes"]),
             "external_filesystem": str(plan_value["storage_mapping"]["selected_storage_root"]).split("/f2-s1-v25-replay-001")[0],
             "nested_v25_storage_estimate_bytes": V25_STORAGE_ESTIMATE,
             "outer_supervisor_storage_bytes": 16 * 1024 * 1024,
             "nested_and_outer_must_be_atomic_parent_guarded": True},
        ],
        "resource_contract": {
            "cpu_threads": 1,
            "inner_v25_max_wall_seconds": 5400,
            "outer_v25_max_wall_seconds": 6000,
            "max_rss_observational_bytes": 5 * 1024 * 1024 * 1024,
            "overlay_copy_bytes": int(frozen["source_bytes"]),
            "nested_storage_plan_required_bytes": int(plan_value["storage_budget"]["required_new_storage_bytes"]),
            "home_floor_preserved": True,
            "external_headroom_recheck_before_copy_and_before_loader": True,
            "ledger_reset": False,
            "new_data_root": False,
            "parent_deadline_utc": plan_value["parent_resource_binding"]["deadline_utc"],
            "cleanup_charge_idempotent": True,
        },
        "outputs": {
            "supervisor_root": str(supervisor_root),
            "bundle_target_root": str(bundle_root),
            "products_root": str(products),
            "accessible_index": str(index_path),
            "all_destinations_must_be_absent": True,
            "old_v25_destinations_must_not_be_reused": True,
        },
        "scientific_scope": {
            "model_invoked": False, "cfd_invoked": False, "quality": dict(UNKNOWN),
            "native_raw_to_typed_and_labels_are_development_evidence_only": True,
            "receiver_and_physical_fate": "UNKNOWN until separately qualified",
        },
    }


def build(*, v25_v13: Path = V25_V13, v26_v14: Path = V26_V14,
          v25_v7: Path = V25_V7, overlay: Path = V25_OVERLAY,
          plan: Path = V25_PLAN, evaluator: Path = EVALUATOR_V3,
          v15_output: Path = V30_V15, v24_output: Path = V30_V24,
          contract_output: Path = V30_CONTRACT,
          supervisor_root: Path = V30_ROOT / "supervisor-v24",
          bundle_root: Path = V30_BUNDLE_ROOT,
          products: Path = V30_PRODUCTS, index_path: Path = V30_INDEX) -> dict[str, Any]:
    paths = [v25_v13, v26_v14, v25_v7, overlay, plan, evaluator]
    for path in paths:
        _require_file(path, "explicit source")
    frozen = _validate_frozen_inputs(*(Path(x).expanduser().resolve() for x in paths))
    if any(Path(x).expanduser().resolve().exists() for x in (v15_output, v24_output, contract_output)):
        raise V30Error("refusing existing v30 request/contract")
    for destination in (supervisor_root, bundle_root, products):
        target = Path(destination).expanduser().resolve()
        if target.exists():
            raise V30Error(f"refusing existing v30 destination namespace: {target}")
        if target == EXTERNAL or EXTERNAL not in target.parents:
            raise V30Error(f"v30 destination must be a fresh child of the bound external filesystem: {target}")
    v15 = V15.build_request(Path(v26_v14).expanduser().resolve(), Path(v15_output).expanduser().resolve())
    v24 = V25.build_request(Path(v15_output).expanduser().resolve(), Path(v24_output).expanduser().resolve(),
                            output_root=Path(supervisor_root).expanduser().resolve(), max_wall_seconds=6000.0)
    contract = _contract(frozen, v25_v13=Path(v25_v13).expanduser().resolve(),
                         v26_v14=Path(v26_v14).expanduser().resolve(),
                         v25_v7=Path(v25_v7).expanduser().resolve(), overlay=Path(overlay).expanduser().resolve(),
                         plan=Path(plan).expanduser().resolve(), evaluator=Path(evaluator).expanduser().resolve(),
                         v15_output=Path(v15_output).expanduser().resolve(), v24_output=Path(v24_output).expanduser().resolve(),
                         supervisor_root=Path(supervisor_root).expanduser().resolve(),
                         bundle_root=Path(bundle_root).expanduser().resolve(), products=Path(products).expanduser().resolve(),
                         index_path=Path(index_path).expanduser().resolve())
    contract["sha256"] = canonical(contract)
    v24_value = load(v24_output)
    v24_value["portable_v29_bundle_contract_v30"] = copy.deepcopy(contract)
    bindings = list(v24_value.get("static_bindings", []))
    bindings.append(_binding(SCRIPT, "portable_v29_bundle_contract_builder_v30"))
    bindings.append(_binding(Path(evaluator).expanduser().resolve(), "no_model_evaluator_v3_contract"))
    v24_value["static_bindings"] = bindings
    v24_value["execution"] = dict(v24_value.get("execution", {}))
    v24_value["execution"]["portable_full_chain_entry"] = str(SCRIPT)
    v24_value["execution"]["portable_full_chain_contract"] = str(contract_output.expanduser().resolve())
    v24_value["execution"]["portable_full_chain_command"] = [
        str(v24_value["execution"].get("python", "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")),
        str(V25_PATH), "run", "--request", str(v24_output.expanduser().resolve()),
        "--io-slot-approved", "--parent-pid", "<parent-pid>"]
    v24_value["limitations"] = list(v24_value.get("limitations", [])) + [
        "The V25/V26 frozen forward graph is provenance and source authority; no consumed request is rewritten.",
        "The parent must apply the contract path map before native access and reject any old V25 destination/open.",
        "Fresh raw-to-label output and evaluator result are required; old typed/result products are not substitutes.",
    ]
    v24_value["sha256"] = V24.canonical_sha(v24_value)
    Path(v24_output).expanduser().resolve().unlink()
    write_new(v24_output, v24_value)
    sidecar = copy.deepcopy(contract)
    sidecar["request_binding"] = {"path": str(Path(v24_output).expanduser().resolve()),
                                   "file_sha256": file_sha(v24_output),
                                   "canonical_sha256": v24_value["sha256"]}
    sidecar["sha256"] = canonical(sidecar)
    write_new(contract_output, sidecar)
    return {"v15": v15, "v24": v24_value, "contract": sidecar,
            "frozen": frozen, "paths": {"v15": str(Path(v15_output).resolve()),
            "v24": str(Path(v24_output).resolve()), "contract": str(Path(contract_output).resolve())}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v25-v13", type=Path, default=V25_V13)
    parser.add_argument("--v26-v14", type=Path, default=V26_V14)
    parser.add_argument("--v25-v7", type=Path, default=V25_V7)
    parser.add_argument("--overlay", type=Path, default=V25_OVERLAY)
    parser.add_argument("--storage-plan", type=Path, default=V25_PLAN)
    parser.add_argument("--evaluator-v3", type=Path, default=EVALUATOR_V3)
    parser.add_argument("--v15-output", type=Path, default=V30_V15)
    parser.add_argument("--v24-output", type=Path, default=V30_V24)
    parser.add_argument("--contract-output", type=Path, default=V30_CONTRACT)
    parser.add_argument("--supervisor-root", type=Path, default=V30_ROOT / "supervisor-v24")
    parser.add_argument("--bundle-root", type=Path, default=V30_BUNDLE_ROOT)
    parser.add_argument("--products-root", type=Path, default=V30_PRODUCTS)
    parser.add_argument("--index-path", type=Path, default=V30_INDEX)
    args = parser.parse_args(argv)
    try:
        result = build(v25_v13=args.v25_v13, v26_v14=args.v26_v14, v25_v7=args.v25_v7,
                       overlay=args.overlay, plan=args.storage_plan, evaluator=args.evaluator_v3,
                       v15_output=args.v15_output, v24_output=args.v24_output,
                       contract_output=args.contract_output, supervisor_root=args.supervisor_root,
                       bundle_root=args.bundle_root, products=args.products_root, index_path=args.index_path)
    except (V30Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({"status": result["v24"].get("status"),
                      "v15": {"path": result["paths"]["v15"], "canonical_sha256": result["v15"]["sha256"]},
                      "v25": {"path": result["paths"]["v24"], "file_sha256": file_sha(result["paths"]["v24"]),
                              "canonical_sha256": result["v24"]["sha256"]},
                      "contract": {"path": result["paths"]["contract"],
                                    "file_sha256": file_sha(result["paths"]["contract"]),
                                    "canonical_sha256": result["contract"]["sha256"]},
                      "overlay_entries": result["frozen"]["entry_count"],
                      "overlay_bytes": result["frozen"]["source_bytes"]},
                     sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
