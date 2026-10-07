#!/usr/bin/env python3
"""Plan a source-bound output namespace for the F2 portable replay.

This module only reads small JSON metadata and filesystem statistics.  It does
not copy or open the HDF5/BI4 inputs, mutate the resource ledger, create an
output namespace, or move/delete an existing product.  The parent guard must
revalidate the live ledger semantics and perform the copy/replay under its
existing lease.

The plan keeps the human-accessible index below the DS-DATA-02 ``data`` tree
while mapping the potentially large per-reference products to one new,
namespaced directory on the filesystem with sufficient headroom.  A changed
live ledger SHA is allowed when the campaign, deadline, limits, and existing
parent lease remain the same; resetting the ledger or changing those semantic
bindings is rejected.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from datetime import datetime, timezone
from typing import Any, Mapping


UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
V4_BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v4"
V5_BUNDLE_SCHEMA = "ds02.stage2.f2-native-raw-to-label-bundle.v5"
PLAN_SCHEMA = "ds02.stage2.f2-portable-storage-plan.v5"
REQUEST_SCHEMA = "ds02.request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-portable-storage-validation.v5"
HEX64 = set("0123456789abcdef")
DEFAULT_LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
DEFAULT_CHECKPOINT = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/checkpoints/CHECKPOINT_001.json"
DEFAULT_DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DEFAULT_INDEX = DEFAULT_DATA_ROOT / "families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5/portable-output-index.json"
DEFAULT_STORAGE = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5/f2-s1-reference-products")
DEFAULT_REFERENCE_COUNT = 14
SAFETY_FRACTION = 0.05


class StorageV5Error(RuntimeError):
    """Raised when the parent resource/storage contract is unsafe."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    try:
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise StorageV5Error(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise StorageV5Error(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise StorageV5Error(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False)
        stream.write("\n")


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise StorageV5Error(f"{name} must be a lowercase SHA-256")
    return value


def _absolute(path: Path | str, name: str) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise StorageV5Error(f"{name} is missing: {target}")
    return target


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _parse_deadline(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise StorageV5Error(f"{name} is not an ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StorageV5Error(f"{name} is not an ISO timestamp") from error
    if result.tzinfo is None:
        raise StorageV5Error(f"{name} must include timezone")
    return result.astimezone(timezone.utc)


def _ledger_binding(ledger_path: Path, checkpoint_path: Path) -> dict[str, Any]:
    ledger = load_json(ledger_path)
    checkpoint = load_json(checkpoint_path)
    if ledger.get("schema") != "ds02.resource-ledger.v1":
        raise StorageV5Error("unexpected parent resource ledger schema")
    if ledger.get("campaign_id") != "DS-DATA-02":
        raise StorageV5Error("parent ledger campaign is not DS-DATA-02")
    limits = ledger.get("limits")
    if not isinstance(limits, Mapping):
        raise StorageV5Error("parent ledger limits are missing")
    required_limits = {"gpu_seconds", "cpu_core_seconds", "new_storage_bytes",
                       "qualification_attempts", "production_attempts",
                       "material_configurations", "material_cpu_fraction",
                       "fluid_learning_attempts", "storage_policy",
                       "home_min_free_bytes", "home_path"}
    if not required_limits.issubset(limits):
        raise StorageV5Error("parent ledger limits are incomplete")
    checkpoint_resources = checkpoint.get("resources")
    if not isinstance(checkpoint_resources, Mapping):
        raise StorageV5Error("checkpoint resources are missing")
    checkpoint_ledger = checkpoint_resources.get("ledger")
    if not isinstance(checkpoint_ledger, Mapping):
        raise StorageV5Error("checkpoint ledger binding is missing")
    if Path(str(checkpoint_ledger.get("path", ""))).expanduser().resolve() != ledger_path:
        raise StorageV5Error("checkpoint points to a different parent ledger")
    if checkpoint_resources.get("deadline_utc") != ledger.get("deadline_utc"):
        raise StorageV5Error("checkpoint and live ledger deadlines differ")
    if checkpoint_resources.get("limits") != limits:
        raise StorageV5Error("checkpoint and live ledger limits differ")
    live_sha = sha256_file(ledger_path)
    return {
        "path": str(ledger_path),
        "schema": ledger["schema"],
        "campaign_id": ledger["campaign_id"],
        "adopted_at_utc": ledger.get("adopted_at_utc"),
        "deadline_utc": ledger["deadline_utc"],
        "limits": copy.deepcopy(dict(limits)),
        "live_sha256_at_plan": live_sha,
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_file_sha256": sha256_file(checkpoint_path),
        "checkpoint_recorded_ledger_sha256": checkpoint_ledger.get("sha256"),
        "ledger_sha_may_change_within_same_parent_lease": True,
        "no_new_data_root_ledger": True,
        "no_reset": True,
        "semantic_revalidation_required_at_dispatch": True,
    }


def _disk_probe(path: Path) -> dict[str, Any]:
    target = path.expanduser().resolve()
    if not target.exists() or not target.is_dir():
        raise StorageV5Error(f"output filesystem probe root is unavailable: {target}")
    usage = shutil.disk_usage(target)
    return {"path": str(target), "total_bytes": int(usage.total),
            "used_bytes": int(usage.used), "free_bytes": int(usage.free),
            "probe_status": "READ_ONLY_STAT"}


def _validate_index_path(index_path: Path) -> None:
    data_root = DEFAULT_DATA_ROOT.resolve()
    families = (data_root / "families").resolve()
    if not _under(index_path, families):
        raise StorageV5Error("accessible index must remain below data/families")


def _validate_storage_namespace(storage_root: Path) -> None:
    var_tmp = Path("/var/tmp").resolve()
    if not _under(storage_root, var_tmp) or storage_root == var_tmp:
        raise StorageV5Error("large outputs must use a new namespace below /var/tmp")


def _v4_metadata(v4_request_path: Path, v4_bundle_path: Path, v4_overlay_path: Path) -> dict[str, Any]:
    request = load_json(v4_request_path)
    bundle = load_json(v4_bundle_path)
    overlay = load_json(v4_overlay_path)
    if bundle.get("schema") != V4_BUNDLE_SCHEMA or bundle.get("sha256") != canonical_sha(bundle):
        raise StorageV5Error("immutable v4 bundle is malformed or not canonical")
    if request.get("sha256") != canonical_sha(request):
        raise StorageV5Error("immutable v4 request is not canonical")
    if overlay.get("sha256") != canonical_sha(overlay):
        raise StorageV5Error("immutable v4 overlay is not canonical")
    if request.get("bundle", {}).get("canonical_sha256") != bundle.get("sha256"):
        raise StorageV5Error("v4 request is bound to another bundle")
    if overlay.get("bundle", {}).get("canonical_sha256") != bundle.get("sha256"):
        raise StorageV5Error("v4 overlay is bound to another bundle")
    reservation = request.get("resource_request", {}).get("new_storage_reservation_bytes")
    if isinstance(reservation, bool) or not isinstance(reservation, int) or reservation <= 0:
        raise StorageV5Error("v4 storage reservation is missing")
    return {"bundle_sha256": bundle["sha256"], "request_sha256": request["sha256"],
            "overlay_sha256": overlay["sha256"],
            "per_reference_reservation_bytes": reservation,
            "v4_h5_or_bi4_content_read": False,
            "v4_qualification": bundle.get("qualification")}


def build_plan(*, v4_bundle_path: Path | str, v4_request_path: Path | str,
               v4_overlay_path: Path | str, ledger_path: Path | str = DEFAULT_LEDGER,
               checkpoint_path: Path | str = DEFAULT_CHECKPOINT,
               index_path: Path | str = DEFAULT_INDEX,
               storage_root: Path | str = DEFAULT_STORAGE,
               reference_count: int = DEFAULT_REFERENCE_COUNT) -> dict[str, Any]:
    if isinstance(reference_count, bool) or not isinstance(reference_count, int) or reference_count <= 0:
        raise StorageV5Error("reference_count must be a positive integer")
    bundle_file = _absolute(v4_bundle_path, "v4 bundle")
    request_file = _absolute(v4_request_path, "v4 request")
    overlay_file = _absolute(v4_overlay_path, "v4 overlay")
    ledger_file = _absolute(ledger_path, "parent resource ledger")
    checkpoint_file = _absolute(checkpoint_path, "stage2 checkpoint")
    index = Path(index_path).expanduser().resolve()
    storage = Path(storage_root).expanduser().resolve()
    _validate_index_path(index)
    _validate_storage_namespace(storage)
    parent = _ledger_binding(ledger_file, checkpoint_file)
    v4 = _v4_metadata(request_file, bundle_file, overlay_file)
    home_path = Path(str(parent["limits"]["home_path"])).expanduser().resolve()
    home_probe = _disk_probe(home_path)
    storage_probe = _disk_probe(Path("/var/tmp"))
    per_reference = int(v4["per_reference_reservation_bytes"])
    reference_total = per_reference * reference_count
    safety = int(math.ceil(reference_total * SAFETY_FRACTION))
    required = reference_total + safety
    home_floor = int(parent["limits"]["home_min_free_bytes"])
    home_slack = max(0, home_probe["free_bytes"] - home_floor)
    home_sufficient = home_slack >= required
    tmp_sufficient = storage_probe["free_bytes"] >= required
    if not tmp_sufficient and not home_sufficient:
        raise StorageV5Error("neither home slack nor /var/tmp has sufficient headroom")
    selected_fs = str(home_path if home_sufficient else Path("/var/tmp").resolve())
    selected_root = str((home_path / "ds-data-02-stage2-output-v5").resolve()
                        if home_sufficient else storage)
    if home_sufficient:
        # The default namespace is intentionally /var/tmp; selecting Home is
        # allowed only when the live floor leaves the whole reservation free.
        selected_root = str((home_path / "ds-data-02-stage2-output-v5").resolve())
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "plan_id": "f2-s1-portable-storage-v5-001",
        "status": "READY_FOR_PARENT_STORAGE_GUARD",
        "role": "DEVELOPMENT",
        "qualification": copy.deepcopy(UNKNOWN),
        "model_invoked": False,
        "cfd_invoked": False,
        "v4_source_binding": v4,
        "parent_resource_binding": parent,
        "reference_output_count": reference_count,
        "storage_budget": {
            "per_reference_reservation_bytes": per_reference,
            "reference_reservation_total_bytes": reference_total,
            "safety_margin_fraction": SAFETY_FRACTION,
            "safety_margin_bytes": safety,
            "required_new_storage_bytes": required,
            "shared_ledger_new_storage_limit_bytes": int(parent["limits"]["new_storage_bytes"]),
            "within_shared_ledger_limit": required <= int(parent["limits"]["new_storage_bytes"]),
        },
        "filesystem_headroom": {
            "home": home_probe,
            "home_floor_bytes": home_floor,
            "home_slack_after_floor_bytes": home_slack,
            "home_sufficient_for_reference_set": home_sufficient,
            "var_tmp": storage_probe,
            "var_tmp_sufficient_for_reference_set": tmp_sufficient,
            "selected_filesystem": selected_fs,
            "headroom_check": "PASS",
        },
        "storage_mapping": {
            "mapping_schema": "ds02.stage2.namespaced-output-overlay.v1",
            "selected_storage_root": selected_root,
            "requested_namespace_root": str(storage),
            "accessible_index_path": str(index),
            "accessible_index_parent": str(index.parent),
            "index_remains_below_data_families": True,
            "large_outputs_are_not_written_below_accessible_index": True,
            "source_paths_unchanged": True,
            "existing_products_moved": False,
            "existing_products_deleted": False,
            "namespace_must_be_new": True,
            "parent_creates_namespace_only_after_guard": True,
        },
        "source_and_resource_policy": {
            "ledger_path_is_parent_owned": True,
            "preserve_parent_ledger_lease": True,
            "ledger_reset_forbidden": True,
            "deadline_reset_forbidden": True,
            "limits_reset_forbidden": True,
            "no_new_data_root": True,
            "hdf5_bi4_copy_or_read": "parent slot only",
            "output_index_write": "parent guard after successful run; new file only",
        },
        "inputs": {
            "v4_bundle": {"path": str(bundle_file), "sha256": sha256_file(bundle_file)},
            "v4_request": {"path": str(request_file), "sha256": sha256_file(request_file)},
            "v4_overlay": {"path": str(overlay_file), "sha256": sha256_file(overlay_file)},
            "parent_ledger": {"path": str(ledger_file), "sha256_at_plan": parent["live_sha256_at_plan"]},
            "checkpoint": {"path": str(checkpoint_file), "sha256": parent["checkpoint_file_sha256"]},
        },
        "limits": {
            "cpu_threads": 1,
            "max_wall_seconds": 5400,
            "max_rss_observational_bytes": 5 * 1024 ** 3,
            "all_qi_qn_qe": "UNKNOWN",
        },
        "limitations": [
            "This plan performs metadata/stat checks only; it has no HDF5/BI4 content-read credit.",
            "The parent guard must revalidate live ledger semantics and create the new namespace.",
            "A changed ledger SHA is accepted only with the same DS-DATA-02 parent campaign/deadline/limits.",
        ],
    }
    plan["sha256"] = canonical_sha(plan)
    return plan


def validate_plan(plan_path: Path | str) -> dict[str, Any]:
    plan_file = _absolute(plan_path, "v5 storage plan")
    plan = load_json(plan_file)
    if plan.get("schema") != PLAN_SCHEMA or plan.get("sha256") != canonical_sha(plan):
        raise StorageV5Error("storage plan is not canonical v5")
    if plan.get("status") != "READY_FOR_PARENT_STORAGE_GUARD":
        raise StorageV5Error("storage plan is not parent-guard ready")
    if plan.get("model_invoked") is not False or plan.get("cfd_invoked") is not False:
        raise StorageV5Error("storage plan cannot invoke model/CFD")
    parent = plan.get("parent_resource_binding")
    if not isinstance(parent, Mapping):
        raise StorageV5Error("parent resource binding is missing")
    ledger_file = _absolute(parent.get("path", ""), "live parent ledger")
    checkpoint_file = _absolute(parent.get("checkpoint_path", ""), "bound checkpoint")
    live = _ledger_binding(ledger_file, checkpoint_file)
    for key in ("campaign_id", "adopted_at_utc", "deadline_utc", "limits"):
        if live.get(key) != parent.get(key):
            raise StorageV5Error(f"parent lease semantic field changed: {key}")
    if parent.get("no_reset") is not True or parent.get("no_new_data_root_ledger") is not True:
        raise StorageV5Error("plan does not preserve parent ledger/lease")
    deadline = _parse_deadline(parent["deadline_utc"], "parent deadline")
    if datetime.now(timezone.utc) >= deadline:
        raise StorageV5Error("parent deadline has expired")
    mapping = plan.get("storage_mapping")
    if not isinstance(mapping, Mapping):
        raise StorageV5Error("storage mapping is missing")
    index = Path(str(mapping.get("accessible_index_path", ""))).expanduser().resolve()
    storage = Path(str(mapping.get("requested_namespace_root", ""))).expanduser().resolve()
    _validate_index_path(index)
    _validate_storage_namespace(storage)
    if mapping.get("existing_products_moved") is not False or mapping.get("existing_products_deleted") is not False:
        raise StorageV5Error("storage plan permits destructive product changes")
    probe = _disk_probe(Path(str(plan["filesystem_headroom"]["selected_filesystem"])))
    required = int(plan["storage_budget"]["required_new_storage_bytes"])
    if probe["free_bytes"] < required:
        raise StorageV5Error("selected output filesystem no longer has enough headroom")
    if storage.exists() and any(storage.iterdir()):
        raise StorageV5Error("requested output namespace already contains products")
    report = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_PARENT_SEMANTIC_AND_HEADROOM_RECHECK",
        "plan_path": str(plan_file),
        "plan_sha256": plan["sha256"],
        "live_ledger_sha256_at_validation": live["live_sha256_at_plan"],
        "ledger_sha_changed_since_plan": live["live_sha256_at_plan"] != parent.get("live_sha256_at_plan"),
        "parent_lease_semantics_preserved": True,
        "deadline_preserved": True,
        "limits_preserved": True,
        "selected_filesystem_recheck": probe,
        "required_new_storage_bytes": required,
        "namespace_empty_or_absent": not storage.exists() or not any(storage.iterdir()),
        "hdf5_or_bi4_content_read": False,
        "model_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
    }
    report["sha256"] = canonical_sha(report)
    return report


def build_request(plan_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    plan_file = _absolute(plan_path, "v5 storage plan")
    plan = load_json(plan_file)
    if plan.get("sha256") != canonical_sha(plan):
        raise StorageV5Error("storage plan is not canonical")
    validate = validate_plan(plan_file)
    v4 = plan["inputs"]
    input_files = [str(plan_file), str(v4["v4_bundle"]["path"]),
                   str(v4["v4_request"]["path"]), str(v4["v4_overlay"]["path"])]
    input_hashes = {str(plan_file): sha256_file(plan_file)}
    for item in (v4["v4_bundle"], v4["v4_request"], v4["v4_overlay"]):
        input_hashes[str(item["path"])] = sha256_file(item["path"])
    mapping = plan["storage_mapping"]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-portable-storage-v5-001",
        "status": "READY_FOR_PARENT_STORAGE_GUARD",
        "role": "DEVELOPMENT",
        "command": ["<parent-python>", "<portable_loader_v5>", "run", "--bundle", "<relocated-bundle>",
                     "--overlay", "<sealed-overlay>", "--output-dir", mapping["selected_storage_root"],
                     "--io-slot-approved", "--rehash-after-copy"],
        "input_files": input_files,
        "input_hashes": input_hashes,
        "resource_request": {
            "cpu_threads": plan["limits"]["cpu_threads"],
            "max_wall_seconds": plan["limits"]["max_wall_seconds"],
            "max_rss_observational_bytes": plan["limits"]["max_rss_observational_bytes"],
            "new_storage_reservation_bytes": plan["storage_budget"]["required_new_storage_bytes"],
            "storage_filesystem": mapping["selected_storage_root"],
            "parent_ledger_path": plan["parent_resource_binding"]["path"],
            "parent_deadline_utc": plan["parent_resource_binding"]["deadline_utc"],
            "parent_lease_preserved": True,
            "ledger_reset": False,
            "hdf5_or_bi4_read": "parent slot only",
            "os_open_audit_required": True,
        },
        "storage_mapping": mapping,
        "parent_resource_binding": plan["parent_resource_binding"],
        "metadata_preflight": validate,
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": copy.deepcopy(UNKNOWN),
        "no_existing_output_overwrite": True,
        "accessible_index_write_after_parent_run": mapping["accessible_index_path"],
        "limitations": plan["limitations"],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output_path, request)
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build-plan")
    p.add_argument("--v4-bundle", type=Path, required=True)
    p.add_argument("--v4-request", type=Path, required=True)
    p.add_argument("--v4-overlay", type=Path, required=True)
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    p.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    p.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE)
    p.add_argument("--reference-count", type=int, default=DEFAULT_REFERENCE_COUNT)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("validate")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("build-request")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-plan":
            value = build_plan(v4_bundle_path=args.v4_bundle, v4_request_path=args.v4_request,
                               v4_overlay_path=args.v4_overlay, ledger_path=args.ledger,
                               checkpoint_path=args.checkpoint, index_path=args.index,
                               storage_root=args.storage_root, reference_count=args.reference_count)
            write_new(args.output, value)
        elif args.command == "validate":
            value = validate_plan(args.plan)
            write_new(args.output, value)
        else:
            value = build_request(args.plan, args.output)
        print(json.dumps(value, sort_keys=True, ensure_ascii=False))
        return 0
    except (StorageV5Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
