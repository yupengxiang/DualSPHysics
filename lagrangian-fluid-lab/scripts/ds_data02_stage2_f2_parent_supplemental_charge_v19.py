#!/usr/bin/env python3
"""Apply the v13 trace-finalization delta under the existing parent ledger.

The v13 launcher intentionally does not mutate the Stage2 ledger.  This
forward-only helper is the parent-owned accounting step: it verifies the
immutable v13 sidecar, measures the final trace and sidecar bytes, and adds a
deterministic supplemental charge through the bound v6 ``ledger_locked`` API.
It never creates a ledger, a new data root, a lease, or a second accounting
owner.  Repeating the same request is idempotent; a differing byte or source
binding is rejected.

The trace itself is only stat'ed here.  v13 records the final trace byte count;
its older sidecar has no bridge-byte field, so this helper obtains the bridge
count from the bound immutable v10 terminal receipt (or accepts an explicit
sidecar field in a future compatible producer).  Missing bridge evidence is a
hard error rather than an inferred zero.  This keeps the parent finalization
bounded and leaves any full trace content hash to the OS guard/parent receipt.
No HDF5/BI4 content is opened.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import resource
import time
from typing import Any, Mapping


SCHEMA = "ds02.stage2.f2-parent-supplemental-charge.v19"
V13_SCHEMA = "ds02.stage2.f2-parent-supervised-launch.v13"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class SupplementalChargeError(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser()
    try:
        value = json.loads(target.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SupplementalChargeError(f"cannot read JSON {target}: {error}") from error
    if not isinstance(value, dict):
        raise SupplementalChargeError(f"JSON object required: {target}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists():
        raise SupplementalChargeError(f"refusing to overwrite output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise SupplementalChargeError(f"{name} must be a lowercase SHA-256")
    return value


def _cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_utime + usage.ru_stime)


def _load_runtime(path: Path, expected_sha: str):
    path = path.expanduser()
    if not path.is_file():
        raise SupplementalChargeError(f"bound runtime is missing: {path}")
    actual = sha256_file(path)
    if actual != expected_sha:
        raise SupplementalChargeError("bound runtime SHA differs")
    spec = importlib.util.spec_from_file_location("ds02_bound_runtime_v6_for_supplement", path)
    if spec is None or spec.loader is None:
        raise SupplementalChargeError(f"cannot import bound runtime: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "ledger_locked", None)):
        raise SupplementalChargeError("bound runtime lacks ledger_locked")
    return module


def _relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _v13_binding(v13_path: Path) -> dict[str, Any]:
    request = load_json(v13_path)
    if request.get("schema") != V13_SCHEMA or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise SupplementalChargeError("v13 request is not ready")
    if request.get("sha256") != canonical_sha(request):
        raise SupplementalChargeError("v13 request canonical SHA differs")
    accounting = request.get("accounting")
    storage = request.get("storage_scope")
    if not isinstance(accounting, Mapping) or not isinstance(storage, Mapping):
        raise SupplementalChargeError("v13 accounting/storage binding is missing")
    ledger_path = Path(str(accounting.get("ledger_path", ""))).expanduser()
    trace_path = Path(str(request.get("trace", {}).get("path", ""))).expanduser()
    sidecar_path = Path(str(storage.get("finalization_sidecar", ""))).expanduser()
    external = Path(str(storage.get("external_filesystem", ""))).expanduser()
    if not ledger_path.is_file():
        raise SupplementalChargeError(f"parent ledger is missing: {ledger_path}")
    if not trace_path.is_file() or not sidecar_path.is_file():
        raise SupplementalChargeError("final trace and immutable v13 sidecar must exist")
    if not external.is_dir() or not _relative_to(trace_path, external) or not _relative_to(sidecar_path, external):
        raise SupplementalChargeError("trace/sidecar must remain in the bound external filesystem")
    # The v10 request is the transitive source of the v6 runtime.  It is
    # copied into this new request explicitly so a relocated helper cannot
    # silently import a path from the original process environment.
    v11_path = Path(str(request.get("v11_launch", {}).get("path", ""))).expanduser()
    v11 = load_json(v11_path)
    bridge_request_path = Path(str(v11.get("bridge_request", {}).get("path", ""))).expanduser()
    bridge_request = load_json(bridge_request_path)
    runtime_binding = next((item for item in bridge_request.get("guard_bindings", [])
                            if isinstance(item, Mapping) and item.get("role") == "shared_runtime_v6"), None)
    if not isinstance(runtime_binding, Mapping):
        raise SupplementalChargeError("v10 bridge has no bound shared_runtime_v6")
    runtime_path = Path(str(runtime_binding.get("path", ""))).expanduser()
    runtime_sha = _sha(runtime_binding.get("sha256"), "shared_runtime_v6.sha256")
    return {
        "request": request,
        "v13_path": v13_path,
        "ledger_path": ledger_path,
        "attempt_id": str(accounting.get("attempt_id", "")),
        "receipt_path": Path(str(accounting.get("home_receipt_path", ""))).expanduser(),
        "trace_path": trace_path,
        "sidecar_path": sidecar_path,
        "external_filesystem": external,
        "runtime_path": runtime_path,
        "runtime_sha256": runtime_sha,
        "runtime_source_binding": dict(runtime_binding),
    }


def build_request(v13_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    bound = _v13_binding(Path(v13_path).expanduser())
    runtime_path = bound["runtime_path"]
    if not runtime_path.is_file():
        raise SupplementalChargeError(f"bound runtime is missing: {runtime_path}")
    v13_path = bound["v13_path"]
    parent_ledger = load_json(bound["ledger_path"])
    parent_limits = parent_ledger.get("limits", {})
    storage_policy = str(parent_limits.get("storage_policy", ""))
    if not storage_policy:
        raise SupplementalChargeError("parent ledger must declare a storage policy")
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "READY_FOR_PARENT_LEDGER",
        "role": "DEVELOPMENT_ACCOUNTING",
        "v13_request": {"path": str(v13_path), "sha256": bound["request"].get("sha256"),
                        "immutable": True},
        "parent_resource_binding": {
            "path": str(bound["ledger_path"]),
            "campaign_id": bound["request"].get("parent_resource_binding", {}).get("campaign_id"),
            "same_parent_ledger": True,
            "no_new_data_root": True,
            "ledger_owner": "parent supplemental helper under shared runtime ledger_locked",
        },
        "accounting": {
            "ledger_path": str(bound["ledger_path"]),
            "attempt_id": bound["attempt_id"],
            "supplemental_charge_id": bound["attempt_id"] + "::v13-trace-finalization-v19",
            "terminal_parent_charge_required": True,
            "idempotent": True,
            "charge_fields": ["trace_growth_after_bridge_charge_bytes", "sidecar_bytes", "cpu_core_seconds"],
        },
        "trace": {"path": str(bound["trace_path"]), "external_filesystem": str(bound["external_filesystem"])},
        "sidecar": {"path": str(bound["sidecar_path"]), "schema": "ds02.stage2.f2-parent-trace-finalization.v13"},
        "runtime_binding": {"path": str(runtime_path), "sha256": bound["runtime_sha256"], "role": "shared_runtime_v6"},
        "limits": {
            "deadline_utc": bound["request"].get("parent_resource_binding", {}).get("deadline_utc"),
            "home_min_free_bytes": bound["request"].get("storage_scope", {}).get("home_min_free_bytes"),
            "new_storage_bytes": parent_limits.get("new_storage_bytes"),
            "cpu_core_seconds": parent_limits.get("cpu_core_seconds"),
            "storage_policy": storage_policy,
            "home_path": parent_limits.get("home_path"),
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
        "limitations": [
            "Trace content is not reread or rehashed; final bytes come from stat and v13 sidecar evidence.",
            "This helper charges only the post-bridge trace delta, immutable v13 sidecar bytes, and its own bounded CPU.",
            "Repeated execution with the same bytes is idempotent; a changed sidecar/trace delta is rejected.",
            "Under home_free_floor, historical cumulative new_storage_bytes is retained as provenance and is not an active cap; live Home and external filesystem floors govern.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    write_new(output_path, request)
    return request


def _validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if request.get("schema") != SCHEMA or request.get("status") != "READY_FOR_PARENT_LEDGER":
        raise SupplementalChargeError("unsupported supplemental charge request")
    if request.get("sha256") != canonical_sha(request):
        raise SupplementalChargeError("supplemental request canonical SHA differs")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise SupplementalChargeError("supplemental helper must remain model-free")
    v13_ref = request.get("v13_request")
    if not isinstance(v13_ref, Mapping):
        raise SupplementalChargeError("v13 request binding is missing")
    v13_path = Path(str(v13_ref.get("path", ""))).expanduser()
    bound = _v13_binding(v13_path)
    if v13_ref.get("sha256") != bound["request"].get("sha256"):
        raise SupplementalChargeError("v13 request SHA differs")
    for section, key in (("trace", "trace_path"), ("sidecar", "sidecar_path")):
        value = request.get(section)
        if not isinstance(value, Mapping) or Path(str(value.get("path", ""))).expanduser() != bound[key]:
            raise SupplementalChargeError(f"{section} path differs from v13")
    runtime_binding = request.get("runtime_binding")
    if not isinstance(runtime_binding, Mapping) or Path(str(runtime_binding.get("path", ""))).expanduser() != bound["runtime_path"]:
        raise SupplementalChargeError("runtime path differs from transitive v10 binding")
    if runtime_binding.get("sha256") != bound["runtime_sha256"]:
        raise SupplementalChargeError("runtime SHA differs from transitive v10 binding")
    accounting = request.get("accounting")
    if not isinstance(accounting, Mapping) or accounting.get("ledger_path") != str(bound["ledger_path"]):
        raise SupplementalChargeError("ledger path differs from v13")
    if accounting.get("attempt_id") != bound["attempt_id"]:
        raise SupplementalChargeError("attempt id differs from v13")
    limits = request.get("limits")
    if not isinstance(limits, Mapping):
        raise SupplementalChargeError("explicit parent limits are required")
    requested_policy = str(limits.get("storage_policy", ""))
    if not requested_policy:
        raise SupplementalChargeError("explicit parent storage policy is required")
    current_limits = load_json(bound["ledger_path"]).get("limits", {})
    if str(current_limits.get("storage_policy", "")) != requested_policy:
        raise SupplementalChargeError("parent storage policy changed since request build")
    return bound


def _receipt_trace_bytes(receipt_path: Path, trace_path: Path) -> int | None:
    """Read only the v10 terminal receipt's trace artifact byte count.

    v13's sidecar schema predates the v12 ``bridge_receipt_trace_bytes``
    field.  Falling back to the final trace size would double-charge every
    byte, so a v19 helper requires either the explicit sidecar field or the
    immutable terminal receipt artifact record.
    """
    if not receipt_path.is_file():
        return None
    try:
        receipt = load_json(receipt_path)
    except SupplementalChargeError:
        return None
    artifact = receipt.get("filesystem", {}).get("artifact_check", {}).get("items", [])
    if not isinstance(artifact, list):
        return None
    for item in artifact:
        if not isinstance(item, Mapping) or item.get("role") != "parent_os_open_trace":
            continue
        if item.get("path") is not None and str(item.get("path")) != str(trace_path):
            continue
        value = item.get("bytes")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return int(value)
    return None


def _sidecar_accounting(bound: Mapping[str, Any]) -> dict[str, Any]:
    sidecar_path = Path(bound["sidecar_path"])
    trace_path = Path(bound["trace_path"])
    sidecar = load_json(sidecar_path)
    if sidecar.get("schema") != "ds02.stage2.f2-parent-trace-finalization.v13":
        raise SupplementalChargeError("unexpected v13 sidecar schema")
    if sidecar.get("request_sha256") != bound["request"].get("sha256"):
        raise SupplementalChargeError("sidecar request SHA differs")
    if sidecar.get("sha256") != canonical_sha(sidecar):
        raise SupplementalChargeError("v13 sidecar canonical SHA differs")
    trace = sidecar.get("trace")
    if not isinstance(trace, Mapping) or trace.get("path") != str(trace_path):
        raise SupplementalChargeError("sidecar trace binding differs")
    final_bytes = int(trace_path.stat().st_size)
    recorded_final = trace.get("bytes")
    if recorded_final is not None and int(recorded_final) != final_bytes:
        raise SupplementalChargeError("trace grew after v13 finalization sidecar")
    bridge_bytes = sidecar.get("bridge_receipt_trace_bytes")
    bridge_source = "v13_sidecar"
    if bridge_bytes is None:
        bridge_bytes = _receipt_trace_bytes(Path(bound["receipt_path"]), trace_path)
        bridge_source = "v10_terminal_receipt"
    delta_recorded = sidecar.get("trace_growth_after_bridge_charge_bytes")
    if bridge_bytes is None:
        raise SupplementalChargeError(
            "v13 sidecar has no bridge trace bytes and bound terminal receipt lacks an artifact record"
        )
    bridge_bytes = int(bridge_bytes)
    if bridge_bytes < 0 or bridge_bytes > final_bytes:
        raise SupplementalChargeError("sidecar bridge trace byte count is invalid")
    delta = final_bytes - bridge_bytes
    if delta_recorded is not None and int(delta_recorded) != delta:
        raise SupplementalChargeError("trace delta differs from sidecar")
    sidecar_bytes = sidecar_path.stat().st_size
    return {
        "sidecar_sha256": sidecar.get("sha256"),
        "trace_final_bytes": final_bytes,
        "bridge_trace_bytes": bridge_bytes,
        "bridge_trace_source": bridge_source,
        "trace_growth_after_bridge_charge_bytes": delta,
        "sidecar_bytes": sidecar_bytes,
        "supplemental_new_storage_bytes": int(delta + sidecar_bytes),
    }


def _lease_paths(ledger_path: Path, attempt_id: str) -> list[str]:
    root = ledger_path.parent / "leases"
    result = []
    if not root.is_dir():
        return result
    for path in root.glob("*.json"):
        try:
            value = load_json(path)
        except SupplementalChargeError:
            continue
        if value.get("attempt_id") == attempt_id:
            result.append(str(path))
    return result


def apply_charge(request_path: Path | str) -> dict[str, Any]:
    start_cpu = _cpu_seconds()
    started = time.monotonic()
    request_file = Path(request_path).expanduser()
    request = load_json(request_file)
    bound = _validate_request(request)
    runtime = _load_runtime(Path(str(request["runtime_binding"]["path"])),
                            str(request["runtime_binding"]["sha256"]))
    bytes_info = _sidecar_accounting(bound)
    accounting = request["accounting"]
    attempt_id = str(accounting["attempt_id"])
    supplement_id = str(accounting["supplemental_charge_id"])
    data_root = Path(str(bound["ledger_path"])).parent.parent
    now = datetime.now(timezone.utc)
    deadline = request.get("limits", {}).get("deadline_utc")
    if isinstance(deadline, str) and now >= datetime.fromisoformat(deadline):
        raise SupplementalChargeError("parent campaign deadline has passed")
    external = Path(str(bound["external_filesystem"]))
    stat = external.stat().st_dev
    del stat  # existence/device check is retained without reading the tree
    external_stat = __import__("os").statvfs(external)
    home_path = Path(str(bound["request"].get("parent_resource_binding", {}).get("limits", {}).get("home_path", data_root)))
    home_stat = __import__("os").statvfs(home_path)
    home_floor = int(request.get("limits", {}).get("home_min_free_bytes") or 0)
    if home_stat.f_bavail * home_stat.f_frsize < home_floor:
        raise SupplementalChargeError("Home free floor is not satisfied")
    if external_stat.f_bavail * external_stat.f_frsize < bytes_info["supplemental_new_storage_bytes"]:
        raise SupplementalChargeError("external filesystem lacks supplemental headroom")
    measured_cpu = max(0.0, _cpu_seconds() - start_cpu)
    finished = datetime.now(timezone.utc).isoformat()
    with runtime.ledger_locked(data_root) as ledger:
        charges = ledger.setdefault("charges", [])
        existing = [row for row in charges if isinstance(row, Mapping) and row.get("id") == supplement_id]
        if existing:
            row = existing[-1]
            comparable = (int(row.get("new_storage_bytes", -1)) == bytes_info["supplemental_new_storage_bytes"]
                          and str(row.get("parent_attempt_id")) == attempt_id
                          and row.get("status") == "completed")
            if not comparable:
                raise SupplementalChargeError("supplemental charge id already exists with different accounting")
            return {
                "schema": "ds02.stage2.f2-parent-supplemental-charge-report.v19",
                "status": "IDEMPOTENT_ALREADY_CHARGED",
                "charge": dict(row), "bytes": bytes_info,
                "cpu_core_seconds": float(row.get("cpu_core_seconds", 0.0)),
                "ledger_mutated": False, "elapsed_seconds": time.monotonic() - started,
                "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
            }
        parent_charges = [row for row in charges if isinstance(row, Mapping) and row.get("id") == attempt_id]
        if not parent_charges or any(str(row.get("status")) in {"reserved", "running"} for row in parent_charges):
            raise SupplementalChargeError("terminal parent charge is missing")
        reservations = [row for row in ledger.get("reservations", [])
                        if isinstance(row, Mapping) and row.get("id") == attempt_id]
        if reservations:
            raise SupplementalChargeError("parent reservation is still active")
        leases = _lease_paths(Path(str(bound["ledger_path"])), attempt_id)
        if leases:
            raise SupplementalChargeError("parent lease is still active")
        limits = ledger.get("limits", {})
        storage_policy = str(limits.get("storage_policy", ""))
        requested_policy = str(request.get("limits", {}).get("storage_policy", ""))
        if storage_policy != requested_policy:
            raise SupplementalChargeError("parent storage policy changed during accounting")
        # home_free_floor is an approved policy migration: historical
        # cumulative bytes remain provenance, while live Home and external
        # filesystem floors are the active storage guards.  A parent using an
        # explicit byte budget retains the legacy cumulative check.
        if storage_policy != "home_free_floor":
            used_bytes = sum(int(row.get("new_storage_bytes", 0)) for row in charges)
            max_bytes = limits.get("new_storage_bytes")
            if max_bytes is not None and used_bytes + bytes_info["supplemental_new_storage_bytes"] > int(max_bytes):
                raise SupplementalChargeError("parent new-storage limit would be exceeded")
        used_cpu = sum(float(row.get("cpu_core_seconds", 0.0)) for row in charges)
        max_cpu = limits.get("cpu_core_seconds")
        if max_cpu is not None and used_cpu + measured_cpu > float(max_cpu):
            raise SupplementalChargeError("parent CPU limit would be exceeded")
        row = {
            "id": supplement_id,
            "parent_attempt_id": attempt_id,
            "kind": "supplemental_trace_finalization_v19",
            "gpu_seconds": 0.0,
            "cpu_core_seconds": measured_cpu,
            "new_storage_bytes": bytes_info["supplemental_new_storage_bytes"],
            "trace_final_bytes": bytes_info["trace_final_bytes"],
            "trace_growth_after_bridge_charge_bytes": bytes_info["trace_growth_after_bridge_charge_bytes"],
            "sidecar_bytes": bytes_info["sidecar_bytes"],
            "sidecar_sha256": bytes_info["sidecar_sha256"],
            "storage_filesystems": [str(external), str(data_root)],
            "accounting_scope": "same_parent_v13_trace_delta_plus_immutable_sidecar_and_helper_cpu",
            "storage_policy": storage_policy,
            "historical_new_storage_cap_enforced": storage_policy != "home_free_floor",
            "status": "completed",
            "finished_at_utc": finished,
        }
        charges.append(row)
    return {
        "schema": "ds02.stage2.f2-parent-supplemental-charge-report.v19",
        "status": "SUPPLEMENTAL_CHARGE_APPLIED",
        "charge": row,
        "bytes": bytes_info,
        "cpu_core_seconds": measured_cpu,
        "ledger_mutated": True,
        "idempotent_charge_id": supplement_id,
        "elapsed_seconds": time.monotonic() - started,
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    build.add_argument("--v13-request", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("apply")
    run.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build-request":
        result = build_request(args.v13_request, args.output)
        output = {"status": result["status"], "sha256": result["sha256"]}
    else:
        output = apply_charge(args.request)
    print(json.dumps(output, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
