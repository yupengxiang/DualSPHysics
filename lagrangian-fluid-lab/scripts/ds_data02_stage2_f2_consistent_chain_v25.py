#!/usr/bin/env python3
"""Create an additive v7→v10→v11→v12→v13 portable launch chain.

The consumed v19 request bytes are left untouched.  This forward builder
rewrites the complete request graph, including the v7 request, its overlay,
and its storage plan.  The bridge therefore loads the fresh v7 contract from
disk instead of retaining the old v7 path/output roots hidden inside v10.
All products use a fresh absent namespace and the same parent-owned trace;
this module only reads small JSON contracts and never opens HDF5/BI4 or
copies an output payload.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping


SCRIPT_DIR = Path(__file__).resolve().parent
V13_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v13.py"
V10_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_portable_ledger_bridge_v10.py"
V11_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v11.py"
V12_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_parent_launcher_v12.py"
V7_ENGINE_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_portable_orchestrator_v7.py"
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
OLD_V7 = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v7-f2-orchestration/f2-s1-portable-orchestration-request-v7-001.json")
OLD_V10_PATH = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v10-hardwall-v6/f2-s1-portable-ledger-bridge-request-v10-005.json")
OLD_V13 = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v13-venv/f2-s1-parent-supervised-launch-request-v13-001.json")
OLD_V12 = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v12-parent-supervised/f2-s1-parent-supervised-launch-request-v12-001.json")
OLD_V11 = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v11-parent-supervised/f2-s1-parent-supervised-launch-request-v11-001.json")
OUT_DIR = Path("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v25-consistent").resolve()
V7_OUT = OUT_DIR / "f2-s1-portable-orchestration-request-v7-012.json"
V7_OVERLAY_OUT = OUT_DIR / "f2-s1-native-raw-portable-overlay-v7-012.json"
V7_PLAN_OUT = OUT_DIR / "f2-s1-portable-storage-plan-v7-012.json"
V10_OUT = OUT_DIR / "f2-s1-portable-ledger-bridge-request-v10-012.json"
V11_OUT = OUT_DIR / "f2-s1-parent-supervised-launch-request-v11-012.json"
V12_OUT = OUT_DIR / "f2-s1-parent-supervised-launch-request-v12-012.json"
V13_OUT = OUT_DIR / "f2-s1-parent-supervised-launch-request-v13-012.json"
NEW_ATTEMPT = "f2-s1-portable-ledger-bridge-v10-012-v25"
NEW_V7_ID = "f2-s1-portable-orchestration-v7-012-forward"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V10 = _load("ds02_v10_chain_v19", V10_PATH)
V11 = _load("ds02_v11_chain_v19", V11_PATH)
V12 = _load("ds02_v12_chain_v19", V12_PATH)
V7 = _load("ds02_v7_chain_v25", V7_ENGINE_PATH)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite forward chain output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")


def _binding(role: str, path: Path | str, *, literal: bool = False) -> dict[str, Any]:
    spelling = Path(path).expanduser() if literal else Path(path).expanduser().resolve()
    resolved = spelling.resolve()
    stat = resolved.stat()
    return {"role": role, "path": str(spelling), "bytes": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256_file(resolved),
            "source_kind": "static"}


def _replace_binding(item: Mapping[str, Any], role: str, path: Path | str,
                     *, literal: bool = False) -> dict[str, Any]:
    result = _binding(role, path, literal=literal)
    if item.get("source_kind") == "parent":
        result["source_kind"] = "parent"
    return result


def _replace_path(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        result = value
        for old, new in replacements.items():
            result = result.replace(old, new)
        return result
    if isinstance(value, list):
        return [_replace_path(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_path(item, replacements) for key, item in value.items()}
    return value


def _set_canonical(value: dict[str, Any], module: Any) -> dict[str, Any]:
    value["sha256"] = module.canonical_sha(value)
    return value


def _new_namespace(old_v10: Mapping[str, Any]) -> tuple[str, str, str, str, str, str, str, str]:
    """Return the complete fresh namespace used by every forward contract."""
    old_fs = str(old_v10["external_storage_scope"]["filesystem"])
    old_target, old_selected = [str(item) for item in old_v10["external_storage_scope"]["roots"]]
    old_trace = next(item["path"] for item in old_v10["external_storage_scope"]["expected_artifacts"]
                     if item.get("role") == "parent_os_open_trace")
    new_prefix = old_fs + "/f2-s1-v25-replay-001"
    new_target = new_prefix + "/bundle-target-v25"
    new_selected = new_prefix + "/reference-products-v25"
    index_parent = str(old_v10["external_storage_scope"]["accessible_index_path"]).rsplit("/", 1)[0]
    new_index = index_parent + "/portable-output-index-v25.json"
    new_trace = old_fs + "/os-open-trace-v25.log"
    return old_fs, old_target, old_selected, old_trace, new_target, new_selected, new_index, new_trace


def _build_forward_plan(old_plan: dict[str, Any], output: Path, *, old_selected: str,
                        new_selected: str, old_index: str, new_index: str) -> dict[str, Any]:
    value = _replace_path(copy.deepcopy(old_plan), {
        old_selected: new_selected,
        old_index: new_index,
    })
    value["plan_id"] = "f2-s1-portable-storage-plan-v7-012-forward-v25"
    value["forward_of"] = {
        "prior_plan_path": str((OLD_V7.parent / "f2-s1-portable-storage-plan-v7-001.json").resolve()),
        "prior_plan_sha256": old_plan.get("sha256"),
        "immutable": True,
        "revision": "v7-bridge-request-graph-forward-v25",
    }
    value = _set_canonical(value, V7)
    write_new(output, value)
    return value


def _build_forward_overlay(old_overlay: dict[str, Any], output: Path, *, old_target: str,
                           new_target: str, bundle_path: Path) -> dict[str, Any]:
    value = _replace_path(copy.deepcopy(old_overlay), {old_target: new_target})
    value["bundle"] = {
        "path": str(bundle_path),
        "sha256": load(bundle_path).get("sha256"),
    }
    value["forward_of"] = {
        "prior_overlay_path": str((OLD_V7.parent / "f2-s1-native-raw-portable-overlay-v7-001.json").resolve()),
        "prior_overlay_sha256": old_overlay.get("sha256"),
        "immutable": True,
        "revision": "v7-target-namespace-forward-v25",
    }
    value = _set_canonical(value, V7)
    write_new(output, value)
    return value


def _build_forward_v7(old_v7: dict[str, Any], output: Path, *, old_target: str,
                      old_selected: str, old_index: str, new_target: str,
                      new_selected: str, new_index: str, plan_path: Path,
                      overlay_path: Path, plan: Mapping[str, Any],
                      overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Forward v7 and every private v5 path consumed by its engine.

    The old v7 request is the contract that v10 actually opens at run time.
    Updating only v10 therefore leaves the old target/output roots active.
    This function updates the v7 request, the overlay target paths, and the
    v7 storage plan as one graph, then records exact file SHA bindings for all
    three newly written JSON files.
    """
    value = _replace_path(copy.deepcopy(old_v7), {
        old_target: new_target,
        old_selected: new_selected,
        old_index: new_index,
    })
    value["request_id"] = NEW_V7_ID
    value["copy_contract"]["target_root"] = new_target
    value["execution"]["output_dir"] = new_selected
    value["execution"]["accessible_index_path"] = new_index
    value["execution"]["command"] = [str(VENV_PYTHON), "-B", str(V7_ENGINE_PATH),
                                       "run", "--request", "<request>", "--io-slot-approved"]
    value["execution"]["loader_entrypoint"] = str(V7_ENGINE_PATH.parent / "ds_data02_stage2_f2_raw_portable_v5.py")
    value["resource_request"]["storage_filesystem"] = new_selected
    value["storage_plan"] = {
        "path": str(plan_path),
        "sha256": sha256_file(plan_path),
        "schema": str(plan.get("schema")),
    }
    value["v5_inputs"]["overlay"] = {
        "path": str(overlay_path),
        "sha256": sha256_file(overlay_path),
    }
    value["source_bindings"] = list(value["source_bindings"])
    for item in value["source_bindings"]:
        role = str(item.get("role"))
        if role == "v5_storage_plan":
            item.update(_replace_binding(item, role, plan_path))
        elif role == "v5_overlay":
            item.update(_replace_binding(item, role, overlay_path))
        elif role == "portable_orchestrator_v7":
            item.update(_replace_binding(item, role, V7_ENGINE_PATH))
    value["input_files"] = [item["path"] for item in value["source_bindings"]]
    value["input_hashes"] = {item["path"]: item["sha256"] for item in value["source_bindings"]}
    value["forward_of"] = {
        "prior_request_path": str(OLD_V7.resolve()),
        "prior_request_sha256": sha256_file(OLD_V7),
        "prior_canonical_sha256": old_v7.get("sha256"),
        "immutable": True,
        "revision": "v7-overlay-plan-and-output-root-forward-v25",
    }
    value["limitations"] = list(value.get("limitations", [])) + [
        "v25 forwards the v7 request actually loaded by bridge v10; its overlay, storage plan, target root, output root and accessible index are one new graph.",
        "The original v7 request and all prior output namespaces remain immutable provenance; no source path fallback is permitted.",
    ]
    return _set_canonical(value, V7)


def _build_v10(old_v10: dict[str, Any], output: Path, *, v7_path: Path,
               v7: Mapping[str, Any], new_target: str, new_selected: str,
               new_index: str, old_fs: str, old_trace: str,
               old_attempt: str, old_v10_path: Path, new_trace: str,
               attempt: str) -> tuple[dict[str, Any], str, str, str]:
    old_target, old_selected = [str(item) for item in old_v10["external_storage_scope"]["roots"]]
    replacements = {old_target: new_target, old_selected: new_selected,
                    str(old_trace): new_trace, old_attempt: attempt}
    value = _replace_path(copy.deepcopy(old_v10), replacements)
    value["request_id"] = attempt
    value["attempt_id"] = attempt
    value["v7_request"] = {"path": str(v7_path), "sha256": sha256_file(v7_path),
                            "schema": str(v7.get("schema"))}
    value["external_storage_scope"]["accessible_index_path"] = new_index
    value["execution"]["v7_engine"] = str(V7_ENGINE_PATH)
    value["forward_of"] = {"prior_request_path": str(old_v10_path),
                           "prior_attempt_id": old_attempt,
                           "prior_request_sha256": old_v10.get("sha256"),
                           "v7_forward_request_path": str(v7_path),
                           "v7_forward_request_sha256": sha256_file(v7_path),
                           "immutable": True,
                           "revision": "v7-overlay-plan-output-forward-v25"}
    value["external_storage_scope"]["filesystem"] = old_fs
    value["external_storage_scope"]["roots"] = [new_target, new_selected]
    expected_artifacts = [dict(item) for item in value["external_storage_scope"]["expected_artifacts"]]
    for item in expected_artifacts:
        role = str(item.get("role"))
        if role == "v7_orchestration_report":
            item["path"] = str(Path(new_selected).parent / "orchestration-v7-report.json")
        elif role == "private_loader_receipt":
            item["path"] = str(Path(new_selected) / "private-loader-subprocess-v1.json")
        elif role == "v5_loader_report":
            item["path"] = str(Path(new_selected) / "portable-raw-to-label-run-report-v5.json")
        elif role == "python_access_audit":
            item["path"] = str(Path(new_selected) / "portable-python-access-audit-v5.json")
        elif role == "sealed_overlay":
            item["path"] = str(Path(new_target) / "sealed-overlay-v7.json")
        elif role == "native_output_root":
            item["path"] = str(Path(new_selected) / "native-v5")
        elif role == "parent_os_open_trace":
            item["path"] = new_trace
    value["external_storage_scope"]["expected_artifacts"] = expected_artifacts
    value["execution"]["command"] = [str(VENV_PYTHON), "-B", str(V10_PATH), "run",
                                       "--request", "<request>", "--io-slot-approved"]
    value["execution"]["entrypoint"] = str(V10_PATH)
    value["source_bindings"] = list(value["source_bindings"])
    for item in value["source_bindings"]:
        role = str(item.get("role"))
        if role == "v7_request":
            item.update(_replace_binding(item, role, v7_path))
        elif role == "v7:v5_overlay":
            item.update(_replace_binding(item, role, Path(str(v7["v5_inputs"]["overlay"]["path"]))))
        elif role == "v7:v5_storage_plan":
            item.update(_replace_binding(item, role, Path(str(v7["storage_plan"]["path"]))))
        elif role == "v7:portable_orchestrator_v7":
            item.update(_replace_binding(item, role, V7_ENGINE_PATH))
        elif role == "portable_ledger_bridge_v10":
            item.update(_replace_binding(item, role, V10_PATH))
    value["input_files"] = [item["path"] for item in value["source_bindings"]]
    value["input_hashes"] = {item["path"]: item["sha256"] for item in value["source_bindings"]}
    return _set_canonical(value, V10), old_fs, new_trace, attempt


def _build_v11(old_v11: dict[str, Any], v10: dict[str, Any], v10_path: Path,
               old_fs: str, new_trace: str, attempt: str, output: Path) -> dict[str, Any]:
    value = copy.deepcopy(old_v11)
    value["bridge_request"] = {"path": str(v10_path), "sha256": v10["sha256"],
                                "schema": v10["schema"], "attempt_id": attempt}
    value["trace"] = {"role": "parent_os_open_trace", "path": new_trace,
                       "required_for_completion": True}
    value["storage_scope"] = copy.deepcopy(value["storage_scope"])
    value["storage_scope"]["external_filesystem"] = old_fs
    value["storage_scope"]["external_roots"] = copy.deepcopy(v10["external_storage_scope"]["roots"])
    value["storage_scope"]["external_reserved_bytes"] = int(v10["reservation"]["external_product_reserved_bytes"])
    value["storage_scope"]["home_receipt_reserved_bytes"] = int(v10["reservation"]["home_receipt_reserved_bytes"])
    value["storage_scope"]["home_receipt_path"] = v10["external_storage_scope"]["home_receipt"]["path"]
    value["execution"] = copy.deepcopy(value["execution"])
    value["execution"]["python"] = str(VENV_PYTHON)
    value["execution"]["bridge"] = str(V10_PATH)
    value["execution"]["parent_supervised"] = [str(VENV_PYTHON), "-B", str(V11_PATH),
                                                   "run", "--request", "<request>",
                                                   "--parent-pid", "<supervisor_pid>"]
    value["execution"]["traced_bridge_template"] = ["/usr/bin/strace", "-f", "-e",
        "trace=openat,openat2,creat,truncate,rename,unlink,statx", "-o", new_trace,
        str(VENV_PYTHON), "-B", str(V10_PATH), "run", "--request", str(v10_path),
        "--io-slot-approved"]
    bindings = []
    for item in value["source_bindings"]:
        role = str(item["role"])
        path = str(item["path"])
        if role == "v10_bridge_request":
            bindings.append(_replace_binding(item, role, v10_path))
        elif role == "python_executable":
            bindings.append(_replace_binding(item, role, VENV_PYTHON, literal=True))
        else:
            bindings.append(dict(item))
    value["source_bindings"] = bindings
    value["input_files"] = [item["path"] for item in bindings]
    value["input_sha256"] = {item["path"]: item["sha256"] for item in bindings}
    value["forward_of"] = {"prior_request_path": str(OLD_V11),
                            "prior_request_sha256": old_v11.get("sha256"),
                            "bridge_request_sha256": v10["sha256"],
                            "immutable": True,
                            "revision": "fresh-v10-attempt-and-trace-v13"}
    return _set_canonical(value, V11)


def _update_nested_bindings(bindings: list[dict[str, Any]], path_map: Mapping[str, Path]) -> list[dict[str, Any]]:
    result = []
    for item in bindings:
        old_path = str(item.get("path", ""))
        chosen = next((path for key, path in path_map.items() if old_path == key), None)
        if chosen is None:
            result.append(dict(item))
        else:
            result.append(_replace_binding(item, str(item["role"]), chosen,
                                           literal=str(chosen) == str(VENV_PYTHON)))
    return result


def _build_v12(old_v12: dict[str, Any], v11: dict[str, Any], v11_path: Path,
               v10: dict[str, Any], v10_path: Path, old_fs: str, new_trace: str,
               attempt: str, output: Path) -> dict[str, Any]:
    value = copy.deepcopy(old_v12)
    value["v11_launch"] = {"path": str(v11_path), "sha256": v11["sha256"],
                            "file_sha256": sha256_file(v11_path),
                            "schema": v11["schema"], "attempt_id": attempt}
    value["trace"] = {"role": "parent_os_open_trace", "path": new_trace,
                       "required_for_completion": True}
    value["accounting"] = copy.deepcopy(value["accounting"])
    value["accounting"]["attempt_id"] = attempt
    value["accounting"]["home_receipt_path"] = v10["external_storage_scope"]["home_receipt"]["path"]
    value["storage_scope"] = copy.deepcopy(value["storage_scope"])
    value["storage_scope"]["external_filesystem"] = old_fs
    value["storage_scope"]["external_roots"] = copy.deepcopy(v10["external_storage_scope"]["roots"])
    value["storage_scope"]["trace_path"] = new_trace
    # v12 derives its sidecar from the shared trace stem.  v13 has its own
    # later sidecar name, so do not make the nested v12 contract claim the
    # v13 product path.
    value["storage_scope"]["finalization_sidecar"] = old_fs + "/os-open-trace-v13-finalization-v12.json"
    value["execution"] = copy.deepcopy(value["execution"])
    value["execution"]["python"] = str(VENV_PYTHON)
    value["execution"]["bridge"] = str(V10_PATH)
    value["execution"]["trace_finalization_sidecar"] = value["storage_scope"]["finalization_sidecar"]
    path_map = {str(Path(str(old_v12["v11_launch"]["path"])).expanduser().resolve()): v11_path,
                str(Path(str(old_v10_path := old_v12["source_bindings"][3]["path"])).expanduser().resolve()): v10_path}
    value["source_bindings"] = _update_nested_bindings(list(value["source_bindings"]), path_map)
    # The direct v11 request role is explicit in the v12 closure.
    for item in value["source_bindings"]:
        if item.get("role") == "v11_launch_request":
            item.update(_replace_binding(item, item["role"], v11_path))
        elif item.get("role") == "v11:v10_bridge_request":
            item.update(_replace_binding(item, item["role"], v10_path))
    value["input_files"] = [item["path"] for item in value["source_bindings"]]
    value["input_sha256"] = {item["path"]: item["sha256"] for item in value["source_bindings"]}
    value["forward_of"] = {"prior_request_path": str(OLD_V12),
                            "prior_request_sha256": old_v12.get("sha256"),
                            "v11_request_sha256": v11["sha256"],
                            "bridge_request_sha256": v10["sha256"],
                            "immutable": True, "revision": "fresh-trace-and-attempt-v13"}
    return _set_canonical(value, V12)


def _build_v13(old_v13: dict[str, Any], v12: dict[str, Any], v12_path: Path,
               v11: dict[str, Any], v11_path: Path, v10: dict[str, Any],
               v10_path: Path, old_fs: str, new_trace: str, attempt: str,
               output: Path) -> dict[str, Any]:
    value = copy.deepcopy(old_v13)
    value["v12_launch"] = {"path": str(v12_path), "sha256": v12["sha256"],
                            "file_sha256": sha256_file(v12_path),
                            "schema": v12["schema"], "attempt_id": attempt}
    value["v11_launch"] = {"path": str(v11_path), "sha256": v11["sha256"],
                            "file_sha256": sha256_file(v11_path),
                            "schema": v11["schema"], "attempt_id": attempt}
    value["attempt_id"] = attempt
    value["trace"] = {"role": "parent_os_open_trace", "path": new_trace,
                       "required_for_completion": True}
    value["accounting"] = copy.deepcopy(v12["accounting"])
    value["storage_scope"] = copy.deepcopy(v12["storage_scope"])
    value["storage_scope"]["external_filesystem"] = old_fs
    value["storage_scope"]["trace_path"] = new_trace
    value["storage_scope"]["finalization_sidecar"] = old_fs + "/f2-s1-v25-replay-001/os-open-trace-v25-finalization-v13.json"
    value["execution"] = copy.deepcopy(value["execution"])
    value["execution"]["python"] = str(VENV_PYTHON)
    value["execution"]["bridge"] = str(V10_PATH)
    value["execution"]["trace_finalization_sidecar"] = value["storage_scope"]["finalization_sidecar"]
    value["execution"]["parent_supervised"] = [str(VENV_PYTHON), "-B", str(V13_PATH),
                                                   "run", "--request", "<request>",
                                                   "--parent-pid", "<supervisor_pid>"]
    path_map = {
        str(Path(str(old_v13["v12_launch"]["path"])).expanduser().resolve()): v12_path,
        str(Path(str(old_v13["v11_launch"]["path"])).expanduser().resolve()): v11_path,
    }
    value["source_bindings"] = _update_nested_bindings(list(value["source_bindings"]), path_map)
    for item in value["source_bindings"]:
        role = str(item.get("role"))
        if role == "v12_launch_request":
            item.update(_replace_binding(item, role, v12_path))
        elif role == "v11_launch_request":
            item.update(_replace_binding(item, role, v11_path))
        elif "v10_bridge_request" in role:
            item.update(_replace_binding(item, role, v10_path))
    value["input_files"] = [item["path"] for item in value["source_bindings"]]
    value["input_sha256"] = {item["path"]: item["sha256"] for item in value["source_bindings"]}
    value["forward_of"] = {"prior_request_path": str(OLD_V13),
                            "prior_request_sha256": old_v13.get("sha256"),
                            "v12_request_sha256": v12["sha256"],
                            "v11_request_sha256": v11["sha256"],
                            "bridge_request_sha256": v10["sha256"],
                            "immutable": True, "revision": "consistent-v7-forward-attempt-trace-chain-v25"}
    value["limitations"] = list(value.get("limitations", [])) + [
        "v25 binds one fresh v7/v10 bridge attempt, v11 trace, v12/v13 sidecar and receipt path; no old attempt or old v7 output root is reused.",
        "This is metadata/source closure only until the parent grants the actual I/O slot.",
    ]
    return _set_canonical(value, _load("ds02_v13_chain_v19", V13_PATH))


def build() -> dict[str, Any]:
    old_v7 = load(OLD_V7)
    old_v13 = load(OLD_V13)
    old_v12 = load(OLD_V12)
    old_v11 = load(OLD_V11)
    old_v10_path = Path(str(old_v11["bridge_request"]["path"])).expanduser().resolve()
    old_v10 = load(old_v10_path)
    old_plan_path = Path(str(old_v7["storage_plan"]["path"])).expanduser().resolve()
    old_overlay_path = Path(str(old_v7["v5_inputs"]["overlay"]["path"])).expanduser().resolve()
    old_plan = load(old_plan_path)
    old_overlay = load(old_overlay_path)
    old_fs, old_target, old_selected, old_trace, new_target, new_selected, new_index, new_trace = _new_namespace(old_v10)
    if str(old_v7["copy_contract"]["target_root"]) != old_target:
        raise ValueError("old v7 and v10 target roots disagree")
    if str(old_v7["execution"]["output_dir"]) != old_selected:
        raise ValueError("old v7 and v10 output roots disagree")
    old_index = str(old_v7["execution"]["accessible_index_path"])
    outputs = (V7_OUT, V7_OVERLAY_OUT, V7_PLAN_OUT, V10_OUT, V11_OUT, V12_OUT, V13_OUT)
    if any(path.exists() for path in outputs):
        raise ValueError("one or more consistent chain outputs already exist")
    plan = _build_forward_plan(old_plan, V7_PLAN_OUT, old_selected=old_selected,
                               new_selected=new_selected, old_index=old_index,
                               new_index=new_index)
    overlay = _build_forward_overlay(
        old_overlay, V7_OVERLAY_OUT, old_target=old_target, new_target=new_target,
        bundle_path=Path(str(old_v7["v5_inputs"]["bundle"]["path"])).expanduser().resolve())
    v7 = _build_forward_v7(
        old_v7, V7_OUT, old_target=old_target, old_selected=old_selected,
        old_index=old_index, new_target=new_target, new_selected=new_selected,
        new_index=new_index, plan_path=V7_PLAN_OUT, overlay_path=V7_OVERLAY_OUT,
        plan=plan, overlay=overlay)
    write_new(V7_OUT, v7)
    attempt = NEW_ATTEMPT
    v10, old_fs, new_trace, attempt = _build_v10(
        old_v10, V10_OUT, v7_path=V7_OUT, v7=v7, new_target=new_target,
        new_selected=new_selected, new_index=new_index, old_fs=old_fs,
        old_trace=old_trace, old_attempt=str(old_v10["attempt_id"]),
        old_v10_path=old_v10_path,
        new_trace=new_trace, attempt=attempt)
    write_new(V10_OUT, v10)
    v11 = _build_v11(old_v11, v10, V10_OUT, old_fs, new_trace, attempt, V11_OUT)
    write_new(V11_OUT, v11)
    v12 = _build_v12(old_v12, v11, V11_OUT, v10, V10_OUT, old_fs, new_trace, attempt, V12_OUT)
    write_new(V12_OUT, v12)
    v13 = _build_v13(old_v13, v12, V12_OUT, v11, V11_OUT, v10, V10_OUT, old_fs, new_trace, attempt, V13_OUT)
    write_new(V13_OUT, v13)
    return {"v7": v7, "v10": v10, "v11": v11, "v12": v12, "v13": v13}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    result = build()
    print(json.dumps({key: {"path": str(path), "sha256": value["sha256"],
                            "attempt_id": value.get("attempt_id")}
                      for key, path, value in (("v7", V7_OUT, result["v7"]),
                                               ("v10", V10_OUT, result["v10"]),
                                               ("v11", V11_OUT, result["v11"]),
                                               ("v12", V12_OUT, result["v12"]),
                                               ("v13", V13_OUT, result["v13"]))},
                     sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
